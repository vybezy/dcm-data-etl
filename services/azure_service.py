import os

import main as cli
import utils
from database import release_import_lock
from logger import logger
from services import imports_service
from services.errors import UnavailableError

AZURE_FOLDER = "azure"


def is_configured() -> bool:
    return utils.azure_container_url() != ""


def sync() -> dict:
    container_url = utils.azure_container_url()
    if not container_url:
        raise UnavailableError("Azure Blob Storage is not configured")

    target = os.path.join(os.path.realpath(cli.default_data_dir()), AZURE_FOLDER)

    with imports_service.job_lock:
        lock = imports_service.take_import_lock("cannot sync while an import or a reset is running")

    try:
        downloaded = utils.download_new_blobs(container_url, target)

    except Exception:
        logger.exception("Azure sync failed")
        raise UnavailableError("couldn't download from Azure Blob Storage, see the server log")

    finally:
        release_import_lock(lock)

    return {"folder": AZURE_FOLDER, "downloaded": downloaded}
