from fastapi import APIRouter, HTTPException

from api.schemas import Settings
from services import settings_service
from services.errors import InvalidSettingsError

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=Settings)
def read_settings() -> dict:
    return settings_service.get_settings()


@router.put("/settings", response_model=Settings)
def replace_settings(settings: Settings) -> dict:
    try:
        return settings_service.update_settings(settings.model_dump())
    except InvalidSettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
