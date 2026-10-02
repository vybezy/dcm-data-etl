import os
import pytest
from processor import is_valid_filename, sanitize_and_validate_path
from utils import ImportErrorWithContext

def test_is_valid_filename():
    # test valid cases
    assert is_valid_filename("Trial01.c3d") is True
    assert is_valid_filename("subject_test-01.c3d") is True
    
    # test invalid cases (special characters)
    assert is_valid_filename("subject@test!#$%.c3d") is False
    
    # test length limits
    assert is_valid_filename("a" * 256 + ".c3d") is False


def test_sanitize_and_validate_path_success(tmp_path):
    base_folder = tmp_path / "data"
    base_folder.mkdir()
    
    safe_file = base_folder / "test.c3d"
    safe_file.write_text("dummy binary data")
    
    # should return real path without raising an exception
    result = sanitize_and_validate_path(str(safe_file), str(base_folder))
    assert result == str(safe_file)


def test_sanitize_and_validate_path_traversal(tmp_path):
    base_folder = tmp_path / "data"
    base_folder.mkdir()
    
    malicious_file = tmp_path / "outside.c3d"
    malicious_file.write_text("malicious data")
    
    # attempt to escape the base folder raises custom exception
    with pytest.raises(ImportErrorWithContext, match="Path traversal or escape detected"):
        sanitize_and_validate_path(str(malicious_file), str(base_folder))