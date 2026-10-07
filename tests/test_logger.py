import io
import logging

import pytest

import logger as log_module
from logger import SafeStreamHandler, logger, pretty_log


@pytest.fixture
def capture():
    """Attaches a handler that writes to a cp1252 stream, like redirected output on Windows."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    handler = SafeStreamHandler(stream)
    handler.setFormatter(logging.Formatter("[%(label)s] %(message)s"))
    logger.addHandler(handler)
    yield lambda: (stream.flush(), raw.getvalue().decode("cp1252"))[1]
    logger.removeHandler(handler)


def test_pretty_log_uses_plain_text_labels(capture):
    pretty_log("SUCCESS", "Imported scan1.dcm (ID: 1)", file="scan1.dcm")
    assert "[SUCCESS] Imported scan1.dcm (ID: 1) [scan1.dcm]" in capture()


def test_no_emoji_in_output(capture):
    for level in ("INFO", "SUCCESS", "ERROR", "DUPLICATE", "SKIP", "DRYRUN", "CRITICAL"):
        pretty_log(level, "message")
    out = capture()
    assert all(ord(ch) < 0x2000 for ch in out)  # emoji live far above this range


def test_greek_filename_does_not_crash_cp1252_console(capture, monkeypatch):
    errors = []
    monkeypatch.setattr(logging.Handler, "handleError", lambda self, record: errors.append(record))

    pretty_log("ERROR", "Import failed for file", file="\u0391\u03c3\u03b8\u03b5\u03bd\u03ae\u03c201.dcm")

    assert errors == []                       # no "--- Logging error ---"
    assert "Import failed for file [" in capture()


def test_plain_logger_calls_get_their_level_as_label(capture):
    logger.warning("No scan date in a.dcm")
    assert "[WARNING] No scan date in a.dcm" in capture()


def test_duplicate_is_logged_as_warning(caplog):
    with caplog.at_level(logging.INFO, logger="dicom_importer"):
        pretty_log("DUPLICATE", "Duplicate file")
    assert caplog.records[-1].levelno == logging.WARNING
    assert caplog.records[-1].label == "DUPLICATE"


def test_critical_log_file_is_utf8():
    assert log_module.file_handler.encoding.lower().replace("-", "") == "utf8"
