import os
import time
import hashlib
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from processor import (
    is_valid_filename,
    sanitize_and_validate_path,
    compute_sha256,
    process_file,
    scan_and_import,
)
from utils import ImportOptions, ImportErrorWithContext


# ------------------------- Helpers -------------------------


def make_options(base_folder, **overrides):
    defaults = dict(
        base_folder=os.path.realpath(str(base_folder)),
        min_size=1,
        max_size=10 * 1024 * 1024,
        subject_min_length=3,
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


@pytest.fixture
def mock_db():
    """Replaces config, DB connection, and DB/console logging for process_file tests."""
    conn = make_mock_conn()
    with patch("processor.config", return_value={}), \
         patch("processor.psycopg2.connect", return_value=conn), \
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
    "Ασθενής01.dcm",  # Greek characters are allowed
])
def test_valid_filenames(name):
    assert is_valid_filename(name) is True


@pytest.mark.parametrize("name", [
    "subject@test!#$%.dcm",
    "../etc/passwd",
    "folder/file.dcm",
    "file;rm -rf.dcm",
    "",
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


def test_process_file_rejects_too_old(tmp_path, mock_db):
    f = tmp_path / "old.dcm"
    f.write_bytes(b"data")
    five_years_ago = time.time() - 5 * 365 * 24 * 3600
    os.utime(f, (five_years_ago, five_years_ago))

    result = run_process_file(f, make_options(tmp_path, max_file_age_months=24))
    assert result["status"] == "invalid"
    assert "too old" in result["message"]


def test_process_file_rejects_future_date(tmp_path, mock_db):
    f = tmp_path / "future.dcm"
    f.write_bytes(b"data")
    future = time.time() + 90 * 24 * 3600
    os.utime(f, (future, future))

    result = run_process_file(f, make_options(tmp_path))
    assert result["status"] == "invalid"
    assert "future" in result["message"]


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