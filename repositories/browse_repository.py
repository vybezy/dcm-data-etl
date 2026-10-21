"""sql for browsing patients -> studies -> series -> instances."""

from repositories import common


def list_patients(limit: int, offset: int) -> list[dict]:
    return common.fetch_all("""
        SELECT p.patient_id, p.patient_name, p.sex,
               (SELECT COUNT(*) FROM dicom_studies s
                WHERE s.patient_id = p.patient_id) AS study_count
        FROM dicom_patients p
        ORDER BY p.patient_id
        LIMIT %s OFFSET %s
    """, (limit, offset))


def list_studies(patient_id: int) -> list[dict]:
    return common.fetch_all("""
        SELECT st.study_id, st.study_date, st.study_description,
               (SELECT COUNT(*) FROM dicom_series se
                WHERE se.study_id = st.study_id) AS series_count
        FROM dicom_studies st
        WHERE st.patient_id = %s
        ORDER BY st.study_date, st.study_id
    """, (patient_id,))


def list_series(study_id: int) -> list[dict]:
    return common.fetch_all("""
        SELECT se.series_id, se.series_number, se.modality, se.body_part_examined,
               se.series_description, se.slice_thickness_mm,
               (SELECT COUNT(*) FROM dicom_instances i
                WHERE i.series_id = se.series_id) AS instance_count
        FROM dicom_series se
        WHERE se.study_id = %s
        ORDER BY se.series_number, se.series_id
    """, (study_id,))


def list_instances(series_id: int) -> list[dict]:
    return common.fetch_all("""
        SELECT file_id, instance_number, rows, columns, file_size_bytes
        FROM dicom_instances
        WHERE series_id = %s
        ORDER BY instance_number NULLS LAST, file_id
    """, (series_id,))


def patient_exists(patient_id: int) -> bool:
    sql = "SELECT 1 FROM dicom_patients WHERE patient_id = %s"
    return common.fetch_all(sql, (patient_id,)) != []


def study_exists(study_id: int) -> bool:
    sql = "SELECT 1 FROM dicom_studies WHERE study_id = %s"
    return common.fetch_all(sql, (study_id,)) != []


def series_exists(series_id: int) -> bool:
    sql = "SELECT 1 FROM dicom_series WHERE series_id = %s"
    return common.fetch_all(sql, (series_id,)) != []
