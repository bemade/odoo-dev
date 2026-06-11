"""Tests for the database preflight connection check."""

import subprocess

import pytest
import typer

from odoo_dev.config import DbConfig
from odoo_dev.preflight import (
    PreflightResult,
    check_db_connection,
    classify_psql_failure,
    psql_argv,
    require_db,
)


class TestPsqlArgv:
    def test_includes_host_and_port_when_set(self):
        db = DbConfig(host="db.example.com", port="5544", user="appuser")
        argv = psql_argv(db, dbname="postgres", sql="SELECT 1")
        assert "-w" in argv  # never prompt for a password (non-interactive)
        assert "-h" in argv and "db.example.com" in argv
        assert "-p" in argv and "5544" in argv
        assert argv[:1] == ["psql"]
        assert "-U" in argv and "appuser" in argv
        assert "-d" in argv and "postgres" in argv

    def test_omits_host_and_port_for_socket(self):
        # No host/port => libpq local socket, same as odoo-bin with no db_host
        db = DbConfig(user="odoo")
        argv = psql_argv(db)
        assert "-h" not in argv
        assert "-p" not in argv
        assert "-U" in argv and "odoo" in argv


class TestClassifyPsqlFailure:
    def test_role_missing(self):
        assert (
            classify_psql_failure(2, 'FATAL:  role "odoo" does not exist')
            == "role_missing"
        )

    def test_database_missing(self):
        assert (
            classify_psql_failure(2, 'FATAL:  database "postgres" does not exist')
            == "db_missing"
        )

    def test_password_auth(self):
        assert (
            classify_psql_failure(
                2, 'FATAL:  password authentication failed for user "odoo"'
            )
            == "auth"
        )

    def test_peer_auth(self):
        assert (
            classify_psql_failure(
                2, 'FATAL:  Peer authentication failed for user "odoo"'
            )
            == "auth"
        )

    def test_server_unreachable_tcp(self):
        assert (
            classify_psql_failure(2, "could not connect to server: Connection refused")
            == "unreachable"
        )

    def test_server_unreachable_socket(self):
        msg = "could not connect to server: No such file or directory\n\tIs the server running locally..."
        assert classify_psql_failure(2, msg) == "unreachable"

    def test_unknown(self):
        assert classify_psql_failure(2, "some other weird error") == "unknown"


class _FakeProc:
    def __init__(self, returncode: int, stderr: str = "", stdout: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


class TestCheckDbConnection:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc(0, stdout="1"))
        result = check_db_connection(DbConfig(user="odoo"))
        assert result.ok is True
        assert result.category == "ok"

    def test_classifies_failure(self, monkeypatch):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: _FakeProc(2, stderr='FATAL:  role "odoo" does not exist'),
        )
        result = check_db_connection(DbConfig(user="odoo"))
        assert result.ok is False
        assert result.category == "role_missing"

    def test_client_missing(self, monkeypatch):
        def _raise(*a, **k):
            raise FileNotFoundError("psql")

        monkeypatch.setattr(subprocess, "run", _raise)
        result = check_db_connection(DbConfig())
        assert result.ok is False
        assert result.category == "client_missing"


class TestRequireDb:
    def test_passes_when_ok(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "odoo_dev.preflight.check_db_connection",
            lambda db, dbname="postgres": PreflightResult(True, "ok", ""),
        )
        # cfg only needs a .config_file attribute
        cfg = type("Cfg", (), {"config_file": tmp_path / "odoo.conf"})()
        require_db(cfg)  # must not raise

    def test_exits_on_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "odoo_dev.preflight.check_db_connection",
            lambda db, dbname="postgres": PreflightResult(False, "unreachable", "boom"),
        )
        cfg = type("Cfg", (), {"config_file": tmp_path / "odoo.conf"})()
        with pytest.raises(typer.Exit):
            require_db(cfg)
