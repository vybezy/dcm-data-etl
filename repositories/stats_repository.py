"""sql for the dashboard"""

from database import db_connection


def get_counts() -> dict:
    with db_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM dicom_patients),
                (SELECT COUNT(*) FROM dicom_studies),
                (SELECT COUNT(*) FROM dicom_series),
                (SELECT COUNT(*) FROM dicom_instances),
                (SELECT COALESCE(SUM(file_size_bytes), 0) FROM dicom_instances),
                (SELECT COALESCE(SUM(pixel_data_size_bytes), 0) FROM dicom_pixel_data)
        """)
        row = cur.fetchone()

    return {
        "patients": row[0],
        "studies": row[1],
        "series": row[2],
        "instances": row[3],
        "total_file_bytes": row[4],
        "total_pixel_bytes": row[5],
    }
