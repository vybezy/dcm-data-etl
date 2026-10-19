from fastapi import APIRouter

from services import stats_service

router = APIRouter(tags=["stats"])


@router.get("/stats")
def read_stats() -> dict:
    return stats_service.get_stats()
