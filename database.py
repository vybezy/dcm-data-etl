"""
database helpers: opening connections, import sessions, event logging and settings.
"""
import socket
import psycopg2
import multiprocessing
import threading
import traceback
import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from config import config
from utils import ImportOptions
from typing import Dict, Any


# ------------------------- DB Helpers -------------------------


@contextmanager
def db_connection():
    """
    opens a PostgreSQL connection for one unit of work.
    Commits if the block succeeds, rolls back if it raises, and always closes
    the connection, so no code path can leak one.

    """
    conn = psycopg2.connect(**config())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_import_session() -> int:
    """starts a new import session and returns its id. stores the machine name and ip."""
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except OSError:  # hostname can't be resolved
        ip = "unknown"
    machineid = f"{hostname} ({ip})"
    with db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dicom_logger_session (logses_machineid)
            VALUES (%s) RETURNING logses_id;
        """, (machineid,))
        return cur.fetchone()[0]

def log_db_event(conn, options: ImportOptions, file_path: str, level: str, message: str, exc: Exception = None):
    """
    writes one event to dicom_logger, with where it was called from.
    pass exc to also store the exception type and stack trace. does nothing without a session.
    """
    if not options.session_id:
        return
    frame = inspect.currentframe().f_back
    caller_module = inspect.getmodule(frame)  # can be None
    module = caller_module.__name__ if caller_module else "unknown"
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

def load_settings_from_db() -> Dict[str, Any]:
    """returns the dicom_settings table as a {key: value} dict."""
    with db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT key, value FROM dicom_settings;")
        return {k: v for k, v in cur.fetchall()}
