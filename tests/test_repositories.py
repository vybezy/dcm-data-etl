from unittest.mock import MagicMock, patch

from repositories import stats_repository


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
