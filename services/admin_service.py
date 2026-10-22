"""reset rules: never reset while an import is running."""

from database import release_import_lock
from repositories import admin_repository
from services import imports_service


def reset_database() -> None:
    # same lock as start_import, so an import can't start in the middle of a reset
    with imports_service.job_lock:
        lock = imports_service.take_import_lock("cannot reset while an import is running")
        try:
            admin_repository.reset_tables()
            imports_service.forget_jobs()

        finally:
            release_import_lock(lock)
