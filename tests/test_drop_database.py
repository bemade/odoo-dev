"""Integration tests for _drop_database.

These tests verify that test databases are actually dropped after a test run.
Requires a local PostgreSQL instance accessible via peer authentication.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest


def _pg_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a PostgreSQL command using peer auth on the local socket."""
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _db_exists(db_name: str) -> bool:
    result = _pg_run(["psql", "-d", "postgres", "-tAc",
                       f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"])
    return result.stdout.strip() == "1"


def _create_db(db_name: str) -> None:
    result = _pg_run(["createdb", db_name])
    assert result.returncode == 0, f"createdb failed: {result.stderr}"


def _drop_db_force(db_name: str) -> None:
    """Forcefully drop a database (for test cleanup)."""
    _pg_run(["psql", "-d", "postgres", "-c",
             f"DROP DATABASE IF EXISTS \"{db_name}\" WITH (FORCE)"])


@dataclass
class FakeConfig:
    """Minimal config to satisfy _drop_database's interface."""
    project_dir: Path
    venv_path: Path
    odoo_bin: Path
    config_file: Path


def _make_config(tmp_path: Path) -> FakeConfig:
    """Create a fake config with an odoo.conf using peer auth.

    Sets up a real python symlink but a fake odoo-bin that always exits 1,
    so the odoo-bin drop method fails cleanly (nonzero exit) and the
    dropdb fallback path is exercised — matching real-world behavior where
    'odoo-bin db drop' fails.
    """
    conf = tmp_path / "conf"
    conf.mkdir()
    config_file = conf / "odoo.conf"
    # Use peer auth (no password, local socket) matching the test environment
    config_file.write_text(
        "[options]\n"
        "db_host = /var/run/postgresql\n"
        "db_port = 5432\n"
        f"db_user = {subprocess.run(['whoami'], capture_output=True, text=True).stdout.strip()}\n"
        "db_password =\n"
    )
    # Create a venv with a real python and a fake odoo-bin that always fails
    venv_path = tmp_path / ".venv"
    venv_path.mkdir()
    bin_dir = venv_path / "bin"
    bin_dir.mkdir()
    import sys
    (bin_dir / "python").symlink_to(sys.executable)

    fake_odoo_bin = tmp_path / "odoo-bin"
    fake_odoo_bin.write_text("#!/usr/bin/env python3\nimport sys; sys.exit(1)\n")
    fake_odoo_bin.chmod(0o755)

    return FakeConfig(
        project_dir=tmp_path,
        venv_path=venv_path,
        odoo_bin=fake_odoo_bin,
        config_file=config_file,
    )


@pytest.mark.slow
class TestDropDatabase:
    """Verify _drop_database actually removes the database."""

    def _unique_db(self) -> str:
        return f"test_odoodev_{int(time.time() * 1000)}"

    def test_drop_removes_database(self, tmp_path: Path):
        """Basic case: database with no active connections is dropped."""
        from odoo_dev.commands.run import _drop_database

        db_name = self._unique_db()
        cfg = _make_config(tmp_path)

        _create_db(db_name)
        assert _db_exists(db_name), "Precondition: database should exist"

        try:
            _drop_database(cfg, db_name)
            assert not _db_exists(db_name), (
                f"Database {db_name} still exists after _drop_database!"
            )
        finally:
            _drop_db_force(db_name)

    def test_drop_works_when_venv_missing(self, tmp_path: Path):
        """When venv python doesn't exist, should fall back to dropdb
        instead of crashing with FileNotFoundError."""
        from odoo_dev.commands.run import _drop_database

        db_name = self._unique_db()
        cfg = _make_config(tmp_path)
        # Remove the python symlink to simulate missing venv
        (cfg.venv_path / "bin" / "python").unlink()

        _create_db(db_name)
        assert _db_exists(db_name), "Precondition: database should exist"

        try:
            _drop_database(cfg, db_name)
            assert not _db_exists(db_name), (
                f"Database {db_name} still exists after _drop_database!"
            )
        finally:
            _drop_db_force(db_name)

    def test_drop_removes_database_with_active_connections(self, tmp_path: Path):
        """Simulates a lingering Odoo worker holding a connection open.

        This is the primary failure mode: dropdb refuses to drop a database
        that has active connections, and _drop_database doesn't terminate
        them first.
        """
        from odoo_dev.commands.run import _drop_database

        db_name = self._unique_db()
        cfg = _make_config(tmp_path)

        _create_db(db_name)
        assert _db_exists(db_name), "Precondition: database should exist"

        # Hold an active connection (simulates a lingering Odoo worker)
        blocker = subprocess.Popen(
            ["psql", "-d", db_name, "-c", "SELECT pg_sleep(300)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Give the connection a moment to establish
            time.sleep(0.5)

            _drop_database(cfg, db_name)
            assert not _db_exists(db_name), (
                f"Database {db_name} still exists after _drop_database! "
                "Active connections were not terminated before drop."
            )
        finally:
            blocker.terminate()
            blocker.wait(timeout=5)
            _drop_db_force(db_name)
