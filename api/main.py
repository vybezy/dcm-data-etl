"""fastapi app: the http entry point into the pipeline."""

from fastapi import FastAPI

from api.controllers import health, settings, stats

app = FastAPI(
    title="DICOM ETL API",
    description="http api for dicom etl pipeline",
    version="0.1.0",
)

app.include_router(health.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
