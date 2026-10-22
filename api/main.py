"""fastapi app: the http entry point into the pipeline."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.controllers import admin, browse, health, images, imports, settings, stats
from services.errors import (ConflictError, InvalidSettingsError, NotFoundError,
                             UnsupportedImageError)

app = FastAPI(
    title="DICOM ETL API",
    description="http api for dicom etl pipeline",
    version="0.1.0",
)


@app.exception_handler(NotFoundError)
def handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidSettingsError)
def handle_invalid_settings(request: Request, exc: InvalidSettingsError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
def handle_conflict(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(UnsupportedImageError)
def handle_unsupported_image(request: Request, exc: UnsupportedImageError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


app.include_router(health.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(browse.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(images.router, prefix="/api")

app.mount("/", StaticFiles(directory="web", html=True), name="web")
