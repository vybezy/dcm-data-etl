"""pydantic models."""

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_file_size: int = Field(ge=0)
    max_file_size: int = Field(gt=0)
    max_file_age_months: int = Field(ge=1)
    workers: int = Field(ge=0, le=32)
    store_pixel_data: bool
