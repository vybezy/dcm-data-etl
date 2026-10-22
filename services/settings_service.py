"""settings rules: converts between stored text and real types, checks rules across fields."""

from config import BOOL_SETTINGS, typed_settings
from repositories import settings_repository
from services.errors import InvalidSettingsError


def get_settings() -> dict:
    """
    gets user's chosen settings
    """
    return typed_settings(settings_repository.get_all())


def update_settings(new: dict) -> dict:
    """
    updates settings table after checking if values inserted by the user are valid
    """
    if new["max_file_size"] <= new["min_file_size"]:
        raise InvalidSettingsError("max_file_size must be bigger than min_file_size")

    # table stores text, so convert back
    as_text = {
        key: ("true" if value else "false") if key in BOOL_SETTINGS else str(value)
        for key, value in new.items()
    }
    settings_repository.save_all(as_text)
    return new
