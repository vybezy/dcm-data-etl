"""rebuilds a picture from the stored pixel bytes: bytes -> grid -> grey shades -> png."""

from io import BytesIO

import numpy as np
from PIL import Image

from repositories import image_repository
from services.errors import NotFoundError, UnsupportedImageError

# (center, width) in hounsfield units: standard ct presets.
# the window decides which values become black (below) and white (above)
WINDOWS = {
    "lung": (-600, 1500),
    "soft_tissue": (40, 400),
    "bone": (400, 1800),
}

# uncompressed little endian: the stored bytes are the pixel numbers themselves
RAW_SYNTAXES = {"1.2.840.10008.1.2", "1.2.840.10008.1.2.1", None}


def get_png(file_id: int, window: str) -> bytes:
    info = image_repository.get_pixel_data(file_id)   # step 1: read the bytes
    if info is None:
        raise NotFoundError(f"no pixel data stored for instance {file_id}")

    grid = to_grid(info)                               # step 2: bytes -> grid of numbers
    grey = to_grey(grid, window)                       # step 3: numbers -> grey shades

    if info["photometric_interpretation"] == "MONOCHROME1":
        grey = 255 - grey   # this type stores bright as low numbers, so flip it

    return to_png(grey)                                # step 4: grid -> png picture


def to_grid(info: dict) -> np.ndarray:
    if info["transfer_syntax_uid"] not in RAW_SYNTAXES:
        raise UnsupportedImageError("compressed images are not supported")
    if (info["samples_per_pixel"] or 1) != 1 or info["bits_allocated"] not in (8, 16):
        raise UnsupportedImageError("only grayscale 8 or 16 bit images are supported")

    # how to read the bytes: "<" little endian, "i" signed / "u" unsigned, 1 or 2 bytes each
    kind = "i" if info["pixel_representation"] == 1 else "u"
    dtype = f"<{kind}{info['bits_allocated'] // 8}"
    numbers = np.frombuffer(info["pixel_data"], dtype=dtype)

    rows, columns = info["rows"], info["columns"]
    if numbers.size < rows * columns:
        raise UnsupportedImageError("stored pixel data is shorter than rows x columns")

    # cut the long line of numbers into rows (multi-frame files: first frame only)
    grid = numbers[:rows * columns].reshape(rows, columns)

    # stored numbers -> real values (hounsfield units for ct)
    slope = info["rescale_slope"] or 1.0
    intercept = info["rescale_intercept"] or 0.0
    return grid * slope + intercept


def to_grey(grid: np.ndarray, window: str) -> np.ndarray:
    if window == "auto":
        low, high = grid.min(), grid.max()   # darkest pixel -> black, brightest -> white
    else:
        center, width = WINDOWS[window]
        low, high = center - width / 2, center + width / 2

    if high <= low:   # a completely flat image would divide by zero
        return np.zeros(grid.shape, dtype=np.uint8)

    # low and below -> 0 (black), high and above -> 255 (white), evenly spread in between
    scaled = np.clip((grid - low) / (high - low), 0, 1) * 255
    return scaled.astype(np.uint8)


def to_png(grey: np.ndarray) -> bytes:
    buffer = BytesIO()   # a file that lives in memory, so nothing touches the disk
    Image.fromarray(grey).save(buffer, format="PNG")
    return buffer.getvalue()
