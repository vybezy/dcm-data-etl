"""sql for the stored pixel data of one instance (step 1: read the bytes)."""

from repositories import common


def get_pixel_data(file_id: int) -> dict | None:
    # rows and columns live in dicom_instances, everything else in dicom_pixel_data
    rows = common.fetch_all("""
        SELECT i.rows, i.columns, p.transfer_syntax_uid, p.samples_per_pixel,
               p.bits_allocated, p.pixel_representation, p.photometric_interpretation,
               p.rescale_slope, p.rescale_intercept, p.pixel_data
        FROM dicom_pixel_data p
        JOIN dicom_instances i ON i.file_id = p.file_id
        WHERE p.file_id = %s
    """, (file_id,))
    return rows[0] if rows else None
