"""Tests that setup writes configurable DB connection settings into odoo.conf."""

from pathlib import Path

from odoo_dev.commands.setup import _setup_odoo_config
from odoo_dev.config import ProjectConfig


def _make_cfg(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        project_dir=tmp_path,
        script_dir=tmp_path / ".odoo-deploy",
        odoo_version="19.0",
        python_version="3.12",
        project_name="test-project",
    )


class TestSetupOdooConfigDb:
    def test_defaults_to_socket_odoo_role(self, tmp_path: Path, monkeypatch):
        for var in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD"):
            monkeypatch.delenv(var, raising=False)
        _setup_odoo_config(_make_cfg(tmp_path))
        conf = (tmp_path / "conf" / "odoo.conf").read_text()
        assert "db_user = odoo" in conf
        assert "db_password = odoo" in conf
        # No host/port => local socket (matches prior behavior)
        assert "db_host" not in conf
        assert "db_port" not in conf

    def test_honors_db_env_vars(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("DB_HOST", "db.example.com")
        monkeypatch.setenv("DB_PORT", "5544")
        monkeypatch.setenv("DB_USER", "appuser")
        monkeypatch.setenv("DB_PASSWORD", "secret")
        _setup_odoo_config(_make_cfg(tmp_path))
        conf = (tmp_path / "conf" / "odoo.conf").read_text()
        assert "db_host = db.example.com" in conf
        assert "db_port = 5544" in conf
        assert "db_user = appuser" in conf
        assert "db_password = secret" in conf
