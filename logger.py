"""
logging setup: console output, a critical log file
and pretty_log() for pipeline events.
"""
import sys
import logging


class _DefaultLabel(logging.Filter):
    """
    gives every record a "label" pretty_log sets SUCCESS, DUPLICATE, etc..
    other records use the level name.
    """
    def filter(self, record):
        if not hasattr(record, "label"):
            record.label = record.levelname

        return True


class SafeStreamHandler(logging.StreamHandler):
    """
    console handler that replaces characters
    the terminal can't print instead of crashing.
    """
    def emit(self, record):
        try:
            msg = self.format(record)
            encoding = getattr(self.stream, "encoding", None) or "utf-8"
            msg = msg.encode(encoding, errors="replace").decode(encoding)
            self.stream.write(msg + self.terminator)
            self.flush()

        except RecursionError:
            raise

        except Exception:
            self.handleError(record)


logger = logging.getLogger("dicom_importer")
logger.setLevel(logging.DEBUG)
logger.addFilter(_DefaultLabel())

# critical events also go to a UTF-8 file, so any filename is written safely
file_handler = logging.FileHandler(
    "dicom_importer_critical.log", encoding="utf-8"
)
file_handler.setLevel(logging.CRITICAL)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(label)s] %(message)s")
)
logger.addHandler(file_handler)

console_handler = SafeStreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("[%(label)s] %(message)s"))
logger.addHandler(console_handler)

# pipeline outcome
_LEVELS = {
    "SUCCESS": logging.INFO,
    "SKIP": logging.INFO,
    "DRYRUN": logging.INFO,
    "INFO": logging.INFO,
    "DUPLICATE": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.ERROR,
}


def pretty_log(level, msg, file=None, extra=None):
    """
    logs one pipeline event as plain text, e.g.
        [SUCCESS] Successfully imported scan1.dcm (ID: 1) [scan1.dcm]
    """
    file_part = f" [{file}]" if file else ""
    extra_part = f" {extra}" if extra else ""
    logger.log(
        _LEVELS.get(level, logging.INFO),
        f"{msg}{file_part}{extra_part}",
        extra={"label": level},
        )
