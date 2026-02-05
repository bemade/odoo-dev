"""Tests for database command utilities."""

from pathlib import Path

from odoo_dev.commands.db import _parse_db_config


class TestParseDbConfig:
    def test_parses_full_config(self, tmp_path: Path):
        config_file = tmp_path / "odoo.conf"
        config_file.write_text(
            """[options]
db_host = localhost
db_port = 5432
db_user = myuser
db_password = secret123
admin_passwd = admin
"""
        )

        result = _parse_db_config(config_file)

        assert result["host"] == "localhost"
        assert result["port"] == "5432"
        assert result["user"] == "myuser"
        assert result["password"] == "secret123"

    def test_uses_defaults_for_missing(self, tmp_path: Path):
        config_file = tmp_path / "odoo.conf"
        config_file.write_text("[options]\nadmin_passwd = admin\n")

        result = _parse_db_config(config_file)

        assert result["host"] == "localhost"
        assert result["port"] == "5432"
        assert result["user"] == "odoo"
        assert result["password"] == ""

    def test_handles_whitespace(self, tmp_path: Path):
        config_file = tmp_path / "odoo.conf"
        config_file.write_text("db_user =   spacey_user   \ndb_host=nospaceshost\n")

        result = _parse_db_config(config_file)

        assert result["user"] == "spacey_user"
        assert result["host"] == "nospaceshost"
