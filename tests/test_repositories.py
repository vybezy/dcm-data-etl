from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from repositories import common, imports_repository, settings_repository, stats_repository


def test_get_counts_returns_the_single_row_from_fetch_all():
    counts = {"patients": 1, "studies": 1, "series": 1, "instances": 78,
              "total_file_bytes": 41123456, "total_pixel_bytes": 40894464}

    with patch("repositories.common.fetch_all", return_value=[counts]) as fetch:
        result = stats_repository.get_counts()

    assert result == counts
    sql, params = fetch.call_args.args
    assert params == ()
    for name in counts:
        assert f"AS {name}" in sql


def test_save_all_upserts_every_setting():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    with patch("repositories.settings_repository.db_connection") as mock_db:
        mock_db.return_value.__enter__.return_value = conn
        settings_repository.save_all({"workers": "4", "store_pixel_data": "true"})

    sql, rows = cur.executemany.call_args.args
    assert "ON CONFLICT (key) DO UPDATE" in sql
    assert rows == [("workers", "4"), ("store_pixel_data", "true")]


def test_fetch_all_maps_rows_by_column_name():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.description = [SimpleNamespace(name="file_id"), SimpleNamespace(name="instance_number")]
    cur.fetchall.return_value = [(10, 1), (11, 2)]

    with patch("repositories.common.db_connection") as mock_db:
        mock_db.return_value.__enter__.return_value = conn
        result = common.fetch_all("SELECT file_id, instance_number FROM dicom_instances", ())

    assert result == [
        {"file_id": 10, "instance_number": 1},
        {"file_id": 11, "instance_number": 2},
    ]


def test_list_sessions_newest_first_with_limit():
    with patch("repositories.common.fetch_all", return_value=[]) as fetch:
        imports_repository.list_sessions(5)

    sql, params = fetch.call_args.args
    assert "ORDER BY s.logses_id DESC LIMIT %s" in sql
    assert params == (5,)
