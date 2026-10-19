from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    # just checks if server is up
    return {"status": "ok"}
