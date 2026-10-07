"""
database credentials from .env and the default import settings.
"""
import os
from dotenv import load_dotenv


# default import settings: the single source of truth.
# db_init() seeds the dicom_settings table from this dict, and main.py falls back
# to it if a key is missing. Values are strings because the table stores TEXT.
DEFAULT_SETTINGS = {
    "min_file_size": str(100 * 1024),           # 100 KB
    "max_file_size": str(99 * 1024 * 1024),     # 99 MB
    "max_file_age_months": "1200",              # 100 years
    "workers": "4",                             # 0 = sequential
}

def config():
    """returns the database connection settings from the environment / .env file."""
    load_dotenv()

    db = {
        'host': os.getenv('DB_HOST'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }

    # missing .env file / misspelled variable safety check
    if not all(db.values()):
        raise Exception(
            "Missing database credentials. Ensure a .env file exists "
            "with DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD defined."
        )

    # optional: defaults to the standard PostgreSQL port
    db['port'] = os.getenv('DB_PORT', '5432')

    return db
