import os
import re
import hashlib
import pydicom
import calendar
from datetime import date, datetime, timezone, timedelta
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from config import config
import psycopg2
from utils import ImportOptions, ImportErrorWithContext, handle_exception, Profiler
from logger import pretty_log, logger
from database import log_db_event
from extractor import process_dicom_file, parse_dicom_date


# ------------------------- File Processing -------------------------


# checks if file name is valid
# Letters and digits of any alphabet (\w is Unicode-aware in Python 3), plus _ - . and space.
# Path separators and shell/special characters such as / \ : ; @ $ are rejected.
_FILENAME_PATTERN = re.compile(r"[\w\-. ]+")


def is_valid_filename(filename: str) -> bool:
    """Max 255 characters, made only of the characters in _FILENAME_PATTERN."""
    if len(filename) > 255:
        return False
    # fullmatch, not match(...$): '$' would also accept a trailing newline
    return _FILENAME_PATTERN.fullmatch(filename) is not None

def sanitize_and_validate_path(candidate: str, base_folder: str) -> str:
    base_abs = os.path.abspath(base_folder)
    candidate_real = os.path.realpath(candidate)
    if not os.path.exists(candidate_real):
        raise FileNotFoundError(f"Path does not exist: {candidate}")
    try:
        common = os.path.commonpath([base_abs, candidate_real])
    except ValueError as err:  # e.g. different drives on Windows
        raise ImportErrorWithContext(
            f"Candidate path {candidate_real} is not on the same filesystem as base {base_abs}"
        ) from err
    if common != base_abs:
        raise ImportErrorWithContext(f"Path traversal or escape detected: {candidate_real} is not under {base_abs}")
    return candidate_real

# DICOM date tags checked in order of preference when deciding how old a scan is
SCAN_DATE_TAGS = ("StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate")


def read_dicom_header(path: str):
    """Reads the DICOM header only (pixel data is skipped). Raises if the file is not valid DICOM."""
    return pydicom.dcmread(path, stop_before_pixels=True)


def subtract_months(day: date, months: int) -> date:
    """Calendar-correct 'N months before day' (Mar 31 minus 1 month -> Feb 28/29)."""
    total = day.year * 12 + (day.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def get_scan_date(dataset):
    """
    Returns (date, tag_name) for the first valid scan date in SCAN_DATE_TAGS,
    or (None, None) if the file has none.
    """
    for tag in SCAN_DATE_TAGS:
        iso = parse_dicom_date(dataset.get(tag, None))
        if iso:
            return date.fromisoformat(iso), tag
    return None, None


def check_scan_age(dataset, max_age_months: int, today: date = None):
    """
    Validates the scan's own date (not the file's timestamp on disk).
    Returns None if the scan is acceptable, otherwise the rejection reason.
    Files with no scan date are accepted, because there is nothing to judge.
    """
    today = today or datetime.now(timezone.utc).date()
    scan_date, tag = get_scan_date(dataset)
    if scan_date is None:
        return None
    oldest_allowed = subtract_months(today, max_age_months)
    if scan_date < oldest_allowed:
        return f"Scan too old: {tag}={scan_date} is before {oldest_allowed} (limit {max_age_months} months)"
    if scan_date > today + timedelta(days=1):  # 1 day of slack for time zones
        return f"Scan date in future: {tag}={scan_date}"
    return None


def compute_sha256(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest()

# main file processing
@Profiler
def process_file(path: str, options_dict: dict):
    options = ImportOptions(**options_dict)
    result = {"path": path, "status": "error", "message": "Initial", "db_file_id": None, "metadata": None}

    # set before the try so the except/finally blocks can always reference them,
    # even when config() or connect() is what failed
    params = None
    conn = None

    try:
        params = config()
        conn = psycopg2.connect(**params)

        try:
            abs_path = sanitize_and_validate_path(path, options.base_folder)
        except Exception as e:
            reason = f"Path validation failed: {e}"
            pretty_log("ERROR", "Import failed for file", file=path, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        filename = os.path.basename(abs_path)

        # Medical Standard: Check for .dcm
        if not filename.lower().endswith(".dcm"):
            reason = "Not a .dcm file"
            pretty_log("SKIP", "Skipped file", file=filename, extra=reason)
            log_db_event(conn, options, path, "SKIP", reason)
            result.update(status="skipped", message=reason)
            return result

        if not is_valid_filename(filename):
            reason = f"Invalid filename: {filename}"
            pretty_log("ERROR", "Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        st = os.stat(abs_path)
        if st.st_size < options.min_size or st.st_size > options.max_size:
            reason = f"File size ({st.st_size}) outside allowed range"
            pretty_log("ERROR", "Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        sha = compute_sha256(abs_path)

        # Duplicate check: has a file with identical content been imported before?
        with conn.cursor() as cur:
            cur.execute("SELECT file_id FROM dicom_instances WHERE file_sha256_hash = %s", (sha,))
            row = cur.fetchone()
            if row:
                reason = f"Duplicate file (SHA256={sha})"
                pretty_log("DUPLICATE", "Duplicate file", file=filename, extra=reason)
                log_db_event(conn, options, path, "DUPLICATE", reason)
                result.update(status="duplicate", message="Duplicate file", db_file_id=row[0])
                return result

        # Read the header once: used for the scan-date check and then for extraction
        try:
            dataset = read_dicom_header(abs_path)
        except Exception as e:
            reason = f"Unreadable DICOM file: {type(e).__name__}: {e}"
            pretty_log("ERROR", "Import failed for file", file=filename, extra=reason)
            logger.debug("Traceback for %s", filename, exc_info=True)
            log_db_event(conn, options, path, "ERROR", reason, exc=e)
            result.update(status="error", message=reason)
            return result

        reason = check_scan_age(dataset, options.max_file_age_months)
        if reason:
            pretty_log("ERROR", "Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result
        if get_scan_date(dataset)[0] is None:
            logger.warning("No scan date in %s; age check skipped", filename)

        if options.dry_run:
            pretty_log("DRYRUN", "Dry run - not inserted", file=filename)
            log_db_event(conn, options, path, "DRYRUN", "Dry run - not inserted")
            result.update(status="dry_run", message="Dry run - not inserted")
            return result

        # Delegate parsing and hierarchical database insertion to extractor.py
        try:
            file_id = process_dicom_file(conn, dataset, abs_path, filename, sha, st.st_size)
            conn.commit()

            pretty_log("SUCCESS", f"Successfully imported {filename} (ID: {file_id})", file=filename)
            log_db_event(conn, options, path, "SUCCESS", f"Imported file (ID={file_id})")
            result.update(status="inserted", message="Successfully imported", db_file_id=file_id)
            return result

        except psycopg2.errors.UniqueViolation as e:
            conn.rollback()
            reason = "Duplicate detected during hierarchical insert"
            pretty_log("DUPLICATE", "Duplicate file", file=filename, extra=reason)
            log_db_event(conn, options, path, "DUPLICATE", reason, exc=e)
            result.update(status="duplicate", message="Duplicate detected during insert")
            return result

        except Exception as e:
            conn.rollback()
            reason = f"Extraction/Insert error: {type(e).__name__}: {e}"
            pretty_log("ERROR", "Import failed for file", file=filename, extra=reason)
            # full traceback: hidden from normal console output (DEBUG level),
            # but always stored in dicom_logger.log_stack_trace via exc=e
            logger.debug("Traceback for %s", filename, exc_info=True)
            log_db_event(conn, options, path, "ERROR", reason, exc=e)
            result.update(status="error", message=reason)
            return result

    except Exception as e:
        reason = f"Exception: {e}"
        pretty_log("CRITICAL", "Critical error in worker", file=path, extra=reason)

        # Log to the DB on a fresh connection (the original one may be broken or
        # may never have opened). If that also fails, the console log above is
        # enough - never let the logging attempt hide the original error.
        if params is not None:
            log_conn = None
            try:
                log_conn = psycopg2.connect(**params)
                log_db_event(log_conn, options, path, "CRITICAL", reason, exc=e)
            except Exception as log_err:
                logger.error("Could not write CRITICAL event to the database: %s", log_err)
            finally:
                if log_conn is not None:
                    log_conn.close()

        result.update(status="error", message=reason)
        return result

    finally:
        if conn is not None:
            conn.close()

# file import process

def scan_and_import(folder: str, options: ImportOptions, file_list: list = None):
    """
    Imports every file under `folder`, or only the files in `file_list` if given.
    Returns one result dict per file.
    """
    if file_list is None:
        # grabs every file so process_file() can demonstrate the skip logic
        file_list = [os.path.join(root, f) for root, _, files in os.walk(folder) for f in files]
    logger.info("Found %d file(s) to process", len(file_list))

    options_dict = asdict(options)  # convert dataclass to dict

    results = []

    # parallel execution using ProcessPoolExecutor
    if options.workers and options.workers > 0:
        logger.info("Running with %d workers (ProcessPoolExecutor)", options.workers)

        with ProcessPoolExecutor(max_workers=options.workers) as executor:
            # submit all files to the pool at once
            future_to_file = {executor.submit(process_file, f, options_dict): f for f in file_list}

            # as each job finishes, grab the result
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    handle_exception(e, options, file_path=file_path, level="CRITICAL")
                    # record the crash so it is counted in the summary and exit code
                    results.append({"path": file_path, "status": "error", "message": str(e)})

    # sequential fallback
    else:
        logger.info("Running sequentially")
        for f in file_list:
            try:
                res = process_file(f, options_dict)
                results.append(res)
            except Exception as e:
                handle_exception(e, options, file_path=f, level="CRITICAL")
                results.append({"path": f, "status": "error", "message": str(e)})

    # summarize results
    summary = {"inserted": 0, "duplicate": 0, "invalid": 0, "skipped": 0, "dry_run": 0, "error": 0}
    for r in results:
        if r and "status" in r and r["status"] in summary:
            summary[r["status"]] += 1
        else:
            summary["error"] += 1

    logger.info("Import summary: %s", summary)
    return results