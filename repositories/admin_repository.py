"""the reset: drops and recreates every pipeline table."""

from db_init import db_init
from logger import logger


def reset_tables() -> None:
    # same as main.py --reset. also resets dicom_settings to the defaults
    # and empties the import history (the logger tables are dropped too)
    db_init(reset_tables=True, logger=logger)
