from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from repositories import browse_repository, settings_repository, stats_repository


def test_get_counts_maps_row_to_dict():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (1, 1, 1, 78, 41123456, 40894464)

    with patch("repositories.stats_repository.db_connection") as mock_db:
        mock_db.return_value.__enter__.return_value = conn
        result = stats_repository.get_counts()

    assert result == {
        "patients": 1,
        "studies": 1,
        "series": 1,
        "instances": 78,
        "total_file_bytes": 41123456,
        "total_pixel_bytes": 40894464,
    }


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

    with patch("repositories.browse_repository.db_connection") as mock_db:
        mock_db.return_value.__enter__.return_value = conn
        result = browse_repository.list_instances(5)

    assert result == [
        {"file_id": 10, "instance_number": 1},
        {"file_id": 11, "instance_number": 2},
    ]
