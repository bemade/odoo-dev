"""Tests for reading DB connection settings the way odoo-bin will use them."""

from pathlib import Path

from odoo_dev.config import DbConfig, read_db_config


class TestReadDbConfig:
    def test_parses_full_config(self, tmp_path: Path):
        conf = tmp_path / "odoo.conf"
        conf.write_text(
            "[options]\n"
            "db_host = db.example.com\n"
            "db_port = 5544\n"
            "db_user = appuser\n"
            "db_password = secret\n"
            "db_name = mydb\n"
        )
        db = read_db_config(conf)
        assert db == DbConfig(
            host="db.example.com",
            port="5544",
            user="appuser",
            password="secret",
            name="mydb",
        )

    def test_unset_host_port_stay_empty_for_socket(self, tmp_path: Path):
        # odoo-bin with no db_host uses the local socket; preflight must mirror that
        conf = tmp_path / "odoo.conf"
        conf.write_text("[options]\ndb_user = odoo\ndb_password = odoo\n")
        db = read_db_config(conf)
        assert db.host == ""
        assert db.port == ""
        assert db.user == "odoo"
        assert db.password == "odoo"
        assert db.name is None

    def test_defaults_when_file_missing(self, tmp_path: Path):
        db = read_db_config(tmp_path / "nonexistent.conf")
        assert db == DbConfig()
        assert db.user == "odoo"

    def test_handles_whitespace(self, tmp_path: Path):
        conf = tmp_path / "odoo.conf"
        conf.write_text("db_user =   spacey   \ndb_host=nospace\n")
        db = read_db_config(conf)
        assert db.user == "spacey"
        assert db.host == "nospace"
