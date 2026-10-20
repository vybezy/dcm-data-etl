"""settings rules: converts between stored text and real types, checks rules across fields."""

from config import DEFAULT_SETTINGS, is_true
from repositories import settings_repository
from services.errors import InvalidSettingsError

INT_KEYS = ("min_file_size", "max_file_size", "max_file_age_months", "workers")
BOOL_KEYS = ("store_pixel_data",)


def get_settings() -> dict:
    """
    gets user's chosen settings
    """
    # database values on top of defaults(same merge as main.py)
    raw = {**DEFAULT_SETTINGS, **settings_repository.get_all()}

    typed = {key: int(raw[key]) for key in INT_KEYS}
    typed.update({key: is_true(raw[key]) for key in BOOL_KEYS})
    return typed


def update_settings(new: dict) -> dict:
    """
    updates settings table after checking if values inserted by the user are valid
    """
    if new["max_file_size"] <= new["min_file_size"]:
        raise InvalidSettingsError("max_file_size must be bigger than min_file_size")

    # table stores text, so convert back
    as_text = {
        key: ("true" if value else "false") if key in BOOL_KEYS else str(value)
        for key, value in new.items()
    }
    settings_repository.save_all(as_text)
    return new
