import os
import hashlib
from dataclasses import asdict
from datetime import date
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from pydicom.dataset import Dataset

from processor import (
    is_valid_filename,
    sanitize_and_validate_path,
    compute_sha256,
    process_file,
    scan_and_import,
    subtract_months,
    get_scan_date,
    check_scan_age,
    read_dicom_header,
)
from utils import ImportOptions, ImportErrorWithContext


# ------------------------- Helpers -------------------------


def make_options(base_folder, **overrides):
    defaults = dict(
        base_folder=os.path.realpath(str(base_folder)),
        min_size=1,
        max_size=10 * 1024 * 1024,
        max_file_age_months=24,
        workers=0,
        session_id=None,
    )
    defaults.update(overrides)
    return ImportOptions(**defaults)


def make_mock_conn(fetchone_value=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_value  # None = no duplicate in DB
    conn.cursor.return_value.__enter__.return_value = cur
    return conn


def make_header(**tags):
    """A DICOM header with only the given tags, e.g. make_header(StudyDate="20240115")."""
    ds = Dataset()
    for name, value in tags.items():
        setattr(ds, name, value)
    return ds


@pytest.fixture
def header():
    """The header process_file() will 'read'. Tests can add tags to it before running."""
    return make_header(StudyDate=date.today().strftime("%Y%m%d"))


@pytest.fixture
def mock_db(header):
    """Replaces config, DB connection, DICOM parsing and DB/console logging for process_file tests."""
    conn = make_mock_conn()
    with patch("processor.config", return_value={}), \
         patch("processor.psycopg2.connect", return_value=conn), \
         patch("processor.read_dicom_header", return_value=header), \
         patch("processor.log_db_event"), \
         patch("processor.pretty_log"):
        yield conn


def run_process_file(path, options):
    return process_file(str(path), asdict(options))


# ------------------------- is_valid_filename -------------------------


@pytest.mark.parametrize("name", [
    "Trial01.dcm",
    "subject_test-01.dcm",
    "my file.dcm",
    "Ασθενής01.dcm",  # any alphabet is allowed: Greek,
    "Пациент01.dcm",  # Cyrillic,
    "患者01.dcm",      # Chinese
])
def test_valid_filenames(name):
    assert is_valid_filename(name) is True


@pytest.mark.parametrize("name", [
    "subject@test!#$%.dcm",
    "../etc/passwd",
    "folder/file.dcm",
    "file;rm -rf.dcm",
    "",
    "scan.dcm\n",         # trailing newline ('$' would have accepted it)
    "back\\slash.dcm",
    "C:file.dcm",
])
def test_invalid_filenames(name):
    assert is_valid_filename(name) is False


def test_filename_length_limit():
    assert is_valid_filename("a" * 251 + ".dcm") is True   # exactly 255
    assert is_valid_filename("a" * 252 + ".dcm") is False  # 256


# ------------------------- sanitize_and_validate_path -------------------------


def test_sanitize_success(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    f = base / "test.dcm"
    f.write_text("dummy")

    assert sanitize_and_validate_path(str(f), str(base)) == os.path.realpath(str(f))


def test_sanitize_traversal(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    outside = tmp_path / "outside.dcm"
    outside.write_text("x")

    with pytest.raises(ImportErrorWithContext, match="Path traversal or escape detected"):
        sanitize_and_validate_path(str(outside), str(base))


def test_sanitize_dotdot_traversal(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    (tmp_path / "secret.dcm").write_text("x")
    sneaky = str(base / ".." / "secret.dcm")

    with pytest.raises(ImportErrorWithContext):
        sanitize_and_validate_path(sneaky, str(base))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need elevated rights on Windows")
def test_sanitize_symlink_escape(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    target = tmp_path / "secret.dcm"
    target.write_text("x")
    link = base / "link.dcm"
    link.symlink_to(target)

    with pytest.raises(ImportErrorWithContext):
        sanitize_and_validate_path(str(link), str(base))


def test_sanitize_nonexistent_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        sanitize_and_validate_path(str(tmp_path / "nope.dcm"), str(tmp_path))


# ------------------------- compute_sha256 -------------------------


def test_compute_sha256(tmp_path):
    f = tmp_path / "a.dcm"
    f.write_bytes(b"hello dicom")
    assert compute_sha256(str(f)) == hashlib.sha256(b"hello dicom").hexdigest()


def test_compute_sha256_differs_for_different_content(tmp_path):
    a, b = tmp_path / "a.dcm", tmp_path / "b.dcm"
    a.write_bytes(b"one")
    b.write_bytes(b"two")
    assert compute_sha256(str(a)) != compute_sha256(str(b))


# ------------------------- process_file: validation paths -------------------------


def test_process_file_skips_non_dcm(tmp_path, mock_db):
    f = tmp_path / "notes.txt"
    f.write_bytes(b"data")

    result = run_process_file(f, make_options(tmp_path))
    assert result["status"] == "skipped"


def test_process_file_rejects_path_outside_base(tmp_path, mock_db):
    base = tmp_path / "data"
    base.mkdir()
    outside = tmp_path / "outside.dcm"
    outside.write_bytes(b"data")

    result = run_process_file(outside, make_options(base))
    assert result["status"] == "invalid"
    assert "Path validation failed" in result["message"]


def test_process_file_rejects_bad_filename(tmp_path, mock_db):
    f = tmp_path / "bad@name.dcm"
    f.write_bytes(b"data")

    result = run_process_file(f, make_options(tmp_path))
    assert result["status"] == "invalid"
    assert "Invalid filename" in result["message"]


def test_process_file_rejects_too_small(tmp_path, mock_db):
    f = tmp_path / "small.dcm"
    f.write_bytes(b"tiny")

    result = run_process_file(f, make_options(tmp_path, min_size=100))
    assert result["status"] == "invalid"
    assert "outside allowed range" in result["message"]


def test_process_file_rejects_too_large(tmp_path, mock_db):
    f = tmp_path / "big.dcm"
    f.write_bytes(b"x" * 500)

    result = run_process_file(f, make_options(tmp_path, max_size=100))
    assert result["status"] == "invalid"


def test_process_file_rejects_old_scan(tmp_path, header, mock_db):
    header.StudyDate = "20000101"
    f = tmp_path / "old.dcm"
    f.write_bytes(b"data")

    result = run_process_file(f, make_options(tmp_path, max_file_age_months=24))
    assert result["status"] == "invalid"
    assert "Scan too old: StudyDate=2000-01-01" in result["message"]


def test_process_file_rejects_future_scan(tmp_path, header, mock_db):
    header.StudyDate = "29990101"
    f = tmp_path / "future.dcm"
    f.write_bytes(b"data")

    result = run_process_file(f, make_options(tmp_path))
    assert result["status"] == "invalid"
    assert "future" in result["message"]


def test_process_file_ignores_file_timestamp_on_disk(tmp_path, header, mock_db):
    """A recent scan is accepted even if the file itself is old on disk (and vice versa)."""
    f = tmp_path / "copied.dcm"
    f.write_bytes(b"data")
    old = 315532800  # 1980-01-01 as a Unix timestamp
    os.utime(f, (old, old))

    with patch("processor.process_dicom_file", return_value=1):
        result = run_process_file(f, make_options(tmp_path, max_file_age_months=24))
    assert result["status"] == "inserted"


def test_process_file_unreadable_dicom_is_error(tmp_path, mock_db):
    f = tmp_path / "corrupt.dcm"
    f.write_bytes(b"data")

    with patch("processor.read_dicom_header", side_effect=ValueError("not a DICOM file")):
        result = run_process_file(f, make_options(tmp_path))
    assert result["status"] == "error"
    assert "Unreadable DICOM file" in result["message"]


# ------------------------- scan date helpers -------------------------


@pytest.mark.parametrize("day, months, expected", [
    (date(2026, 10, 7), 24, date(2024, 10, 7)),
    (date(2026, 3, 31), 1, date(2026, 2, 28)),   # clamps to end of February
    (date(2024, 3, 31), 1, date(2024, 2, 29)),   # leap year
    (date(2026, 1, 15), 1, date(2025, 12, 15)),  # crosses a year boundary
    (date(2026, 10, 7), 0, date(2026, 10, 7)),
])
def test_subtract_months(day, months, expected):
    assert subtract_months(day, months) == expected


def test_get_scan_date_prefers_study_date_then_falls_back():
    assert get_scan_date(make_header(StudyDate="20240115", SeriesDate="20230101")) == (date(2024, 1, 15), "StudyDate")
    assert get_scan_date(make_header(StudyDate="", SeriesDate="20230101")) == (date(2023, 1, 1), "SeriesDate")
    assert get_scan_date(make_header(StudyDate="20241399", ContentDate="20220202")) == (date(2022, 2, 2), "ContentDate")
    assert get_scan_date(make_header()) == (None, None)


def test_check_scan_age_boundaries():
    today = date(2026, 10, 7)
    assert check_scan_age(make_header(StudyDate="20241007"), 24, today) is None   # exactly at the limit
    assert "too old" in check_scan_age(make_header(StudyDate="20241006"), 24, today)
    assert check_scan_age(make_header(StudyDate="20261008"), 24, today) is None   # 1 day of slack
    assert "future" in check_scan_age(make_header(StudyDate="20261009"), 24, today)


def test_check_scan_age_accepts_files_without_a_date():
    assert check_scan_age(make_header(), 24, date(2026, 10, 7)) is None


# ------------------------- process_file: DB paths -------------------------


def test_process_file_detects_duplicate_by_hash(tmp_path):
    f = tmp_path / "dup.dcm"
    f.write_bytes(b"data")
    conn = make_mock_conn(fetchone_value=(42,))  # hash already in DB

    with patch("processor.config", return_value={}), \
         patch("processor.psycopg2.connect", return_value=conn), \
         patch("processor.log_db_event"), patch("processor.pretty_log"):
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "duplicate"
    assert result["db_file_id"] == 42


def test_process_file_dry_run_does_not_insert(tmp_path, mock_db):
    f = tmp_path / "a.dcm"
    f.write_bytes(b"data")

    with patch("processor.process_dicom_file") as mock_extract:
        result = run_process_file(f, make_options(tmp_path, dry_run=True))

    assert result["status"] == "dry_run"
    mock_extract.assert_not_called()


def test_process_file_success_commits(tmp_path, mock_db):
    f = tmp_path / "ok.dcm"
    f.write_bytes(b"data")

    with patch("processor.process_dicom_file", return_value=5) as mock_extract:
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "inserted"
    assert result["db_file_id"] == 5
    mock_extract.assert_called_once()
    mock_db.commit.assert_called()
    mock_db.close.assert_called()


def test_process_file_unique_violation_is_duplicate(tmp_path, mock_db):
    f = tmp_path / "a.dcm"
    f.write_bytes(b"data")

    with patch("processor.process_dicom_file", side_effect=psycopg2.errors.UniqueViolation()):
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "duplicate"
    mock_db.rollback.assert_called()


def test_process_file_extraction_error_rolls_back(tmp_path, mock_db):
    f = tmp_path / "a.dcm"
    f.write_bytes(b"data")

    with patch("processor.process_dicom_file", side_effect=ValueError("bad dicom")):
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "error"
    assert "bad dicom" in result["message"]
    mock_db.rollback.assert_called()


# ------------------------- scan_and_import -------------------------


def test_scan_and_import_sequential_collects_results(tmp_path):
    for name in ("a.dcm", "b.dcm"):
        (tmp_path / name).write_bytes(b"data")

    fake = lambda path, opts: {"path": path, "status": "inserted"}
    with patch("processor.process_file", side_effect=fake):
        results = scan_and_import(str(tmp_path), make_options(tmp_path, workers=0))

    assert len(results) == 2
    assert all(r["status"] == "inserted" for r in results)


def test_scan_and_import_survives_worker_exception(tmp_path):
    (tmp_path / "a.dcm").write_bytes(b"data")

    with patch("processor.process_file", side_effect=RuntimeError("boom")), \
         patch("processor.handle_exception"):
        results = scan_and_import(str(tmp_path), make_options(tmp_path, workers=0))

    assert len(results) == 1
    assert results[0]["status"] == "error"

def test_process_file_survives_database_connection_failure(tmp_path):
    """If the DB is unreachable, the worker must return an error result,
    not crash with UnboundLocalError from the except/finally blocks."""
    f = tmp_path / "a.dcm"
    f.write_bytes(b"data")

    with patch("processor.config", return_value={}), \
         patch("processor.psycopg2.connect", side_effect=psycopg2.OperationalError("db down")), \
         patch("processor.pretty_log"):
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "error"
    assert "db down" in result["message"]


def test_scan_and_import_only_processes_given_file_list(tmp_path):
    for name in ("a.dcm", "b.dcm", "c.dcm"):
        (tmp_path / name).write_bytes(b"data")
    only = [str(tmp_path / "b.dcm")]

    fake = lambda path, opts: {"path": path, "status": "inserted"}
    with patch("processor.process_file", side_effect=fake):
        results = scan_and_import(str(tmp_path), make_options(tmp_path), file_list=only)

    assert [r["path"] for r in results] == only


def test_extraction_error_is_logged_once_with_exception_details(tmp_path, mock_db):
    """The DB event gets the exception object, so dicom_logger stores type + stack trace."""
    f = tmp_path / "a.dcm"
    f.write_bytes(b"data")

    with patch("processor.process_dicom_file", side_effect=ValueError("bad tag")), \
         patch("processor.log_db_event") as log_event, \
         patch("processor.pretty_log") as pretty:
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "error"
    assert "ValueError: bad tag" in result["message"]
    error_events = [c for c in log_event.call_args_list if c.args[3] == "ERROR"]
    assert len(error_events) == 1
    assert isinstance(error_events[0].kwargs["exc"], ValueError)
    assert [c.args[0] for c in pretty.call_args_list].count("ERROR") == 1


def test_unique_violation_is_logged_as_duplicate_never_error(tmp_path, mock_db):
    f = tmp_path / "a.dcm"
    f.write_bytes(b"data")

    with patch("processor.process_dicom_file", side_effect=psycopg2.errors.UniqueViolation()), \
         patch("processor.log_db_event") as log_event, \
         patch("processor.pretty_log") as pretty:
        result = run_process_file(f, make_options(tmp_path))

    assert result["status"] == "duplicate"
    levels = [c.args[3] for c in log_event.call_args_list]
    assert levels == ["DUPLICATE"]
    assert "ERROR" not in [c.args[0] for c in pretty.call_args_list]


def test_import_options_rejects_removed_fields():
    """subject_min_length, safe_dicom_folder, debug and log_to_db were never used and are gone."""
    for removed in ("subject_min_length", "safe_dicom_folder", "debug", "log_to_db"):
        with pytest.raises(TypeError):
            make_options(".", **{removed: 1})


# ------------------------- pixel data reading -------------------------


def test_read_dicom_header_skips_pixels_by_default():
    with patch("processor.pydicom.dcmread") as dcmread:
        read_dicom_header("x.dcm")
    assert dcmread.call_args.kwargs["stop_before_pixels"] is True


def test_read_dicom_header_with_pixels():
    with patch("processor.pydicom.dcmread") as dcmread:
        read_dicom_header("x.dcm", with_pixels=True)
    assert dcmread.call_args.kwargs["stop_before_pixels"] is False


@pytest.mark.parametrize("store_pixel_data, dry_run, expected", [
    (True, False, True),    # normal import: pixels are read so they can be stored
    (False, False, False),  # setting off: header only
    (True, True, False),    # dry run stores nothing, so it never reads pixels
])
def test_process_file_reads_pixels_only_when_storing_them(tmp_path, header, mock_db,
                                                         store_pixel_data, dry_run, expected):
    f = tmp_path / "scan.dcm"
    f.write_bytes(b"data")
    options = make_options(tmp_path, store_pixel_data=store_pixel_data, dry_run=dry_run)

    with patch("processor.read_dicom_header", return_value=header) as read, \
         patch("processor.process_dicom_file", return_value=1):
        run_process_file(f, options)

    assert read.call_args.kwargs["with_pixels"] is expected
