import socket
from unittest.mock import MagicMock, patch

import pytest

import database
from utils import ImportOptions, handle_exception


def make_conn(fetchone=None, fetchall=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = fetchall
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


@pytest.fixture
def no_config():
    with patch("database.config", return_value={}):
        yield


# ------------------------- db_connection -------------------------


def test_db_connection_commits_and_closes_on_success(no_config):
    conn, _ = make_conn()
    with patch("database.psycopg2.connect", return_value=conn):
        with database.db_connection() as c:
            assert c is conn

    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    conn.close.assert_called_once()


def test_db_connection_rolls_back_and_closes_on_error(no_config):
    conn, _ = make_conn()
    with patch("database.psycopg2.connect", return_value=conn):
        with pytest.raises(RuntimeError):
            with database.db_connection():
                raise RuntimeError("query failed")

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    conn.close.assert_called_once()


# ------------------------- helpers use it -------------------------


def test_create_import_session_returns_id_and_closes(no_config):
    conn, cur = make_conn(fetchone=(17,))
    with patch("database.psycopg2.connect", return_value=conn):
        assert database.create_import_session() == 17

    machine_id = cur.execute.call_args[0][1][0]
    assert socket.gethostname() in machine_id
    conn.close.assert_called_once()


def test_create_import_session_survives_unresolvable_hostname(no_config):
    conn, cur = make_conn(fetchone=(1,))
    with patch("database.psycopg2.connect", return_value=conn), \
         patch("database.socket.gethostbyname", side_effect=socket.gaierror("no dns")):
        database.create_import_session()

    assert "(unknown)" in cur.execute.call_args[0][1][0]


def test_load_settings_returns_dict_and_closes(no_config):
    conn, _ = make_conn(fetchall=[("workers", "4"), ("min_file_size", "100")])
    with patch("database.psycopg2.connect", return_value=conn):
        settings = database.load_settings_from_db()

    assert settings == {"workers": "4", "min_file_size": "100"}
    conn.close.assert_called_once()


def test_handle_exception_closes_its_db_connection(no_config):
    conn, _ = make_conn()
    options = ImportOptions(
        base_folder=".", min_size=1, max_size=10, subject_min_length=2,
        max_file_age_months=1, workers=0, session_id=5,
    )
    with patch("database.psycopg2.connect", return_value=conn), \
         patch("database.log_db_event") as log_event, \
         patch("utils.pretty_log"), patch("utils.logger"):
        try:
            raise ValueError("boom")
        except ValueError as e:
            handle_exception(e, options, file_path="a.dcm", level="ERROR")

    log_event.assert_called_once()
    conn.close.assert_called_once()


def test_log_db_event_survives_unknown_caller_module():
    conn, cur = make_conn()
    options = ImportOptions(
        base_folder=".", min_size=1, max_size=10, subject_min_length=2,
        max_file_age_months=1, workers=0, session_id=5,
    )
    with patch("database.inspect.getmodule", return_value=None):
        database.log_db_event(conn, options, "a.dcm", "INFO", "msg")

    params = cur.execute.call_args[0][1]
    assert params[5] == "unknown"  # log_module
