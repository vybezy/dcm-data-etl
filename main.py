"""
DICOM ETL pipeline - command-line entry point.

Examples:
    python main.py                          # import ./data (or /data inside Docker)
    python main.py ./data --workers 8       # folder, 8 parallel workers
    python main.py "./data/*.dcm"           # wildcard
    python main.py ./data/instance-0155.dcm # single file
    python main.py ./data --dry-run         # validate only, insert nothing
    python main.py ./data --reset           # DROP and recreate all tables first

Exit codes: 0 = no errors, 1 = at least one file errored, 2 = bad input path.
"""
import os
import sys
import glob
import argparse

from config import DEFAULT_SETTINGS
from db_init import db_init
from utils import ImportOptions, download_dicom_from_azure
from database import create_import_session, load_settings_from_db
from processor import scan_and_import
from logger import logger


DOCKER_DATA_DIR = "/data"
LOCAL_DATA_DIR = "./data"


def parse_args(argv=None) -> argparse.Namespace:
    default_path = DOCKER_DATA_DIR if os.path.isdir(DOCKER_DATA_DIR) else LOCAL_DATA_DIR

    parser = argparse.ArgumentParser(
        description="Validate DICOM files and load their metadata into PostgreSQL."
    )
    parser.add_argument(
        "path", nargs="?", default=default_path,
        help=f"folder, single .dcm file, or wildcard pattern (default: {default_path})",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="number of parallel worker processes, 0 = sequential "
             "(default: 'workers' value in the dicom_settings table)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="run every validation and duplicate check but insert nothing",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="DROP and recreate all pipeline tables before importing (deletes all data)",
    )
    parser.add_argument(
        "--no-azure", action="store_true",
        help="skip the Azure Blob Storage download even if a connection string is set",
    )
    return parser.parse_args(argv)


def resolve_input(target_path: str):
    """
    Returns (base_folder, file_list) for a folder, a single file or a wildcard.
    file_list is None for a folder, meaning "scan the whole folder".
    Returns (None, None) if nothing matches.
    """
    if "*" in target_path or "?" in target_path:
        file_list = sorted(f for f in glob.glob(target_path) if os.path.isfile(f))
        if not file_list:
            return None, None
        return os.path.dirname(os.path.realpath(target_path)), file_list

    if os.path.isfile(target_path):
        return os.path.dirname(os.path.realpath(target_path)), [target_path]

    if os.path.isdir(target_path):
        return os.path.realpath(target_path), None

    return None, None


def main(argv=None) -> int:
    args = parse_args(argv)

    # optional cloud ingestion: only makes sense when the target is a folder
    if not args.no_azure and os.path.isdir(args.path):
        download_dicom_from_azure(args.path)

    base_folder, file_list = resolve_input(args.path)
    if base_folder is None:
        logger.error("Path not found or no files match: %s", args.path)
        return 2

    if args.reset:
        logger.warning("--reset given: dropping and recreating all pipeline tables")
    db_init(reset_tables=args.reset, logger=logger)

    session_id = create_import_session()
    settings = load_settings_from_db()

    # values from the database win; DEFAULT_SETTINGS covers any missing key
    settings = {**DEFAULT_SETTINGS, **settings}

    workers = args.workers if args.workers is not None else int(settings["workers"])

    options = ImportOptions(
        base_folder=base_folder,
        min_size=int(settings["min_file_size"]),
        max_size=int(settings["max_file_size"]),
        subject_min_length=int(settings["subject_min_length"]),
        max_file_age_months=int(settings["max_file_age_months"]),
        workers=workers,
        dry_run=args.dry_run,
        safe_dicom_folder=settings["safe_dicom_folder"],
        session_id=session_id,
    )

    logger.info("Session ID: %s", session_id)
    logger.info("Settings loaded: %s", settings)

    if file_list is None:
        logger.info("Importing all files from folder: %s", base_folder)
    else:
        logger.info("Importing %d specific file(s)", len(file_list))

    results = scan_and_import(base_folder, options, file_list=file_list)

    failed = [r for r in results if not r or r.get("status") == "error"]
    if failed:
        logger.error("%d file(s) failed with errors", len(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
