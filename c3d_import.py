"""
C3D Import Module (Refactored for GUI Integration) - DR

Υλοποιημένα:
- Όλες οι σταθερές (constants) διαβάζονται από τον πίνακα c3d_settings_dr.
- Χρησιμοποιείται SHA256 για hashing.
- Logging σε database table (c3d_logging_dr) και σε αρχείο (μόνο critical errors).
- Υποστήριξη import session (c3d_logger_session_dr).
- Detailed error context (module, function, γραμμή, process, thread).
- File traversal: extension, filename length, invalid chars, safe path.
- Έλεγχος μεγέθους αρχείου (>=300KB και <=99MB).
- Multiprocessing workers (4-8) ή σειριακή λειτουργία.
- Κάθε import_c3d τρέχει ως αυτόνομο process με δικό του DB connection.
- Πλήρης έλεγχος για invalid/unusual χαρακτήρες στο filename.
- Πλήρης αντικατάσταση path με safe path.
- Πλήρης αναφορά επιτυχίας/αποτυχίας ανά αρχείο (με αναλυτικά στατιστικά).
(19/09/2025)
- init_db_tables : μεσα στη main δεχεται boolean value για να δει αν θα κανει drop & create τα settings & logging tables
- handle_exception : centralized error handling
(10/10/2025)
- Αντικατασταση DB Config με connect function για συνδεση στη βαση δεδομενων , με χρηση .env για την ασφαλη αποθηκευση password και config.py 
- Drops Tables και ξαναδημιουργει για να τρεξει σωστα το προγραμμα
- η load settings from db αποθηκευει τα settings σε dictionary
- Table creation στο main() με boolean parameter
(13/10/2025)
- init_db_tables εγινε διαφορετικο module db_init
- run_c3d_import - η main() σε module
- wildcards/single file/folder

Υπολείπονται/Μερικώς υλοποιημένα:
-

Add New Implementations/Νέες Υλοποιήσεις:
(1/4/2026)
- Line Profiler
- Sql comments on all tables
- ProcessPoolExecutor
- Replaced executemany -> executevalue, less try except more exception handler
- Points & Analog Import

"""

import os
import re
import io
import sys
import math
import json
import ezc3d
import socket
import pstats
import logging
import inspect
import hashlib
import cProfile
import threading
import traceback
import numpy as np
import psycopg2.extras
import psycopg2.errors
import multiprocessing
from functools import wraps
from THKE_config import config
from db_init_MM import db_init
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# ------------------------- Logging setup -------------------------


# ruthmizei to logging kommati tou programmatos

logger = logging.getLogger("c3d_importer")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler("c3d_importer_critical_MM.log")
file_handler.setLevel(logging.CRITICAL)
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


# ------------------------- Pretty Log -------------------------


def pretty_log(level, msg, file=None, extra=None):
    icons = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "ERROR": "❌",
        "DUPLICATE": "⚠️",
        "SKIP": "⏭️",
        "DRYRUN": "📝",
        "CRITICAL": "🔥",
    }
    icon = icons.get(level, "")
    file_part = f" [{file}]" if file else ""
    extra_part = f" {extra}" if extra else ""
    pretty_msg = f"{icon} {msg}{file_part}{extra_part}"
    # Console
    if level in ("ERROR", "CRITICAL"):
        logger.error(pretty_msg)
    elif level == "SUCCESS":
        logger.info(pretty_msg)
    elif level == "DUPLICATE":
        logger.warning(pretty_msg)
    else:
        logger.info(pretty_msg)


# ------------------------- Profiler -------------------------


def Profiler(func):
    """
    A custom line-by-line profiler that logs execution time for every single line.
    Automatically appends the receipt to a text file.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            from line_profiler import LineProfiler
        except ImportError:
            print("⚠️ line_profiler is missing! Please run: pip install line_profiler")
            return func(*args, **kwargs)

        lp = LineProfiler()
        lp.add_function(func)
        
        lp.enable()
        result = func(*args, **kwargs)
        lp.disable()
        
        # get the info as a text
        s = io.StringIO()
        lp.print_stats(stream=s)
        
        # save to log file
        log_file = "profiler_logs_MM.txt"
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"📅 DATE:     {current_time}\n")
            f.write(f"⚙️ FUNCTION: {func.__name__}\n")
            f.write(f"{'='*80}\n")
            f.write(s.getvalue())
            f.write("\n")
            
        return result
    return wrapper


# ------------------------- Dataclasses -------------------------


@dataclass # creates automatically constructor , saves time in writing the class
class ImportOptions:
    base_folder: str
    min_size: int
    max_size: int
    subject_min_length: int
    max_file_age_months: int
    workers: int
    dry_run: bool = False
    debug: bool = False
    log_to_db: bool = True
    safe_c3d_folder: Optional[str] = None
    session_id: Optional[int] = None

class ImportErrorWithContext(Exception):
    pass

# Exception Handler
def handle_exception(e: Exception, options: ImportOptions = None, file_path: str = None, level: str = "CRITICAL"):
    try:
        # traceback in string
        tb_str = traceback.format_exc()

        # exception type
        exc_type = type(e).__name__

        # Tries to get last frame from traceback where exception occured
        tb = sys.exc_info()[2]
        if tb:
            last_frame = traceback.extract_tb(tb)[-1]
            filename = last_frame.filename
            lineno = last_frame.lineno
            funcname = last_frame.name
        else:
            # fallback to caller frame if theres no traceback
            caller = inspect.currentframe().f_back
            filename = caller.f_code.co_filename
            lineno = caller.f_lineno
            funcname = caller.f_code.co_name

        process_name = multiprocessing.current_process().name
        thread_name = threading.current_thread().name

        # Message to where its stored
        message = f"{exc_type} in {funcname} at {filename}:{lineno} -> {e}\n{tb_str}"

        # Console + file logger με stacktrace
        pretty_log(level, f"{exc_type}: {e}", file=file_path, extra=f"{filename}:{lineno}")
        logger.exception(message)  # writes full traceback to αρχείο/console handlers

        # Database logging (if there's session_id)
        session_id = getattr(options, "session_id", None) if options is not None else None
        if session_id:
            try:
                params = config()
                connection = psycopg2.connect(**params)
                if connection:
                    log_db_event(connection, options, file_path or "", level, message, exc=e)
            except Exception as db_e:
                # Doesn't allow handler to break - fallback to local logger
                logger.error("Failed to log exception to DB: %s", db_e)

    except Exception as handler_err:
        # if something breaks in handler, write in local logger
        logger.critical("Exception inside handle_exception(): %s", handler_err)
        logger.critical("Original exception was: %s", e)


# ------------------------- DB Helpers -------------------------


# Apothikeuei sto c3d_logger_session_MM table ta stoixeia tou user pou sundethike sto db
def create_import_session() -> int:
    params = config()
    conn = psycopg2.connect(**params)
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except:
        ip = "unknown"
    machineid = f"{hostname} ({ip})"
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO c3d_logger_session_MM (logses_machineid)
            VALUES (%s) RETURNING logses_id;
        """, (machineid,))
        session_id = cur.fetchone()[0]
        conn.commit()
        return session_id

def log_db_event(conn, options: ImportOptions, file_path: str, level: str, message: str, exc: Exception = None):
    if not options.session_id:
        return
    frame = inspect.currentframe().f_back
    module = inspect.getmodule(frame).__name__
    funcname = frame.f_code.co_name
    lineno = frame.f_lineno
    process_name = multiprocessing.current_process().name
    thread_name = threading.current_thread().name
    exc_type = type(exc).__name__ if exc else None
    stack = traceback.format_exc() if exc else None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO c3d_logger_MM (
                log_logses_id, log_timestamp, log_level, log_c3dfile,
                log_message, log_module, log_function, log_line_number,
                log_process_name, log_thread_name, log_exception_type, log_stack_trace
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);
        """, (
            options.session_id, datetime.now(timezone.utc), level, file_path[:100],
            message, module, funcname, lineno, process_name, thread_name, exc_type, stack
        ))
        conn.commit()

# katevazei ta settings apo to db
def load_settings_from_db() -> Dict[str, Any]:
    params = config()
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    conn.commit()
    cur.execute("SELECT key, value FROM c3d_settings_MM;")
    rows = cur.fetchall()
    settings = {k: v for k, v in rows}
    cur.close()
    return settings


# ------------------------- File Processing -------------------------


# checkarei an to file name einai valid
def is_valid_filename(filename: str) -> bool:
    # Max length 255, only allow alphanum, dash, underscore, dot, space
    if len(filename) > 255:
        return False
    # Disallow unusual characters (allow Greek, Latin, numbers, dash, underscore, dot, space)
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

def make_json_safe(data):
    """
    Recursively cleans data so it is safe for PostgreSQL JSONB storage.
    """
    if isinstance(data, np.ndarray):
        data = data.tolist()
        
    if isinstance(data, (list, tuple)): # if its list/tuple
        return [make_json_safe(v) for v in data] # recursively checks all lists within lists if they exist 
        
    return data

def compute_sha256(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest()

# kuria epeksergasia tou arxeiou

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
        # Path traversal and filename checks
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

        # Subject name extraction (robust, with fallback to filename)
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

         # Duplicate check (SHA256)
        with conn.cursor() as cur:
            cur.execute("SELECT file_id FROM c3d_files_MM WHERE file_sha256_hash = %s", (sha,))
            row = cur.fetchone()
            if row:
                reason = f"Duplicate file (SHA256={sha})"
                pretty_log("DUPLICATE", f"Duplicate file", file=filename, extra=reason)
                log_db_event(conn, options, path, "DUPLICATE", reason)
                result.update(status="duplicate", message="Duplicate file", db_file_id=row[0])
                return result

        # Insert file metadata (if not dry run)
        if options.dry_run:
            pretty_log("DRYRUN", f"Dry run - not inserted", file=filename)
            log_db_event(conn, options, path, "DRYRUN", "Dry run - not inserted")
            result.update(status="dry_run", message="Dry run - not inserted")
            return result

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO c3d_files_MM (file_name, file_path, file_date, file_size, file_sha256_hash, file_subject_name)
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

# ------------------------- Metadata Extraction -------------------------

# extraction functions

def extract_and_insert_headers(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the basic header section of the C3D file.
    Upgraded to use execute_values for high-speed bulk inserts.
    """
    headers_to_insert = []
    
    header_sections = { 
        'POINT': c3d_data['header'].get('points', {}),
        'ANALOG': c3d_data['header'].get('analogs', {})
    }

    for section_key, section_data in header_sections.items(): 
        for key, value in section_data.items():
            header_name = f"{section_key}_{key.upper()}"
            headers_to_insert.append((file_id, header_name, section_key, str(value)))

    if headers_to_insert:
        # No try/except block here! If it fails, it bubbles up to the parent function 
        # (process_c3d_metadata) which handles the logging and rollback centrally.
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_header_MM (header_file_id, header_name, header_key, header_value)
                VALUES %s
                ON CONFLICT (header_file_id, header_name) DO NOTHING;
                """,
                headers_to_insert,
                template="(%s, %s, %s, %s)",
                page_size=1000
            )
            conn.commit()

@Profiler
def extract_and_insert_parameters(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the deep metadata parameters using strict anti-corruption checks.
    Upgraded to use execute_values for high-speed bulk inserts.
    """
    params_to_insert = []
    parameters_section = c3d_data.get('parameters', {})
    
    for group_name, group_data in parameters_section.items():
        if not isinstance(group_data, dict):
            continue

        clean_group = group_name.replace("\x00", "").strip()

        for param_key, param_info in group_data.items():
            if not isinstance(param_info, dict) or "value" not in param_info:
                continue
            
            clean_key = param_key.replace("\x00", "").strip()
            if not clean_key:
                continue
                
            value = param_info["value"]
            description = param_info.get("description", "").replace("\x00", "").strip()
            
            dimensions = param_info.get("dimension", [])
            if not dimensions and isinstance(value, np.ndarray):
                dimensions = list(value.shape)
                
            if not isinstance(dimensions, (list, tuple)):
                dimensions = []

            if len(dimensions) > 5:
                logger.warning(f"Excessive dimensions in {clean_group}.{clean_key}. Skipping.")
                continue
            
            try:
                clean_value = make_json_safe(value)
                json_data = json.dumps(clean_value)
            except Exception as e:
                logger.warning(f"Cannot convert value to JSON in {clean_group}.{clean_key}: {e}")
                continue
            
            is_locked = bool(param_info.get('is_locked', False))

            params_to_insert.append((
                file_id, clean_group.upper(), clean_key.upper(),
                description, str(dimensions), is_locked, json_data
            ))

    if params_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_parameters_MM (
                    parameters_file_id,parameters_group, 
                    parameters_key, 
                    parameters_description, parameters_dimensions, parameters_lock, parameters_value_json
                )
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                params_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=1000
            )
            conn.commit()

@Profiler
def extract_and_insert_analog(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the massive time-series arrays for Analog data (e.g., Force Plates, EMG).
    Uses execute_values for high-speed bulk inserts.
    """
    analog_to_insert = []
    
    # Safely get the data and parameters
    analog_data = c3d_data.get('data', {}).get('analogs')
    analog_params = c3d_data.get('parameters', {}).get('ANALOG', {})
    
    # If there is no analog data (or it's empty), just skip
    if analog_data is None or analog_data.size == 0 or len(analog_data.shape) != 3:
        return

    # ezc3d analog shape is typically (1, num_channels, num_frames)
    num_channels = analog_data.shape[1]
    
    # Extract the metadata lists (with safe fallbacks)
    labels = analog_params.get('LABELS', {}).get('value', [])
    units = analog_params.get('UNITS', {}).get('value', [])
    gains = analog_params.get('GEN_SCALE', {}).get('value', []) # Sometimes named SCALE
    offsets = analog_params.get('OFFSET', {}).get('value', [])
    descs = analog_params.get('DESCRIPTIONS', {}).get('value', [])

    for i in range(num_channels):
        # Safely extract matching metadata by index, with fallbacks if the C3D is poorly formatted
        label = labels[i] if i < len(labels) and labels[i] else f"Analog_{i}"
        unit = str(units[i]) if i < len(units) and units[i] else ""
        gain = str(gains[i]) if i < len(gains) and gains[i] else ""
        
        # Offsets are usually integers
        offset = None
        if i < len(offsets) and offsets[i] is not None:
            try:
                offset = int(float(offsets[i]))
            except ValueError:
                pass
                
        desc = str(descs[i]) if i < len(descs) and descs[i] else ""
        
        # Extract the entire time-series array for this channel and convert to a Postgres-friendly list
        frames = analog_data[0, i, :].tolist()

        analog_to_insert.append((
            file_id, label, unit, gain, frames, offset, desc
        ))

    if analog_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_analog_MM (
                    analog_file_id, analog_label, analog_unit, 
                    analog_gain, analog_frames, analog_offset, analog_desc
                )
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                analog_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=500 # Slightly smaller page size since these arrays are huge!
            )
            conn.commit()

@Profiler
def extract_and_insert_points(conn, file_id: int, c3d_data: ezc3d.c3d):
    """
    Extracts the 3D trajectory tracking points.
    Uses execute_values for high-speed bulk inserts.
    """
    points_to_insert = []
    
    point_data = c3d_data.get('data', {}).get('points')
    point_params = c3d_data.get('parameters', {}).get('POINT', {})
    
    # If there is no point data, skip
    if point_data is None or point_data.size == 0 or len(point_data.shape) != 3:
        return

    # ezc3d point shape is typically (4, num_points, num_frames)
    # 0=X, 1=Y, 2=Z, 3=Residuals
    num_points = point_data.shape[1]
    num_frames = point_data.shape[2]
    
    labels = point_params.get('LABELS', {}).get('value', [])

    for i in range(num_points):
        label = labels[i] if i < len(labels) and labels[i] else f"Point_{i}"
        
        # Extract the X, Y, Z, and Residual arrays 
        x_frames = point_data[0, i, :].tolist()
        y_frames = point_data[1, i, :].tolist()
        z_frames = point_data[2, i, :].tolist()
        r_frames = point_data[3, i, :].tolist()

        points_to_insert.append((
            file_id, num_frames, label, 
            x_frames, y_frames, z_frames, r_frames
        ))

    if points_to_insert:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO c3d_points_MM (
                    points_file_id, points_frame_count, points_label, 
                    points_frames_x, points_frames_y, points_frames_z, points_frames_r
                )
                VALUES %s
                ON CONFLICT DO NOTHING;
                """,
                points_to_insert,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=500
            )
            conn.commit()

# main thing

def process_c3d_metadata(file_id: int, file_path: str):
    """
    Main entry point. Extracts ONLY headers and parameters sequentially.
    """
    try:     
        c3d_data = ezc3d.c3d(file_path)
        params = config()
        
        with psycopg2.connect(**params) as conn:
            extract_and_insert_headers(conn, file_id, c3d_data)
            
            # hand the file_name to the parameter function
            extract_and_insert_parameters(conn, file_id, c3d_data)

            # 3. Massive Scientific Arrays
            extract_and_insert_analog(conn, file_id, c3d_data)
            extract_and_insert_points(conn, file_id, c3d_data)
            
        logger.info(f"Successfully processed headers and parameters for file_id: {file_id}")
        return True
        
    except Exception as e:
        handle_exception(e, options=None, file_path=file_path, level="ERROR")
        return False
    
# ------------------------- MAIN -------------------------
# diaxeirizetai thn import diadikasia twn arxeiwn

def scan_and_import(folder: str, options: ImportOptions):
    file_list = [os.path.join(root, f)
                 for root, _, files in os.walk(folder)
                 for f in files if f.lower().endswith(".c3d")]
    logger.info("Found %d C3D files", len(file_list))

    options_dict = asdict(options)  # Convert dataclass to dict for pickling

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