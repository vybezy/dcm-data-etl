import numpy as np
import pytest

from services.browse_service import mask_name
from services.errors import UnsupportedImageError
from services.image_service import to_grey, to_grid, to_png


@pytest.mark.parametrize("name, expected", [
    ("DOE^JOHN", "D** J***"),
    ("SMITH", "S****"),
    ("ANONYMOUS", "ANONYMOUS"),
    ("", ""),
])
def test_mask_name(name, expected):
    assert mask_name(name) == expected


def ct_info(**changes):
    # a tiny 2 x 2 ct "image", stored the way dicom_pixel_data stores it
    info = {
        "rows": 2, "columns": 2,
        "transfer_syntax_uid": "1.2.840.10008.1.2.1",
        "samples_per_pixel": 1, "bits_allocated": 16, "pixel_representation": 1,
        "photometric_interpretation": "MONOCHROME2",
        "rescale_slope": 1.0, "rescale_intercept": -1024.0,
        "pixel_data": np.array([0, 1024, 1064, 2048], dtype="<i2").tobytes(),
    }
    return {**info, **changes}


def test_to_grid_cuts_rows_and_applies_rescale():
    assert to_grid(ct_info()).tolist() == [[-1024, 0], [40, 1024]]


def test_to_grid_rejects_compressed_images():
    with pytest.raises(UnsupportedImageError):
        to_grid(ct_info(transfer_syntax_uid="1.2.840.10008.1.2.4.50"))


def test_to_grey_soft_tissue_window():
    # soft tissue window: -160 and below -> black, 240 and above -> white
    grid = np.array([[-1000.0, 40.0], [240.0, 1000.0]])
    assert to_grey(grid, "soft_tissue").tolist() == [[0, 127], [255, 255]]


def test_to_png_writes_a_png():
    png = to_png(np.zeros((2, 2), dtype=np.uint8))
    assert png.startswith(b"\x89PNG")
