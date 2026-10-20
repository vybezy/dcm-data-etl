import pytest

from services.browse_service import mask_name


@pytest.mark.parametrize("name, expected", [
    ("DOE^JOHN", "D** J***"),
    ("ANONYMOUS", "A********"),
    ("", ""),
])
def test_mask_name(name, expected):
    assert mask_name(name) == expected
