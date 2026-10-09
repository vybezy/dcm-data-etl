"""
End-to-end integration tests

Required env vars:
    TEST_DB_NAME      e.g. dicom_test
    TEST_DB_USER      e.g. postgres
    TEST_DB_PASSWORD  e.g. postgres
Optional:
    TEST_DB_HOST      default: localhost
    TEST_DB_PORT      default: 5432 (use 5433 for the docker-compose db)
"""
import os
import json
import hashlib
from datetime import date
from dataclasses import asdict

import pytest
import psycopg2
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, CTImageStorage, generate_uid

from config import config
from db_init import db_init
from logger import logger
from database import create_import_session
from processor import process_file, scan_and_import
from utils import ImportOptions

TEST_DB_NAME = os.getenv("TEST_DB_NAME", "")

pytestmark = pytest.mark.skipif(
    "test" not in TEST_DB_NAME.lower(),
    reason="Set TEST_DB_NAME (must contain 'test') to run DB integration tests",
)


# ------------------------- Fixtures & helpers -------------------------


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Points the pipeline at the test DB and starts every test with empty tables."""
    monkeypatch.setenv("DB_HOST", os.getenv("TEST_DB_HOST", "localhost"))
    monkeypatch.setenv("DB_NAME", TEST_DB_NAME)
    monkeypatch.setenv("DB_USER", os.getenv("TEST_DB_USER", "postgres"))
    monkeypatch.setenv("DB_PASSWORD", os.getenv("TEST_DB_PASSWORD", "postgres"))
    monkeypatch.setenv("DB_PORT", os.getenv("TEST_DB_PORT", "5432"))
    monkeypatch.chdir(tmp_path)  # keeps profiler_logs.txt etc. out of the repo

    db_init(reset_tables=True, logger=logger)
    conn = psycopg2.connect(**config())
    yield conn
    conn.close()


def scalar(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def write_dicom(folder, filename, *, patient_id="MRN001", patient_name="Doe^John",
                study_uid=None, series_uid=None, sop_uid=None, instance_number=1,
                pixels=False):
    """Writes a small but valid DICOM file and returns its path.
    header only, unless pixels=True adds a 4x4 signed 16-bit image."""
    sop_uid = sop_uid or generate_uid()

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = sop_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    path = os.path.join(str(folder), filename)
    ds = FileDataset(path, {}, file_meta=meta, preamble=b"\0" * 128)

    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.PatientBirthDate = "19900131"
    ds.PatientSex = "M"
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.StudyDate = date.today().strftime("%Y%m%d")  # always within the age limit
    ds.StudyTime = "134502"
    ds.StudyDescription = "Test study"
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.SeriesNumber = 1
    ds.Modality = "CT"
    ds.InstanceNumber = instance_number
    ds.Rows = 4
    ds.Columns = 4
    ds.PixelSpacing = [0.5, 0.5]
    ds.ImagePositionPatient = [0.0, 0.0, float(instance_number)]

    if pixels:
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.RescaleSlope = "1"
        ds.RescaleIntercept = "-1024"
        # 16 values from -8 to 7, little endian, so the bytes are easy to check
        ds.PixelData = b"".join(v.to_bytes(2, "little", signed=True) for v in range(-8, 8))

    ds.save_as(path)
    return path


def make_options(folder, **overrides):
    defaults = dict(
        base_folder=os.path.realpath(str(folder)),
        min_size=1,
        max_size=50 * 1024 * 1024,
        max_file_age_months=24,
        workers=0,
        session_id=None,
    )
    defaults.update(overrides)
    return ImportOptions(**defaults)


def run(path, options):
    return process_file(path, asdict(options))


# ------------------------- Tests -------------------------


def test_full_pipeline_populates_entire_hierarchy(db, tmp_path):
    path = write_dicom(tmp_path, "scan1.dcm")

    result = run(path, make_options(tmp_path))

    assert result["status"] == "inserted"
    assert scalar(db, "SELECT count(*) FROM dicom_patients") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_studies") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_series") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_instances") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_header") > 0

    assert scalar(db, "SELECT patient_name FROM dicom_patients") == "Doe^John"
    assert scalar(db, "SELECT medical_record_number FROM dicom_patients") == "MRN001"
    assert str(scalar(db, "SELECT birth_date FROM dicom_patients")) == "1990-01-31"
    assert scalar(db, "SELECT modality FROM dicom_series") == "CT"
    assert scalar(db, "SELECT pixel_spacing FROM dicom_series") == [0.5, 0.5]


def test_instance_stores_hash_and_queryable_json(db, tmp_path):
    path = write_dicom(tmp_path, "scan1.dcm")
    run(path, make_options(tmp_path))

    expected_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert scalar(db, "SELECT file_sha256_hash FROM dicom_instances") == expected_sha

    md = scalar(db, "SELECT metadata_json FROM dicom_instances")
    md = md if isinstance(md, dict) else json.loads(md)
    assert md["00100010"]["name"] == "PatientName"
    assert md["00100010"]["value"] == "Doe^John"
    assert "7FE00010" not in md  # pixel data lives in dicom_pixel_data, not in the JSON


def test_header_rows_match_dataset_tags(db, tmp_path):
    path = write_dicom(tmp_path, "scan1.dcm")
    run(path, make_options(tmp_path))

    value = scalar(
        db,
        "SELECT header_value FROM dicom_header WHERE header_tag = %s",
        ("00100010",),
    )
    assert value == "Doe^John"


def test_reimporting_same_file_is_detected_as_duplicate(db, tmp_path):
    path = write_dicom(tmp_path, "scan1.dcm")
    options = make_options(tmp_path)

    first = run(path, options)
    second = run(path, options)

    assert first["status"] == "inserted"
    assert second["status"] == "duplicate"
    assert second["db_file_id"] == first["db_file_id"]
    assert scalar(db, "SELECT count(*) FROM dicom_instances") == 1


def test_upserts_share_patient_study_and_series(db, tmp_path):
    study, series = generate_uid(), generate_uid()
    a = write_dicom(tmp_path, "slice1.dcm", study_uid=study, series_uid=series, instance_number=1)
    b = write_dicom(tmp_path, "slice2.dcm", study_uid=study, series_uid=series, instance_number=2)
    options = make_options(tmp_path)

    assert run(a, options)["status"] == "inserted"
    assert run(b, options)["status"] == "inserted"

    assert scalar(db, "SELECT count(*) FROM dicom_patients") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_studies") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_series") == 1
    assert scalar(db, "SELECT count(*) FROM dicom_instances") == 2


def test_corrupt_dicom_is_rejected_and_nothing_is_stored(db, tmp_path):
    bad = tmp_path / "corrupt.dcm"
    bad.write_bytes(os.urandom(512))

    result = run(str(bad), make_options(tmp_path))

    assert result["status"] == "error"
    for table in ("dicom_patients", "dicom_studies", "dicom_series", "dicom_instances"):
        assert scalar(db, f"SELECT count(*) FROM {table}") == 0


def test_failed_file_does_not_leave_partial_hierarchy(db, tmp_path):
    """A DICOM missing SOPInstanceUID fails at the last step; the patient/study/series
    rows written earlier in the same transaction must be rolled back."""
    path = write_dicom(tmp_path, "nosop.dcm")

    import pydicom
    ds = pydicom.dcmread(path)
    del ds.SOPInstanceUID
    ds.save_as(path)

    result = run(path, make_options(tmp_path))

    assert result["status"] == "error"
    assert scalar(db, "SELECT count(*) FROM dicom_patients") == 0
    assert scalar(db, "SELECT count(*) FROM dicom_studies") == 0


def test_session_events_are_logged_to_database(db, tmp_path):
    session_id = create_import_session()
    path = write_dicom(tmp_path, "scan1.dcm")

    run(path, make_options(tmp_path, session_id=session_id))

    count = scalar(
        db, "SELECT count(*) FROM dicom_logger WHERE log_logses_id = %s", (session_id,)
    )
    assert count >= 1
    level = scalar(
        db,
        "SELECT log_level FROM dicom_logger WHERE log_logses_id = %s ORDER BY log_timestamp DESC LIMIT 1",
        (session_id,),
    )
    assert level == "SUCCESS"


def test_parallel_import_with_process_pool(db, tmp_path):
    folder = tmp_path / "batch"
    folder.mkdir()
    for i in range(6):
        write_dicom(folder, f"file{i}.dcm", patient_id=f"MRN{i:03d}", patient_name=f"Patient^{i}")

    results = scan_and_import(str(folder), make_options(folder, workers=3))

    assert len(results) == 6
    assert all(r["status"] == "inserted" for r in results)
    assert scalar(db, "SELECT count(*) FROM dicom_instances") == 6
    assert scalar(db, "SELECT count(*) FROM dicom_patients") == 6

def test_schema_has_no_indexes_duplicating_unique_constraints(db):
    """UNIQUE constraints already create these indexes; a second copy only slows inserts."""
    duplicate_index_names = (
        "idx_patients_mrn", "idx_studies_uid", "idx_series_uid",
        "idx_instances_sha256", "idx_dicom_headers_file",
    )
    with db.cursor() as cur:
        cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
        indexes = dict(cur.fetchall())

    for name in duplicate_index_names:
        assert name not in indexes

    # every UNIQUE column is still covered by the index of its constraint
    unique_defs = [d for d in indexes.values() if d.startswith("CREATE UNIQUE INDEX")]
    for column in ("medical_record_number", "study_instance_uid", "series_instance_uid",
                   "sop_instance_uid", "file_sha256_hash", "header_file_id, header_tag"):
        assert any(f"({column})" in d for d in unique_defs), column


def test_old_scan_is_rejected_by_study_date_not_file_timestamp(db, tmp_path):
    import pydicom
    path = write_dicom(tmp_path, "old_scan.dcm")
    ds = pydicom.dcmread(path)
    ds.StudyDate = "20000101"
    ds.save_as(path)  # the file on disk is brand new, the scan is from 2000

    result = run(path, make_options(tmp_path, max_file_age_months=24))

    assert result["status"] == "invalid"
    assert "StudyDate=2000-01-01" in result["message"]
    assert scalar(db, "SELECT count(*) FROM dicom_instances") == 0


def test_pixel_data_is_stored_byte_for_byte(db, tmp_path):
    import pydicom
    path = write_dicom(tmp_path, "image.dcm", pixels=True)
    original = pydicom.dcmread(path).PixelData

    result = run(path, make_options(tmp_path))
    assert result["status"] == "inserted"

    with db.cursor() as cur:
        cur.execute("""
            SELECT rows, columns, bits_allocated, pixel_representation, rescale_intercept,
                   transfer_syntax_uid, pixel_data_size_bytes, pixel_sha256, pixel_data
            FROM dicom_pixel_data WHERE file_id = %s
        """, (result["db_file_id"],))
        rows, cols, bits, signed, intercept, syntax, size, sha, stored = cur.fetchone()

    assert bytes(stored) == original
    assert sha == hashlib.sha256(original).hexdigest()
    assert (rows, cols, bits, signed, intercept, size) == (4, 4, 16, 1, -1024.0, 32)
    assert syntax == "1.2.840.10008.1.2.1"

    # pixel data is not copied into the header table either
    assert scalar(db, "SELECT count(*) FROM dicom_header WHERE header_tag = '7FE00010'") == 0


def test_pixel_data_not_stored_when_setting_is_off(db, tmp_path):
    path = write_dicom(tmp_path, "image.dcm", pixels=True)

    result = run(path, make_options(tmp_path, store_pixel_data=False))

    assert result["status"] == "inserted"
    assert scalar(db, "SELECT count(*) FROM dicom_pixel_data") == 0


def test_deleting_an_instance_deletes_its_pixels(db, tmp_path):
    path = write_dicom(tmp_path, "image.dcm", pixels=True)
    run(path, make_options(tmp_path))

    with db.cursor() as cur:
        cur.execute("DELETE FROM dicom_instances")
    db.commit()

    assert scalar(db, "SELECT count(*) FROM dicom_pixel_data") == 0
