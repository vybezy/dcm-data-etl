from fastapi import APIRouter

from api.schemas import ResetRequest
from services import admin_service

router = APIRouter(tags=["admin"])


@router.post("/admin/reset")
def reset_database(request: ResetRequest) -> dict:
    # request is only here for validation: it got past pydantic, so it says "RESET"
    admin_service.reset_database()
    return {"status": "reset"}
