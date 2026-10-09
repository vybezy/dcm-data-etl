import os
from unittest.mock import patch

import pytest

import main
from config import DEFAULT_SETTINGS


# ------------------------- resolve_input -------------------------


def test_resolve_input_folder(tmp_path):
    base, files = main.resolve_input(str(tmp_path))
    assert base == os.path.realpath(str(tmp_path))
    assert files is None  # None = scan the whole folder


def test_resolve_input_single_file(tmp_path):
    f = tmp_path / "a.dcm"
    f.write_bytes(b"x")
    base, files = main.resolve_input(str(f))
    assert base == os.path.realpath(str(tmp_path))
    assert files == [str(f)]


def test_resolve_input_wildcard(tmp_path):
    for name in ("a.dcm", "b.dcm", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    base, files = main.resolve_input(str(tmp_path / "*.dcm"))
    assert base == os.path.realpath(str(tmp_path))
    assert [os.path.basename(f) for f in files] == ["a.dcm", "b.dcm"]


@pytest.mark.parametrize("pattern", ["does_not_exist", "nothing_here_*.dcm"])
def test_resolve_input_missing_path(tmp_path, pattern):
    assert main.resolve_input(str(tmp_path / pattern)) == (None, None)


# ------------------------- main() -------------------------


@pytest.fixture
def fake_pipeline():
    """Replaces every database / cloud call made by main()."""
    with patch("main.db_init") as db_init, \
         patch("main.create_import_session", return_value=1), \
         patch("main.load_settings_from_db", return_value={"workers": "4"}), \
         patch("main.download_dicom_from_azure"), \
         patch("main.scan_and_import", return_value=[{"status": "inserted"}]) as scan:
        yield db_init, scan


def test_main_missing_path_returns_2_and_touches_nothing(tmp_path, fake_pipeline):
    db_init, scan = fake_pipeline
    assert main.main([str(tmp_path / "missing")]) == 2
    db_init.assert_not_called()
    scan.assert_not_called()


def test_main_does_not_reset_tables_by_default(tmp_path, fake_pipeline, monkeypatch):
    monkeypatch.delenv("RESET_TABLES", raising=False)
    monkeypatch.setattr("main.env_flag", lambda name: False)  # ignore a local .env
    db_init, _ = fake_pipeline
    assert main.main([str(tmp_path)]) == 0
    assert db_init.call_args.kwargs["reset_tables"] is False


def test_main_reset_flag_resets_tables(tmp_path, fake_pipeline):
    db_init, _ = fake_pipeline
    main.main([str(tmp_path), "--reset"])
    assert db_init.call_args.kwargs["reset_tables"] is True


def test_main_passes_cli_options_through(tmp_path, fake_pipeline):
    _, scan = fake_pipeline
    main.main([str(tmp_path), "--workers", "0", "--dry-run"])
    options = scan.call_args[0][1]
    assert options.workers == 0
    assert options.dry_run is True


def test_main_single_file_is_imported_once(tmp_path, fake_pipeline):
    _, scan = fake_pipeline
    f = tmp_path / "a.dcm"
    f.write_bytes(b"x")
    main.main([str(f)])
    scan.assert_called_once()
    assert scan.call_args.kwargs["file_list"] == [str(f)]


def test_main_returns_1_when_a_file_errors(tmp_path, fake_pipeline):
    _, scan = fake_pipeline
    scan.return_value = [{"status": "inserted"}, {"status": "error"}]
    assert main.main([str(tmp_path)]) == 1


def test_main_rejections_are_not_errors(tmp_path, fake_pipeline):
    _, scan = fake_pipeline
    scan.return_value = [{"status": "duplicate"}, {"status": "skipped"}, {"status": "invalid"}]
    assert main.main([str(tmp_path)]) == 0


def test_main_falls_back_to_default_settings(tmp_path, fake_pipeline):
    """Keys missing from the database use DEFAULT_SETTINGS, not other hard-coded numbers."""
    _, scan = fake_pipeline
    with patch("main.load_settings_from_db", return_value={}):
        main.main([str(tmp_path)])
    options = scan.call_args[0][1]
    assert options.min_size == int(DEFAULT_SETTINGS["min_file_size"])
    assert options.max_size == int(DEFAULT_SETTINGS["max_file_size"])
    assert options.max_file_age_months == int(DEFAULT_SETTINGS["max_file_age_months"])
    assert options.workers == int(DEFAULT_SETTINGS["workers"])


def test_main_database_settings_override_defaults(tmp_path, fake_pipeline):
    _, scan = fake_pipeline
    with patch("main.load_settings_from_db", return_value={"min_file_size": "5"}):
        main.main([str(tmp_path)])
    assert scan.call_args[0][1].min_size == 5


def test_main_does_not_reset_when_env_flag_is_false(tmp_path, fake_pipeline, monkeypatch):
    monkeypatch.setenv("RESET_TABLES", "false")
    db_init, _ = fake_pipeline
    main.main([str(tmp_path)])
    assert db_init.call_args.kwargs["reset_tables"] is False


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_main_resets_when_env_flag_is_set(tmp_path, fake_pipeline, monkeypatch, value):
    monkeypatch.setenv("RESET_TABLES", value)
    db_init, _ = fake_pipeline
    main.main([str(tmp_path)])
    assert db_init.call_args.kwargs["reset_tables"] is True


def test_reset_flag_wins_even_when_env_flag_is_false(tmp_path, fake_pipeline, monkeypatch):
    monkeypatch.setenv("RESET_TABLES", "false")
    db_init, _ = fake_pipeline
    main.main([str(tmp_path), "--reset"])
    assert db_init.call_args.kwargs["reset_tables"] is True
