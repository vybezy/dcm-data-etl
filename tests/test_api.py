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


# settings
VALID_SETTINGS = {
    "min_file_size": 102400,
    "max_file_size": 103809024,
    "max_file_age_months": 1200,
    "workers": 4,
    "store_pixel_data": False,
}


def test_get_settings_fills_missing_keys_with_defaults():
    with patch("repositories.settings_repository.get_all", return_value={"workers": "8"}):
        response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "min_file_size": 102400,
        "max_file_size": 103809024,
        "max_file_age_months": 1200,
        "workers": 8,
        "store_pixel_data": True,
    }


def test_put_settings_saves_values_as_text():
    with patch("repositories.settings_repository.save_all") as mock_save:
        response = client.put("/api/settings", json=VALID_SETTINGS)

    assert response.status_code == 200
    assert response.json() == VALID_SETTINGS
    mock_save.assert_called_once_with({
        "min_file_size": "102400",
        "max_file_size": "103809024",
        "max_file_age_months": "1200",
        "workers": "4",
        "store_pixel_data": "false",
    })


def test_put_settings_rejects_max_below_min():
    bad = {**VALID_SETTINGS, "max_file_size": 1000}

    with patch("repositories.settings_repository.save_all") as mock_save:
        response = client.put("/api/settings", json=bad)

    assert response.status_code == 422
    mock_save.assert_not_called()


def test_put_settings_rejects_negative_workers():
    bad = {**VALID_SETTINGS, "workers": -1}

    with patch("repositories.settings_repository.save_all") as mock_save:
        response = client.put("/api/settings", json=bad)

    assert response.status_code == 422
    mock_save.assert_not_called()


# browse
def test_list_patients_masks_names():
    rows = [{"patient_id": 1, "patient_name": "DOE^JOHN", "sex": "M", "study_count": 1}]

    with patch("repositories.browse_repository.list_patients", return_value=rows):
        response = client.get("/api/patients")

    assert response.status_code == 200
    assert response.json()[0]["patient_name"] == "D** J***"


def test_list_patients_rejects_limit_over_200():
    response = client.get("/api/patients?limit=500")
    assert response.status_code == 422


def test_list_studies_returns_404_for_unknown_patient():
    with patch("repositories.browse_repository.patient_exists", return_value=False):
        response = client.get("/api/patients/99/studies")

    assert response.status_code == 404
    assert response.json() == {"detail": "patient 99 not found"}


def test_list_instances_returns_slices():
    slices = [{"file_id": 10, "instance_number": 1, "rows": 512, "columns": 512,
               "file_size_bytes": 527000}]

    with patch("repositories.browse_repository.series_exists", return_value=True), \
         patch("repositories.browse_repository.list_instances", return_value=slices):
        response = client.get("/api/series/1/instances")

    assert response.status_code == 200
    assert response.json() == slices
