from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_stats_returns_counts():
    fake = {"patients": 1, "studies": 1, "series": 1, "instances": 78,
            "total_file_bytes": 41123456, "total_pixel_bytes": 40894464}

    with patch("repositories.stats_repository.get_counts", return_value=fake):
        response = client.get("/api/stats")

    assert response.status_code == 200
    assert response.json() == fake


def test_unknown_route_returns_404():
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
