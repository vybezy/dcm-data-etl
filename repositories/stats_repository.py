"""sql for the dashboard."""

from repositories import common

_COUNTS = """
    SELECT
        (SELECT COUNT(*) FROM dicom_patients) AS patients,
        (SELECT COUNT(*) FROM dicom_studies) AS studies,
        (SELECT COUNT(*) FROM dicom_series) AS series,
        (SELECT COUNT(*) FROM dicom_instances) AS instances,
        (SELECT COALESCE(SUM(file_size_bytes), 0) FROM dicom_instances) AS total_file_bytes,
        (SELECT COALESCE(SUM(pixel_data_size_bytes), 0) FROM dicom_pixel_data)
            AS total_pixel_bytes
"""


def get_counts() -> dict:
    """
    counts how many patients, studies, series, etc. in the database
    and stores values in dict, mapping the data to the right name.
    """
    return common.fetch_all(_COUNTS, ())[0]
