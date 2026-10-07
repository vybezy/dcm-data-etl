import json
import pytest
from unittest.mock import MagicMock, patch
from pydicom.dataset import Dataset
from pydicom.dataelem import DataElement
from pydicom.sequence import Sequence

from extractor import (
    clean_tag_value,
    build_metadata_json,
    extract_and_upsert_patient,
    extract_and_upsert_study,
    extract_and_insert_headers,
    parse_dicom_date,
    parse_dicom_time,
)


# ------------------------- Helpers -------------------------


def make_mock_conn(fetchone_value=(1,)):
    """Returns (conn, cursor) where conn.cursor() works as a context manager."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_value
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def make_dataset():
    ds = Dataset()
    ds.add(DataElement((0x0010, 0x0010), "PN", "Doe^John"))      # PatientName
    ds.add(DataElement((0x0008, 0x0060), "CS", "CT"))            # Modality
    ds.add(DataElement((0x0008, 0x0018), "UI", "1.2.3.4.5"))     # SOPInstanceUID
    ds.add(DataElement((0x7FE0, 0x0010), "OB", b"\x00\x01"))     # PixelData (must be skipped)
    return ds


# ------------------------- clean_tag_value -------------------------


def test_clean_tag_value_none():
    assert clean_tag_value(None) == ""


def test_clean_tag_value_plain_string_and_number():
    assert clean_tag_value("CT") == "CT"
    assert clean_tag_value(42) == "42"


def test_clean_tag_value_person_name():
    ds = Dataset()
    ds.add(DataElement((0x0010, 0x0010), "PN", "Doe^John"))
    assert clean_tag_value(ds.PatientName) == "Doe^John"


def test_clean_tag_value_multivalue_joined_with_backslash():
    ds = Dataset()
    ds.add(DataElement((0x0008, 0x0008), "CS", ["ORIGINAL", "PRIMARY"]))  # ImageType
    assert clean_tag_value(ds.ImageType) == "ORIGINAL\\PRIMARY"


def test_clean_tag_value_sequence():
    seq = Sequence([Dataset()])
    assert clean_tag_value(seq) == "[Sequence]"


# ------------------------- build_metadata_json -------------------------


def test_build_metadata_json_structure_and_pixel_skip():
    result = json.loads(build_metadata_json(make_dataset()))

    assert result["00100010"] == {"name": "PatientName", "vr": "PN", "value": "Doe^John"}
    assert result["00080060"]["value"] == "CT"
    assert "7FE00010" not in result  # pixel data excluded


# ------------------------- extract_and_insert_headers -------------------------


def test_insert_headers_bulk_payload():
    conn, _ = make_mock_conn()

    with patch("extractor.psycopg2.extras.execute_values") as mock_execute:
        extract_and_insert_headers(conn, make_dataset(), 99)

    assert mock_execute.call_count == 1
    _, query, records = mock_execute.call_args[0]

    assert "INSERT INTO dicom_header" in query
    assert "ON CONFLICT" in query
    assert (99, "(0010,0010)", "PatientName", "PN", "Doe^John") in records
    assert all(r[1] != "(7FE0,0010)" for r in records)  # pixel data skipped


def test_insert_headers_truncates_long_values():
    ds = Dataset()
    ds.add(DataElement((0x0020, 0x4000), "LT", "x" * 2000))  # ImageComments
    conn, _ = make_mock_conn()

    with patch("extractor.psycopg2.extras.execute_values") as mock_execute:
        extract_and_insert_headers(conn, ds, 1)

    value = mock_execute.call_args[0][2][0][4]
    assert len(value) == 1000
    assert value.endswith("...")


def test_insert_headers_empty_dataset_does_not_hit_db():
    conn, _ = make_mock_conn()

    with patch("extractor.psycopg2.extras.execute_values") as mock_execute:
        extract_and_insert_headers(conn, Dataset(), 1)

    mock_execute.assert_not_called()


# ------------------------- patient / study upserts -------------------------


def test_upsert_patient_formats_birth_date_and_returns_id():
    ds = Dataset()
    ds.PatientID = "MRN123"
    ds.PatientName = "Doe^John"
    ds.PatientBirthDate = "19900131"
    ds.PatientSex = "M"
    conn, cur = make_mock_conn(fetchone_value=(7,))

    patient_id = extract_and_upsert_patient(conn, ds, "abcdef1234567890")

    assert patient_id == 7
    params = cur.execute.call_args[0][1]
    assert params == ("MRN123", "Doe^John", "1990-01-31", "M")


def test_upsert_patient_missing_fields_use_fallbacks():
    conn, cur = make_mock_conn(fetchone_value=(1,))

    extract_and_upsert_patient(conn, Dataset(), "abcdef1234567890")

    mrn, name, birth_date, sex = cur.execute.call_args[0][1]
    assert mrn == "UNKNOWN_abcdef12"
    assert name == "ANONYMOUS"
    assert birth_date is None
    assert sex is None


def test_upsert_study_requires_study_uid():
    conn, _ = make_mock_conn()

    with pytest.raises(ValueError, match="StudyInstanceUID"):
        extract_and_upsert_study(conn, Dataset(), patient_id=1)


def test_upsert_study_formats_date_and_time():
    ds = Dataset()
    ds.StudyInstanceUID = "1.2.840.1"
    ds.StudyDate = "20240115"
    ds.StudyTime = "134502.000"
    conn, cur = make_mock_conn(fetchone_value=(5,))

    study_id = extract_and_upsert_study(conn, ds, patient_id=3)

    assert study_id == 5
    params = cur.execute.call_args[0][1]
    assert params[0] == 3
    assert params[1] == "1.2.840.1"
    assert params[2] == "2024-01-15"
    assert params[3] == "13:45:02"

# ------------------------- date / time parsing -------------------------


@pytest.mark.parametrize("raw, expected", [
    ("20240115", "2024-01-15"),
    ("2024.01.15", "2024-01-15"),   # legacy ACR-NEMA format
    (" 20240229 ", "2024-02-29"),   # leap day, padding stripped
])
def test_parse_dicom_date_valid(raw, expected):
    assert parse_dicom_date(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "20241399", "20230229", "2024011", "abcdefgh",
])
def test_parse_dicom_date_invalid_returns_none(raw):
    assert parse_dicom_date(raw) is None


@pytest.mark.parametrize("raw, expected", [
    ("134502", "13:45:02"),
    ("134502.123456", "13:45:02"),  # fractional seconds dropped
    ("1345", "13:45:00"),           # truncated forms allowed by DICOM
    ("13", "13:00:00"),
    ("13:45:02", "13:45:02"),       # legacy format
])
def test_parse_dicom_time_valid(raw, expected):
    assert parse_dicom_time(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "256000", "136100", "12345", "ab"])
def test_parse_dicom_time_invalid_returns_none(raw):
    assert parse_dicom_time(raw) is None


def test_upsert_study_invalid_date_is_stored_as_null_not_fatal():
    ds = Dataset()
    ds.StudyInstanceUID = "1.2.840.1"
    ds.StudyDate = "20241399"
    ds.StudyTime = "256000"
    conn, cur = make_mock_conn(fetchone_value=(5,))

    assert extract_and_upsert_study(conn, ds, patient_id=3) == 5
    params = cur.execute.call_args[0][1]
    assert params[2] is None  # study_date
    assert params[3] is None  # study_time


def test_upsert_patient_invalid_birth_date_is_stored_as_null():
    ds = Dataset()
    ds.PatientID = "MRN1"
    ds.PatientBirthDate = "19901340"
    conn, cur = make_mock_conn(fetchone_value=(1,))

    extract_and_upsert_patient(conn, ds, "abcdef1234567890")
    assert cur.execute.call_args[0][1][2] is None
