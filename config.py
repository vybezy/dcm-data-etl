"""
database credentials from .env and the default import settings.
"""
import os

from dotenv import load_dotenv

DEFAULT_SETTINGS = {
    "min_file_size": str(100 * 1024),           # 100 KB
    "max_file_size": str(99 * 1024 * 1024),     # 99 MB
    "max_file_age_months": "1200",              # 100 years
    "workers": "4",                             # 0 = sequential
}


def is_true(value) -> bool:
    """true for 1, true or yes (any case). used for flags stored as text."""
    return str(value or "").strip().lower() in ("1", "true", "yes")


def typed_settings(stored: dict) -> dict:
    raw = {**DEFAULT_SETTINGS, **stored}
    return {key: int(raw[key]) for key in DEFAULT_SETTINGS}


def env_flag(name: str) -> bool:
    """true when an environment variable is set to 1, true or yes."""
    load_dotenv()
    return is_true(os.getenv(name))


def config():
    """
    returns the db connection settings
    from the environment / .env file.
    """
    load_dotenv()

    db = {
        "host": os.getenv("DB_HOST"),
        "database": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }

    # missing .env file / misspelled variable safety check
    if not all(db.values()):
        raise Exception(
            "Missing database credentials. Ensure a .env file exists "
            "with DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD defined."
        )

    db["port"] = os.getenv("DB_PORT", "5432")

    return db
