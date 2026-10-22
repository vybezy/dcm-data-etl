"""reset rules: never reset while an import is running."""

from database import acquire_import_lock, release_import_lock
from repositories import admin_repository
from services import imports_service
from services.errors import ConflictError


def reset_database() -> None:
    # same lock as start_import, so an import can't start in the middle of a reset
    with imports_service.job_lock:
        if imports_service.is_running():
            raise ConflictError("cannot reset while an import is running")

        lock = acquire_import_lock()
        if lock is None:
            raise ConflictError("cannot reset while an import is running")

        try:
            admin_repository.reset_tables()
            imports_service.forget_jobs()

        finally:
            release_import_lock(lock)
