import json
from datetime import datetime
import pydicom
import psycopg2.extras
from logger import logger
from utils import Profiler


# ------------------------- Metadata Extraction -------------------------


# Value Representations that hold raw bytes rather than text or numbers
BINARY_VRS = {"OB", "OD", "OF", "OL", "OV", "OW", "UN"}

# Max characters stored per value in dicom_header (the JSONB column keeps everything)
MAX_HEADER_VALUE_LENGTH = 1000


def tag_key(tag) -> str:
    """
    One tag format everywhere: 8 uppercase hex digits, e.g. '00080060' for Modality.
    This is the key format of the DICOM JSON Model (PS3.18 Annex F).
    """
    return f"{tag.group:04X}{tag.element:04X}"


def _strip_nulls(text: str) -> str:
    """PostgreSQL TEXT and JSONB reject the NUL character, which some scanners pad values with."""
    return text.replace("\x00", "")


def element_to_json(value, vr=None):
    """
    Converts a pydicom element value to a JSON-safe Python value:
      - sequences (SQ) become a list of nested tag dictionaries, so no data is lost
      - binary values become a short '<binary: N bytes>' description
      - multi-values are joined with backslash, the DICOM separator
      - everything else becomes text with NUL characters removed
    """
    if value is None:
        return ""
    if isinstance(value, pydicom.sequence.Sequence):
        return [dataset_to_dict(item) for item in value]
    if isinstance(value, (bytes, bytearray)) or vr in BINARY_VRS:
        size = len(value) if hasattr(value, "__len__") else 0
        return f"<binary: {size} bytes>"
    if isinstance(value, pydicom.multival.MultiValue):
        return _strip_nulls("\\".join(str(v) for v in value))
    return _strip_nulls(str(value))


def dataset_to_dict(dataset) -> dict:
    """Every tag of a dataset (pixel data excluded) as {tag_key: {name, vr, value}}."""
    result = {}
    for elem in dataset:
        if elem.tag.group == 0x7FE0:  # skip raw pixel data
            continue
        result[tag_key(elem.tag)] = {
            "name": elem.keyword,
            "vr": elem.VR,
            "value": element_to_json(elem.value, elem.VR),
        }
    return result


def clean_tag_value(value, vr=None) -> str:
    """
    Text form of a value for the dicom_header table.
    Sequences are stored as their JSON structure.
    """
    converted = element_to_json(value, vr)
    if isinstance(converted, list):
        return json.dumps(converted)
    return converted


def parse_dicom_date(value):
    """
    Converts a DICOM DA value (YYYYMMDD) to an ISO date string 'YYYY-MM-DD'.
    Also accepts the legacy ACR-NEMA form YYYY.MM.DD.
    Returns None for empty or invalid dates (e.g. '20241399') instead of raising,
    so one bad tag doesn't make the whole file fail to import.
    """
    if value is None:
        return None
    text = str(value).strip().replace(".", "")
    if not text:
        return None
    # strptime alone would accept '2024011' as 2024-01-01, so require 8 digits
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            pass
    logger.warning("Ignoring invalid DICOM date: %r", str(value))
    return None


def parse_dicom_time(value):
    """
    Converts a DICOM TM value (HH, HHMM, HHMMSS or HHMMSS.FFFFFF) to 'HH:MM:SS'.
    Also accepts the legacy form HH:MM:SS. Fractional seconds are dropped.
    Returns None for empty or invalid times (e.g. '256000').
    """
    if value is None:
        return None
    text = str(value).strip().replace(":", "").split(".")[0]
    if not text:
        return None
    formats = {6: "%H%M%S", 4: "%H%M", 2: "%H"}  # DICOM allows truncated times
    fmt = formats.get(len(text))
    if fmt and text.isdigit():
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M:%S")
        except ValueError:
            pass
    logger.warning("Ignoring invalid DICOM time: %r", str(value))
    return None


def build_metadata_json(dataset: pydicom.dataset.FileDataset) -> str:
    """Serialize the entire DICOM header, including nested sequences, into a queryable JSON dictionary."""
    return json.dumps(dataset_to_dict(dataset))

@Profiler
def extract_and_upsert_patient(conn, dataset: pydicom.dataset.FileDataset, sha: str) -> int:
    """
    Extracts patient demographics and returns the patient_id.
    """
    mrn = str(dataset.get("PatientID", f"UNKNOWN_{sha[:8]}"))
    name = str(dataset.get("PatientName", "ANONYMOUS"))
    birth_date = parse_dicom_date(dataset.get("PatientBirthDate", None))
    sex = dataset.get("PatientSex", None)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dicom_patients (medical_record_number, patient_name, birth_date, sex)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (medical_record_number) DO UPDATE
            SET patient_name = EXCLUDED.patient_name
            RETURNING patient_id;
        """, (mrn, name, birth_date, sex))
        return cur.fetchone()[0]

@Profiler
def extract_and_upsert_study(conn, dataset: pydicom.dataset.FileDataset, patient_id: int) -> int:
    """
    Extracts the clinical study/exam details and returns the study_id.
    """
    study_uid = str(dataset.get("StudyInstanceUID", ""))
    if not study_uid:
        raise ValueError("Missing critical DICOM Tag: StudyInstanceUID")

    study_date = parse_dicom_date(dataset.get("StudyDate", None))
    study_time = parse_dicom_time(dataset.get("StudyTime", None))
    accession = dataset.get("AccessionNumber", None)
    description = dataset.get("StudyDescription", None)
    physician = str(dataset.get("ReferringPhysicianName", ""))

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dicom_studies (
                patient_id, study_instance_uid, study_date, study_time,
                accession_number, study_description, referring_physician
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (study_instance_uid) DO UPDATE
            SET study_description = EXCLUDED.study_description
            RETURNING study_id;
        """, (patient_id, study_uid, study_date, study_time, accession, description, physician))
        return cur.fetchone()[0]

@Profiler
def extract_and_upsert_series(conn, dataset: pydicom.dataset.FileDataset, study_id: int) -> int:
    """
    Extracts the scanner protocol data and returns the series_id.
    """
    series_uid = str(dataset.get("SeriesInstanceUID", ""))
    if not series_uid:
        raise ValueError("Missing critical DICOM Tag: SeriesInstanceUID")

    series_num = dataset.get("SeriesNumber", None)
    modality = dataset.get("Modality", "UNKNOWN")
    body_part = dataset.get("BodyPartExamined", None)
    series_desc = dataset.get("SeriesDescription", None)

    slice_thick = dataset.get("SliceThickness", None)
    try:
        slice_thick = float(slice_thick) if slice_thick else None
    except Exception:
        slice_thick = None

    pixel_spacing = dataset.get("PixelSpacing", None)
    spacing_array = None
    if pixel_spacing and isinstance(pixel_spacing, pydicom.multival.MultiValue):
        try:
            spacing_array = [float(pixel_spacing[0]), float(pixel_spacing[1])]
        except Exception:
            pass

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dicom_series (
                study_id, series_instance_uid, series_number, modality,
                body_part_examined, series_description, slice_thickness_mm, pixel_spacing
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (series_instance_uid) DO UPDATE
            SET series_description = EXCLUDED.series_description
            RETURNING series_id;
        """, (study_id, series_uid, series_num, modality, body_part, series_desc, slice_thick, spacing_array))
        return cur.fetchone()[0]

@Profiler
def extract_and_insert_file(conn, dataset: pydicom.dataset.FileDataset, series_id: int,
                            filename: str, abs_path: str, sha: str, file_size: int) -> int:
    """
    Extracts the file-level instances and returns the master file_id.
    """
    sop_uid = str(dataset.get("SOPInstanceUID", ""))
    if not sop_uid:
        raise ValueError("Missing critical DICOM Tag: SOPInstanceUID")

    instance_num = dataset.get("InstanceNumber", None)
    rows = dataset.get("Rows", None)
    cols = dataset.get("Columns", None)

    img_pos = dataset.get("ImagePositionPatient", None)
    pos_array = None
    if img_pos and isinstance(img_pos, pydicom.multival.MultiValue) and len(img_pos) == 3:
        try:
            pos_array = [float(img_pos[0]), float(img_pos[1]), float(img_pos[2])]
        except Exception:
            pass

    metadata_json = build_metadata_json(dataset)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO dicom_instances (
                series_id, sop_instance_uid, instance_number, file_name,
                file_path, file_size_bytes, file_sha256_hash, image_position_patient,
                rows, columns, metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING file_id;
        """, (series_id, sop_uid, instance_num, filename, abs_path, file_size, sha, pos_array, rows, cols, metadata_json))
        return cur.fetchone()[0]

@Profiler
def extract_and_insert_headers(conn, dataset: pydicom.dataset.FileDataset, file_id: int):
    """
    Extracts all individual DICOM tags and uses execute_values for high-speed bulk inserts.
    """
    header_records = []

    for elem in dataset:
        if elem.tag.group == 0x7fe0:  # Skip raw pixel data
            continue

        name = elem.keyword if elem.keyword else "Unknown"
        vr = elem.VR if elem.VR else "UN"
        val_str = clean_tag_value(elem.value, vr)

        if len(val_str) > MAX_HEADER_VALUE_LENGTH:
            val_str = val_str[:MAX_HEADER_VALUE_LENGTH - 3] + "..."

        header_records.append((file_id, tag_key(elem.tag), name, vr, val_str))

    if header_records:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO dicom_header (header_file_id, header_tag, header_name, header_vr, header_value)
                VALUES %s
                ON CONFLICT (header_file_id, header_tag) DO NOTHING;
                """,
                header_records,
                template="(%s, %s, %s, %s, %s)",
                page_size=1000
            )

def process_dicom_file(conn, dataset: pydicom.dataset.FileDataset, abs_path: str,
                       filename: str, sha: str, file_size: int) -> int:
    """
    Main entry point. Coordinates the hierarchical extraction and insertion sequentially.
    `dataset` is the header already read (and validated) by processor.process_file(),
    so the file is only parsed once.

    Errors are deliberately not caught here: they propagate to processor.process_file(),
    which rolls back the transaction and logs the failure exactly once
    (console + dicom_logger, including exception type and stack trace).
    """
    patient_id = extract_and_upsert_patient(conn, dataset, sha)
    study_id = extract_and_upsert_study(conn, dataset, patient_id)
    series_id = extract_and_upsert_series(conn, dataset, study_id)
    file_id = extract_and_insert_file(conn, dataset, series_id, filename, abs_path, sha, file_size)

    extract_and_insert_headers(conn, dataset, file_id)

    return file_id
