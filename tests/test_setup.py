"""Tests for setup command utilities."""

from pathlib import Path

from odoo_dev.commands.setup import _update_env_file


class TestUpdateEnvFile:
    """Test .env file updating."""

    def test_creates_new_env_file(self, tmp_path: Path):
        env_file = tmp_path / ".env"

        _update_env_file(env_file, {"ODOO_VERSION": "18.0", "PYTHON_VERSION": "3.12"})

        assert env_file.exists()
        content = env_file.read_text()
        assert "ODOO_VERSION=18.0" in content
        assert "PYTHON_VERSION=3.12" in content

    def test_updates_existing_env_file(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=hello\nODOO_VERSION=17.0\n")

        _update_env_file(env_file, {"ODOO_VERSION": "18.0"})

        content = env_file.read_text()
        assert "ODOO_VERSION=18.0" in content
        assert "EXISTING_VAR=hello" in content
        # Old version should be replaced
        assert "17.0" not in content

    def test_preserves_other_vars(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("DB_HOST=localhost\nDB_PORT=5432\n")

        _update_env_file(env_file, {"ODOO_VERSION": "18.0"})

        content = env_file.read_text()
        assert "DB_HOST=localhost" in content
        assert "DB_PORT=5432" in content
        assert "ODOO_VERSION=18.0" in content

    def test_skips_comments(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nVAR=value\n")

        _update_env_file(env_file, {"NEW_VAR": "new"})

        content = env_file.read_text()
        assert "NEW_VAR=new" in content
        assert "VAR=value" in content
        # Comments are not preserved (simplification)
