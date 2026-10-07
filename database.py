import socket
import psycopg2
import multiprocessing
import threading
import traceback
import inspect
from datetime import datetime, timezone
from config import config
from utils import ImportOptions
from typing import Dict, Any


# ------------------------- DB Helpers -------------------------


# saves user data in dicom_logger_session
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
            INSERT INTO dicom_logger_session (logses_machineid)
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
            INSERT INTO dicom_logger (
                log_logses_id, log_timestamp, log_level, log_dicomfile,
                log_message, log_module, log_function, log_line_number,
                log_process_name, log_thread_name, log_exception_type, log_stack_trace
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);
        """, (
            options.session_id, datetime.now(timezone.utc), level, file_path[:100],
            message, module, funcname, lineno, process_name, thread_name, exc_type, stack
        ))
        conn.commit()

# loads settings from db
def load_settings_from_db() -> Dict[str, Any]:
    params = config()
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    conn.commit()
    cur.execute("SELECT key, value FROM dicom_settings;")
    rows = cur.fetchall()
    settings = {k: v for k, v in rows}
    cur.close()
    return settings