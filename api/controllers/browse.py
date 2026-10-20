from fastapi import APIRouter, Query

from services import browse_service

router = APIRouter(tags=["browse"])


@router.get("/patients")
def list_patients(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    return browse_service.list_patients(limit, offset)


@router.get("/patients/{patient_id}/studies")
def list_studies(patient_id: int) -> list[dict]:
    return browse_service.list_studies(patient_id)


@router.get("/studies/{study_id}/series")
def list_series(study_id: int) -> list[dict]:
    return browse_service.list_series(study_id)


@router.get("/series/{series_id}/instances")
def list_instances(series_id: int) -> list[dict]:
    return browse_service.list_instances(series_id)
