from unittest.mock import MagicMock, patch

import utils

URL = "https://demo.blob.core.windows.net/raw-dicom-files"


def fake_container(*names):
    container = MagicMock()
    blobs = [MagicMock() for _ in names]
    for blob, name in zip(blobs, names):
        blob.name = name
    container.list_blobs.return_value = blobs
    container.download_blob.return_value.readall.return_value = b"new data"
    return container


def test_azure_download_without_container_url_logs_and_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONTAINER_URL", "")
    with patch("utils.logger") as log, patch("utils.ContainerClient") as client:
        assert utils.download_dicom_from_azure(str(tmp_path)) == str(tmp_path)

    client.from_container_url.assert_not_called()
    log.info.assert_called_once()
    assert "No AZURE_CONTAINER_URL" in log.info.call_args[0][0]


def test_azure_download_failure_is_logged_as_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AZURE_CONTAINER_URL", URL)
    with patch("utils.logger") as log, \
         patch("utils.ContainerClient.from_container_url", side_effect=ValueError("bad url")):
        utils.download_dicom_from_azure(str(tmp_path))

    log.warning.assert_called_once()
    assert capsys.readouterr().out == ""  # nothing printed outside the logger


def test_azure_download_saves_new_blobs_and_skips_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONTAINER_URL", URL)
    (tmp_path / "old.dcm").write_bytes(b"already here")
    container = fake_container("folder/new.dcm", "old.dcm")

    with patch("utils.ContainerClient.from_container_url", return_value=container), \
         patch("utils.logger"):
        utils.download_dicom_from_azure(str(tmp_path))

    assert (tmp_path / "new.dcm").read_bytes() == b"new data"
    assert (tmp_path / "old.dcm").read_bytes() == b"already here"
    container.download_blob.assert_called_once_with("folder/new.dcm")


def test_download_new_blobs_returns_how_many_were_downloaded(tmp_path):
    target = tmp_path / "azure"

    with patch("utils.ContainerClient.from_container_url",
               return_value=fake_container("a.dcm", "b.dcm")) as from_url, \
         patch("utils.logger"):
        assert utils.download_new_blobs(URL, str(target)) == 2

    from_url.assert_called_once_with(URL)
    assert sorted(p.name for p in target.iterdir()) == ["a.dcm", "b.dcm"]


def test_download_new_blobs_lets_errors_through(tmp_path):
    with patch("utils.ContainerClient.from_container_url", side_effect=ValueError("bad")):
        try:
            utils.download_new_blobs(URL, str(tmp_path))
        except ValueError:
            return

    raise AssertionError("expected ValueError")


def test_container_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("AZURE_CONTAINER_URL", f"  {URL}  ")
    assert utils.azure_container_url() == URL
