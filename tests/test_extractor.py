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
    extract_and_insert_pixel_data,
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


def test_clean_tag_value_sequence_is_stored_as_json():
    item = Dataset()
    item.add(DataElement((0x0008, 0x0100), "SH", "T-04000"))   # CodeValue
    seq = Sequence([item])
    assert json.loads(clean_tag_value(seq)) == [
        {"00080100": {"name": "CodeValue", "vr": "SH", "value": "T-04000"}}
    ]


def test_clean_tag_value_binary_is_described_not_dumped():
    assert clean_tag_value(b"\x00\x01\x02\x03", "OB") == "<binary: 4 bytes>"
    assert clean_tag_value(b"abc") == "<binary: 3 bytes>"


def test_clean_tag_value_strips_null_characters():
    assert clean_tag_value("CT\x00\x00") == "CT"
    assert "\x00" not in clean_tag_value("A\x00B")


def test_metadata_json_keeps_nested_sequences():
    item = Dataset()
    item.add(DataElement((0x0008, 0x0100), "SH", "T-04000"))
    ds = Dataset()
    ds.add(DataElement((0x0008, 0x2218), "SQ", Sequence([item])))  # AnatomicRegionSequence

    result = json.loads(build_metadata_json(ds))
    region = result["00082218"]
    assert region["vr"] == "SQ"
    assert region["value"][0]["00080100"]["value"] == "T-04000"


def test_header_rows_and_json_use_the_same_tag_format():
    conn, _ = make_mock_conn()
    ds = make_dataset()
    with patch("extractor.psycopg2.extras.execute_values") as mock_execute:
        extract_and_insert_headers(conn, ds, 1)

    header_tags = {r[1] for r in mock_execute.call_args[0][2]}
    json_tags = set(json.loads(build_metadata_json(ds)))
    assert header_tags == json_tags


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
    assert (99, "00100010", "PatientName", "PN", "Doe^John") in records
    assert all(r[1] != "7FE00010" for r in records)  # pixel data skipped


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


# ------------------------- process_dicom_file -------------------------


def test_process_dicom_file_propagates_errors_without_logging():
    """Error reporting belongs to processor.py; the extractor must not log on its own."""
    from extractor import process_dicom_file
    conn, _ = make_mock_conn()

    with patch("extractor.extract_and_upsert_patient", side_effect=ValueError("bad patient")), \
         patch("extractor.logger") as log:
        with pytest.raises(ValueError, match="bad patient"):
            process_dicom_file(conn, Dataset(), "x.dcm", "x.dcm", "abc", 10)

    assert not log.method_calls


# ------------------------- extract_and_insert_pixel_data -------------------------


def make_image_dataset(pixel_bytes=b"\x01\x00\x02\x00\x03\x00\x04\x00"):
    """a 2x2 16-bit CT-like image with the tags needed to rebuild it."""
    from pydicom.dataset import FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.PixelRepresentation = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.RescaleSlope = "1"
    ds.RescaleIntercept = "-1024"
    ds.add(DataElement((0x7FE0, 0x0010), "OW", pixel_bytes))
    return ds


def test_pixel_data_is_stored_with_the_tags_to_rebuild_it():
    import hashlib
    pixels = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    conn, cur = make_mock_conn()

    assert extract_and_insert_pixel_data(conn, make_image_dataset(pixels), 7) is True

    params = cur.execute.call_args[0][1]
    assert params[0] == 7                              # file_id
    assert params[1] == "1.2.840.10008.1.2.1"          # transfer syntax
    assert params[2:5] == (2, 2, 1)                    # rows, columns, frames
    assert params[5:9] == (1, 16, 12, 1)               # samples, bits allocated/stored, signed
    assert params[9] == "MONOCHROME2"
    assert params[10:12] == (1.0, -1024.0)             # rescale slope, intercept
    assert params[12] == len(pixels)
    assert params[13] == hashlib.sha256(pixels).hexdigest()
    assert params[14] == pixels                        # bytes stored unchanged


def test_pixel_data_skipped_when_dataset_has_none():
    """a header read with stop_before_pixels has no pixel data: nothing is inserted."""
    ds = make_image_dataset()
    del ds[0x7FE0, 0x0010]
    conn, cur = make_mock_conn()

    assert extract_and_insert_pixel_data(conn, ds, 7) is False
    cur.execute.assert_not_called()


def test_pixel_data_without_dimensions_is_an_error():
    ds = make_image_dataset()
    del ds.Rows
    conn, _ = make_mock_conn()

    with pytest.raises(ValueError, match="Rows/Columns"):
        extract_and_insert_pixel_data(conn, ds, 7)


def test_process_dicom_file_stores_pixel_data_in_same_transaction():
    from extractor import process_dicom_file
    conn, _ = make_mock_conn()
    ds = make_image_dataset()

    with patch("extractor.extract_and_upsert_patient", return_value=1), \
         patch("extractor.extract_and_upsert_study", return_value=2), \
         patch("extractor.extract_and_upsert_series", return_value=3), \
         patch("extractor.extract_and_insert_file", return_value=4), \
         patch("extractor.extract_and_insert_headers"), \
         patch("extractor.extract_and_insert_pixel_data") as pixels:
        assert process_dicom_file(conn, ds, "x.dcm", "x.dcm", "abc", 10) == 4

    pixels.assert_called_once_with(conn, ds, 4)
    conn.commit.assert_not_called()  # processor.py commits once, after everything
