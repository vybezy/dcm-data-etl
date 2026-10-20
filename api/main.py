"""fastapi app: the http entry point into the pipeline."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.controllers import health, settings, stats
from services.errors import InvalidSettingsError, NotFoundError

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


app.include_router(health.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
