import os
import glob
import psycopg2
from c3d_import import *
from db_init import db_init

RESET_TABLES = True

"""
calls importer based on target_path which could be:
- file ('C:\\data\\test1.c3d')
- wildcard ('C:\\data\\*.c3d')
- folder ('C:\\data')
goes through scan_and_import().
"""

if __name__ == "__main__":

    # check if running inside Docker
    if os.path.exists('/data'):
        target_path = '/data'

    db_init(reset_tables=RESET_TABLES, logger=logger)
    session_id = create_import_session()
    settings = load_settings_from_db()

    # determine base folder
    if os.path.isfile(target_path):
        base_folder = os.path.dirname(target_path)
        file_list = [target_path]
    elif "*" in target_path or "?" in target_path:
        file_list = [f for f in glob.glob(target_path) if os.path.isfile(f)]
        base_folder = os.path.dirname(target_path)
    elif os.path.isdir(target_path):
        base_folder = target_path
        file_list = None  # full folder scan
    else:
        print(f"Path not found: {target_path}")

    options = ImportOptions(
        base_folder=base_folder,
        min_size=int(settings.get("min_file_size", 300*1024)),
        max_size=int(settings.get("max_file_size", 99*1024*1024)),
        subject_min_length=int(settings.get("subject_min_length", 3)),
        max_file_age_months=int(settings.get("max_file_age_months", 24)),
        workers=int(settings.get("workers", 4)),
        safe_c3d_folder=settings.get("safe_c3d_folder"),
        session_id=session_id
    )

    logger.info("Session ID: %s", session_id)
    logger.info("Settings loaded: %s", settings)

    if file_list:
        print(f"Importing specific files ({len(file_list)}) ...")
        for f in file_list:
            scan_and_import(os.path.dirname(f), options)
    else:
        print(f"Importing all .c3d from folder: {target_path}")
        scan_and_import(target_path, options)
