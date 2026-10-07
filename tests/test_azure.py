from unittest.mock import MagicMock, patch

import utils


def test_azure_download_without_connection_string_logs_and_skips(monkeypatch, tmp_path):
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    with patch("utils.logger") as log, patch("utils.BlobServiceClient") as client:
        assert utils.download_dicom_from_azure(str(tmp_path)) == str(tmp_path)

    client.from_connection_string.assert_not_called()
    log.info.assert_called_once()
    assert "No AZURE_STORAGE_CONNECTION_STRING" in log.info.call_args[0][0]


def test_azure_download_failure_is_logged_as_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "dummy")
    with patch("utils.logger") as log, \
         patch("utils.BlobServiceClient.from_connection_string", side_effect=ValueError("bad string")):
        utils.download_dicom_from_azure(str(tmp_path))

    log.warning.assert_called_once()
    assert capsys.readouterr().out == ""  # nothing printed outside the logger


def test_azure_download_saves_new_blobs_and_skips_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "dummy")
    (tmp_path / "old.dcm").write_bytes(b"already here")
    container = MagicMock()
    container.list_blobs.return_value = [MagicMock(), MagicMock()]
    container.list_blobs.return_value[0].name = "folder/new.dcm"
    container.list_blobs.return_value[1].name = "old.dcm"
    container.download_blob.return_value.readall.return_value = b"new data"

    with patch("utils.BlobServiceClient.from_connection_string") as from_cs, patch("utils.logger"):
        from_cs.return_value.get_container_client.return_value = container
        utils.download_dicom_from_azure(str(tmp_path))

    assert (tmp_path / "new.dcm").read_bytes() == b"new data"
    assert (tmp_path / "old.dcm").read_bytes() == b"already here"
    container.download_blob.assert_called_once_with("folder/new.dcm")
