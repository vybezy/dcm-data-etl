import os
import re
import hashlib
import ezc3d
from datetime import datetime, timezone, timedelta
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from config import config
import psycopg2
from utils import ImportOptions, ImportErrorWithContext, handle_exception, Profiler
from logger import pretty_log, logger
from database import log_db_event
from extractor import process_c3d_metadata


# ------------------------- File Processing -------------------------


# checks if file name is valid
def is_valid_filename(filename: str) -> bool:
    # max length 255, only allow alphanum, dash, underscore, dot, space
    if len(filename) > 255:
        return False
    # doesn't allow unusual characters (allows: Greek, Latin, numbers, dash, underscore, dot, space)
    return re.match(r"^[\w\-. \u0370-\u03FF]+$", filename) is not None

def sanitize_and_validate_path(candidate: str, base_folder: str) -> str:
    base_abs = os.path.abspath(base_folder)
    candidate_real = os.path.realpath(candidate)
    if not os.path.exists(candidate_real):
        raise FileNotFoundError(f"Path does not exist: {candidate}")
    try:
        common = os.path.commonpath([base_abs, candidate_real])
    except ValueError:
        raise ImportErrorWithContext(f"Candidate path {candidate_real} is not on the same filesystem as base {base_abs}")
    if common != base_abs:
        raise ImportErrorWithContext(f"Path traversal or escape detected: {candidate_real} is not under {base_abs}")
    return candidate_real

def compute_sha256(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest()

# main file processing
@Profiler
def process_file(path: str, options_dict: dict):
    options = ImportOptions(**options_dict)
    result = {"path": path, "status": "error", "message": "Initial", "db_file_id": None, "metadata": None}
    try:
        params = config()
        conn = psycopg2.connect(**params)
        if not conn:
            result.update(status="error", message="Database connection failed")
            return result
        # path traversal and filename checks
        try:
            abs_path = sanitize_and_validate_path(path, options.base_folder)
        except Exception as e:
            reason = f"Path validation failed: {e}"
            pretty_log("ERROR", f"Import failed for file", file=path, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        filename = os.path.basename(abs_path)
        if not filename.lower().endswith(".c3d"):
            reason = "Not a .c3d file"
            pretty_log("SKIP", f"Skipped file", file=filename, extra=reason)
            log_db_event(conn, options, path, "SKIP", reason)
            result.update(status="skipped", message=reason)
            return result
                
        if not is_valid_filename(filename):
            reason = f"Invalid filename: {filename}"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        st = os.stat(abs_path)
        if st.st_size < options.min_size or st.st_size > options.max_size:
            reason = f"File size ({st.st_size}) outside allowed range"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        file_date = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        if file_date < datetime.now(timezone.utc) - timedelta(days=options.max_file_age_months*30):
            reason = f"File too old: {file_date}"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result
        if file_date > datetime.now(timezone.utc) + timedelta(days=30):
            reason = f"File date in future: {file_date}"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        # subject name extraction (robust, with fallback to filename)
        try:
            c3d = ezc3d.c3d(abs_path)
        except Exception as e:
            reason = f"Could not open C3D file: {e}"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        subject_name = ""
        try:
            subject_labels = c3d['parameters']['SUBJECTS']['LABELS']['value']
            if subject_labels and isinstance(subject_labels, list) and subject_labels[0]:
                subject_name = str(subject_labels[0])
        except Exception:
            pass
        if not subject_name:
            try:
                subject_name = c3d['parameters']['SUBJECT']['NAME']['value']
            except Exception:
                pass
        if not subject_name:
            try:
                subject_name = c3d['parameters']['SUBJECTS']['NAME']['value']
            except Exception:
                pass
        if not subject_name:
            try:
                subject_name = c3d['parameters']['SUBJECTS']['LABEL']['value']
            except Exception:
                pass
        if not subject_name:
            base = os.path.basename(abs_path)
            subject_name = base[:-4] if base.lower().endswith('.c3d') else base
        subject_name = subject_name.strip()

        if not isinstance(subject_name, str):
            subject_name = str(subject_name)
        if len(subject_name) < options.subject_min_length:
            reason = f"Subject name '{subject_name}' too short (min {options.subject_min_length})"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="invalid", message=reason)
            return result

        sha = compute_sha256(abs_path)

         # duplicate check (SHA256)
        with conn.cursor() as cur:
            cur.execute("SELECT file_id FROM c3d_files WHERE file_sha256_hash = %s", (sha,))
            row = cur.fetchone()
            if row:
                reason = f"Duplicate file (SHA256={sha})"
                pretty_log("DUPLICATE", f"Duplicate file", file=filename, extra=reason)
                log_db_event(conn, options, path, "DUPLICATE", reason)
                result.update(status="duplicate", message="Duplicate file", db_file_id=row[0])
                return result

        # insert file metadata (if not dry run)
        if options.dry_run:
            pretty_log("DRYRUN", f"Dry run - not inserted", file=filename)
            log_db_event(conn, options, path, "DRYRUN", "Dry run - not inserted")
            result.update(status="dry_run", message="Dry run - not inserted")
            return result

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO c3d_files (file_name, file_path, file_date, file_size, file_sha256_hash, file_subject_name)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING file_id;
                """, (
                    filename, abs_path, file_date, st.st_size, sha, subject_name
                ))
                file_id = cur.fetchone()[0]
                conn.commit()

                process_c3d_metadata(file_id, abs_path)

                pretty_log("SUCCESS", f"Successfully imported {filename} (ID: {file_id})", file=filename)
                log_db_event(conn, options, path, "SUCCESS", f"Imported file (ID={file_id})")
                result.update(status="inserted", message="Successfully imported", db_file_id=file_id)
                return result
            
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            reason = f"Duplicate detected during insert (SHA256={sha})"
            pretty_log("DUPLICATE", f"Duplicate file", file=filename, extra=reason)
            log_db_event(conn, options, path, "DUPLICATE", reason)
            result.update(status="duplicate", message="Duplicate detected during insert")
            return result
        
        except Exception as e:
            conn.rollback()
            reason = f"Insert error: {e}"
            pretty_log("ERROR", f"Import failed for file", file=filename, extra=reason)
            log_db_event(conn, options, path, "ERROR", reason)
            result.update(status="error", message=reason)
            return result
            
    except Exception as e:
        reason = f"Exception: {e}"
        pretty_log("CRITICAL", f"Critical error in worker", file=path, extra=reason)
        conn = psycopg2.connect(**params)
        with conn:
            log_db_event(conn, options, path, "CRITICAL", reason, exc=e)
        result.update(status="error", message=reason)
        return result
    
    finally:
        if conn:
            conn.close()

# file import process

def scan_and_import(folder: str, options: ImportOptions):
    
    # grabs every file so process_file() can demonstrate the skip logic
    file_list = [os.path.join(root, f) for root, _, files in os.walk(folder) for f in files]
    logger.info("Found %d C3D files", len(file_list))

    options_dict = asdict(options)  # convert dataclass to dict

    results = []

    def _append_result(res):
        try:
            results.append(res)
        except Exception as e:
            handle_exception(e, options, file_path=None, level="ERROR")

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
                    _append_result(res)
                except Exception as e:
                    handle_exception(e, options, file_path=file_path, level="CRITICAL")

    # sequential fallback 
    else:
        logger.info("Running sequentially")
        for f in file_list:
            try:
                res = process_file(f, options_dict)
                _append_result(res)
            except Exception as e:
                handle_exception(e, options, file_path=f, level="CRITICAL")
                _append_result({"path": f, "status": "error", "message": str(e)})

    # summarize results
    summary = {"inserted": 0, "duplicate": 0, "invalid": 0, "skipped": 0, "dry_run": 0, "error": 0}
    for r in results:
        if r and "status" in r and r["status"] in summary:
            summary[r["status"]] += 1
        else:
            summary["error"] += 1

    logger.info("Import summary: %s", summary)
    return results