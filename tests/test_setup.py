"""Tests for setup command utilities."""

from pathlib import Path
from unittest.mock import patch

from odoo_dev.commands.setup import _clean, _update_env_file


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


class TestClean:
    """Test _clean function."""

    def test_clean_removes_directories(self, tmp_path: Path):
        """Verify _clean removes expected directories."""
        # Create directories that _clean should remove
        for name in ["odoo", "enterprise", "design-themes", "industry", ".venv"]:
            (tmp_path / name).mkdir()

        # Mock load_config to return our tmp_path as project_dir
        mock_cfg = type("Config", (), {"project_dir": tmp_path})()
        with patch("odoo_dev.commands.setup.load_config", return_value=mock_cfg):
            _clean()

        # Verify all directories were removed
        for name in ["odoo", "enterprise", "design-themes", "industry", ".venv"]:
            assert not (tmp_path / name).exists(), f"{name} should be removed"

    def test_clean_ignores_missing_directories(self, tmp_path: Path):
        """Verify _clean doesn't fail if directories don't exist."""
        # Only create some directories
        (tmp_path / "odoo").mkdir()

        mock_cfg = type("Config", (), {"project_dir": tmp_path})()
        with patch("odoo_dev.commands.setup.load_config", return_value=mock_cfg):
            _clean()  # Should not raise

        assert not (tmp_path / "odoo").exists()
