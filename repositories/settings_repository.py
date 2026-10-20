"""sql for the dicom_settings table."""

from database import db_connection, load_settings_from_db


def get_all() -> dict:
    """
    returns current settings from settings table
    """
    return load_settings_from_db()


def save_all(settings: dict) -> None:
    """
    updates settings table according to user's options
    """
    with db_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dicom_settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;",
            list(settings.items()),
        )
