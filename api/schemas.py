"""pydantic models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_file_size: int = Field(ge=0)
    max_file_size: int = Field(gt=0)
    max_file_age_months: int = Field(ge=1)
    workers: int = Field(ge=0, le=32)
    store_pixel_data: bool


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "" or a sub-folder of data/ like "batch2/day1": no dots, no leading "/", so no ".."
    folder: str = Field(default="", max_length=200, pattern=r"^([\w\- ]+(/[\w\- ]+)*)?$")
    dry_run: bool = False


class ResetRequest(BaseModel):
    # must be exactly "RESET", so a stray click or a buggy script can't wipe the database
    confirm: Literal["RESET"]
