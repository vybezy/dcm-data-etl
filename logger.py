import sys
import logging


# ------------------------- Logging setup -------------------------


# sets up logger
logger = logging.getLogger("dicom_importer")
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler("dicom_importer_critical.log")
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