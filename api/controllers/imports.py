from fastapi import APIRouter, Query

from api.schemas import ImportRequest
from services import imports_service

router = APIRouter(tags=["imports"])


@router.get("/imports")
def list_imports(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    return imports_service.list_imports(limit)


@router.get("/folders")
def list_folders() -> list[str]:
    return imports_service.list_folders()


@router.post("/imports", status_code=202)
def start_import(request: ImportRequest) -> dict:
    return imports_service.start_import(request.folder, request.dry_run)
