import io
import sys
import os
import inspect
import traceback
from logger import pretty_log, logger
from functools import wraps
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from azure.storage.blob import BlobServiceClient


# ------------------------- Profiler -------------------------


PROFILE_ENV_VAR = "DICOM_PROFILE"


def profiling_enabled() -> bool:
    """Profiling is opt-in: set DICOM_PROFILE=1 (or true/yes) to turn it on."""
    return os.getenv(PROFILE_ENV_VAR, "").strip().lower() in ("1", "true", "yes")


def Profiler(func):
    """
    Opt-in line-by-line profiler (requires line_profiler).

    Disabled by default: the decorator then returns the original function
    unchanged, so production imports pay zero overhead. When DICOM_PROFILE=1,
    each call appends its line timings to profiler_logs_<pid>.txt - one file
    per process, so parallel workers never interleave their output.
    """
    if not profiling_enabled():
        return func

    try:
        from line_profiler import LineProfiler
    except ImportError:
        logger.warning(
            "%s is set but line_profiler is not installed (pip install line_profiler); "
            "%s will run without profiling.", PROFILE_ENV_VAR, func.__name__
        )
        return func

    @wraps(func)
    def wrapper(*args, **kwargs):
        lp = LineProfiler()
        lp.add_function(func)

        lp.enable()
        try:
            return func(*args, **kwargs)
        finally:
            # runs even if func raises, so failed calls are profiled too
            lp.disable()
            s = io.StringIO()
            lp.print_stats(stream=s)

            log_file = f"profiler_logs_{os.getpid()}.txt"
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"DATE:     {current_time}\n")
                f.write(f"FUNCTION: {func.__name__}\n")
                f.write(f"{'=' * 80}\n")
                f.write(s.getvalue())
                f.write("\n")

    return wrapper


# ------------------------- Error Handling -------------------------


@dataclass # creates automatically constructor , saves time in writing the class
class ImportOptions:
    base_folder: str
    min_size: int
    max_size: int
    max_file_age_months: int
    workers: int
    dry_run: bool = False
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

        # Message to where its stored
        message = f"{exc_type} in {funcname} at {filename}:{lineno} -> {e}\n{tb_str}"

        # Console + critical log file, with the stack trace
        pretty_log(level, f"{exc_type}: {e}", file=file_path, extra=f"{filename}:{lineno}")
        logger.exception(message)  # writes the full traceback to the log handlers

        # Database logging (if there's session_id)
        session_id = getattr(options, "session_id", None) if options is not None else None
        if session_id:
            try:
                from database import db_connection, log_db_event  # local import prevents circular dependency
                with db_connection() as connection:
                    log_db_event(connection, options, file_path or "", level, message, exc=e)
            except Exception as db_e:
                # Doesn't allow handler to break - fallback to local logger
                logger.error("Failed to log exception to DB: %s", db_e)

    except Exception as handler_err:
        # if something breaks in handler, write in local logger
        logger.critical("Exception inside handle_exception(): %s", handler_err)
        logger.critical("Original exception was: %s", e)


# ------------------------------ Azure ------------------------------


def download_dicom_from_azure(download_dir: str = "/data") -> str:
    """
    Connects to Azure Blob Storage using a SAS connection string and downloads
    all .dcm files into the local container directory prior to processing.
    """
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        logger.info("No AZURE_STORAGE_CONNECTION_STRING found; using existing local files.")
        return download_dir

    logger.info("Connecting to Azure Blob Storage...")
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client("raw-dicom-files")

        os.makedirs(download_dir, exist_ok=True)
        downloaded = 0

        for blob in container_client.list_blobs():
            dest_path = os.path.join(download_dir, os.path.basename(blob.name))
            if not os.path.exists(dest_path):
                logger.info("Downloading %s from Azure Blob Storage...", blob.name)
                with open(dest_path, "wb") as f:
                    f.write(container_client.download_blob(blob.name).readall())
                downloaded += 1

        logger.info("Azure download complete: %d new file(s) retrieved.", downloaded)
    except Exception as e:
        logger.warning("Azure download failed: %s. Falling back to existing directory contents.", e)

    return download_dir
