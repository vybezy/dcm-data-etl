from fastapi import APIRouter

from services import azure_service

router = APIRouter(tags=["azure"])


@router.get("/azure")
def azure_status() -> dict:
    return {"configured": azure_service.is_configured()}


@router.post("/azure/sync")
def sync_from_azure() -> dict:
    return azure_service.sync()
