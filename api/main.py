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


ERROR_STATUS = {
    NotFoundError: 404,
    InvalidSettingsError: 422,
    ConflictError: 409,
    UnsupportedImageError: 422,
}


def handle_service_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=ERROR_STATUS[type(exc)], content={"detail": str(exc)})


for error in ERROR_STATUS:
    app.add_exception_handler(error, handle_service_error)

for controller in (health, stats, settings, browse, imports, admin, images):
    app.include_router(controller.router, prefix="/api")

app.mount("/", StaticFiles(directory="web", html=True), name="web")
