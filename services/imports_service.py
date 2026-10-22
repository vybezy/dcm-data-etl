"""import jobs: checks the folder, runs the pipeline in a background thread, reports progress."""

import os
import re
from threading import Lock, Thread

import main as cli
import processor
from database import acquire_import_lock, release_import_lock
from db_init import db_init
from logger import logger
from repositories import imports_repository
from services.errors import ConflictError, NotFoundError

# imports started by this api process: {session_id: {"status": ..., "total_files": ...}}
_jobs = {}
job_lock = Lock()

# for imports run from the cli or before the api was restarted
_UNTRACKED = {"status": "unknown", "total_files": None}

# "" or a sub-folder of data/ like "batch/day": no dots and no leading "/", so no ".."
# (api/schemas.py checks requests with this same pattern)
FOLDER_PATTERN = r"^([\w\- ]+(/[\w\- ]+)*)?$"


def is_running() -> bool:
    return any(job["status"] == "running" for job in _jobs.values())


def forget_jobs() -> None:
    _jobs.clear()


def list_folders() -> list[str]:
    # every folder inside data/ that can be imported, as "kits" or "batch/day"
    data_dir = os.path.realpath(cli.default_data_dir())
    folders = []
    for root, dirs, _ in os.walk(data_dir):
        for name in dirs:
            relative = os.path.relpath(os.path.join(root, name), data_dir).replace(os.sep, "/")
            # names the import would refuse (dots, brackets...) are left out of the list
            if re.fullmatch(FOLDER_PATTERN, relative):
                folders.append(relative)

    return sorted(folders)


def list_imports(limit: int) -> list[dict]:
    sessions = imports_repository.list_sessions(limit)
    return [{**session, **_jobs.get(session["id"], _UNTRACKED)} for session in sessions]


def start_import(folder: str, dry_run: bool) -> dict:
    base_folder = _resolve_folder(folder)

    # check + mark as running in one step, so two requests can't both start
    with job_lock:
        if is_running():
            raise ConflictError("an import is already running")

        lock = acquire_import_lock()
        if lock is None:
            raise ConflictError("an import or a reset is already running")

        try:
            db_init(reset_tables=False, logger=logger)
            options = cli.build_options(base_folder, dry_run=dry_run)
            files = processor.list_files(base_folder)

        except Exception:
            release_import_lock(lock)
            raise

        _jobs[options.session_id] = {"status": "running", "total_files": len(files)}
        job = {"id": options.session_id, **_jobs[options.session_id]}

    Thread(target=_run, args=(base_folder, options, files, lock), daemon=True).start()
    return job


def _run(base_folder: str, options, files: list, lock) -> None:
    # runs in the background thread. no request is waiting, so errors only get logged
    try:
        processor.scan_and_import(base_folder, options, file_list=files)
        _jobs[options.session_id]["status"] = "finished"

    except Exception:
        logger.exception("background import %s failed", options.session_id)
        _jobs[options.session_id]["status"] = "failed"

    finally:
        release_import_lock(lock)


def _resolve_folder(folder: str) -> str:
    data_dir = os.path.realpath(cli.default_data_dir())
    target = os.path.realpath(os.path.join(data_dir, folder))

    # second check after the schema pattern: the folder must stay inside data/
    if os.path.commonpath([data_dir, target]) != data_dir or not os.path.isdir(target):
        raise NotFoundError(f"folder '{folder}' not found in data/")

    return target
