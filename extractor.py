import json
from datetime import datetime
import pydicom
import psycopg2.extras
from pydicom.errors import InvalidDicomError
from config import config
from logger import logger
from utils import Profiler, handle_exception


# ------------------------- Metadata Extraction -------------------------


def clean_tag_value(value):
    """
    Cleans pydicom data so it is safe for PostgreSQL JSONB/Text storage.
    """
    if value is None:
        return ""
    if isinstance(value, pydicom.multival.MultiValue):
        return "\\".join([str(v) for v in value])
    if isinstance(value, pydicom.sequence.Sequence):
        return "[Sequence]"
    if isinstance(value, pydicom.valuerep.PersonName):
        return str(value)
    return str(value)

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
    """Serialize the entire DICOM header into a queryable JSON dictionary."""
    metadata = {}
    for elem in dataset:
        if elem.tag.group == 0x7fe0:  # skip raw pixel data arrays
            continue
        tag_str = f"{elem.tag.group:04x}{elem.tag.element:04x}".upper()
        metadata[tag_str] = {
            "name": elem.keyword,
            "vr": elem.VR,
            "value": clean_tag_value(elem.value)
        }
    return json.dumps(metadata)

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
        
        tag_hex = f"({elem.tag.group:04X},{elem.tag.element:04X})"
        name = elem.keyword if elem.keyword else "Unknown"
        vr = elem.VR if elem.VR else "UN"
        val_str = clean_tag_value(elem.value)
        
        if len(val_str) > 1000:
            val_str = val_str[:997] + "..."

        header_records.append((file_id, tag_hex, name, vr, val_str))

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

def process_dicom_file(conn, abs_path: str, filename: str, sha: str, file_size: int) -> int:
    """
    Main entry point. Coordinates the hierarchical extraction and insertion sequentially.
    """
    try:
        dataset = pydicom.dcmread(abs_path, stop_before_pixels=True)
        
        patient_id = extract_and_upsert_patient(conn, dataset, sha)
        study_id = extract_and_upsert_study(conn, dataset, patient_id)
        series_id = extract_and_upsert_series(conn, dataset, study_id)
        file_id = extract_and_insert_file(conn, dataset, series_id, filename, abs_path, sha, file_size)
        
        extract_and_insert_headers(conn, dataset, file_id)

        logger.info(f"Successfully processed medical hierarchy for file_id: {file_id}")
        return file_id
        
    except Exception as e:
        handle_exception(e, options=None, file_path=abs_path, level="ERROR")
        raise