from fastapi import APIRouter

from api.schemas import Settings
from services import settings_service

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=Settings)
def read_settings() -> dict:
    return settings_service.get_settings()


@router.put("/settings", response_model=Settings)
def replace_settings(settings: Settings) -> dict:
    return settings_service.update_settings(settings.model_dump())
