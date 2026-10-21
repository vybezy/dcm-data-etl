from typing import Literal

from fastapi import APIRouter, Query, Response

from services import image_service

router = APIRouter(tags=["images"])


@router.get("/instances/{file_id}/image")
def read_image(
    file_id: int,
    window: Literal["auto", "lung", "soft_tissue", "bone"] = Query("auto"),
) -> Response:
    png = image_service.get_png(file_id, window)
    # not json this time: the body is the picture itself
    return Response(content=png, media_type="image/png")
