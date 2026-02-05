"""Tests for configuration loading."""

import os
from pathlib import Path

import pytest

from odoo_dev.config import ProjectConfig, find_project_root, load_config, load_dotenv


class TestFindProjectRoot:
    def test_finds_git_root(self, tmp_path: Path):
        # Create a git repo structure
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        subdir = tmp_path / "src" / "deep" / "nested"
        subdir.mkdir(parents=True)

        # Should find root from nested directory
        result = find_project_root(subdir)
        assert result == tmp_path

    def test_finds_git_submodule(self, tmp_path: Path):
        # Submodules have a .git file, not a directory
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: ../.git/modules/submodule")
        subdir = tmp_path / "src"
        subdir.mkdir()

        result = find_project_root(subdir)
        assert result == tmp_path

    def test_returns_start_when_no_git(self, tmp_path: Path):
        subdir = tmp_path / "not" / "a" / "repo"
        subdir.mkdir(parents=True)

        # Should return cwd when no .git found
        result = find_project_root(subdir)
        # Returns Path.cwd() when walking up finds nothing
        assert result == Path.cwd()


class TestLoadDotenv:
    def test_loads_env_vars(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_VAR=hello\nANOTHER=world\n")

        # Clear any existing value
        os.environ.pop("TEST_VAR", None)
        os.environ.pop("ANOTHER", None)

        load_dotenv(env_file)

        assert os.environ.get("TEST_VAR") == "hello"
        assert os.environ.get("ANOTHER") == "world"

        # Cleanup
        os.environ.pop("TEST_VAR", None)
        os.environ.pop("ANOTHER", None)

    def test_skips_comments_and_empty_lines(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nVALID=yes\n  # indented comment\n")

        os.environ.pop("VALID", None)

        load_dotenv(env_file)

        assert os.environ.get("VALID") == "yes"
        os.environ.pop("VALID", None)

    def test_does_not_override_existing(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=from_file\n")

        os.environ["EXISTING"] = "already_set"

        load_dotenv(env_file)

        assert os.environ.get("EXISTING") == "already_set"
        os.environ.pop("EXISTING", None)

    def test_missing_file_ok(self, tmp_path: Path):
        # Should not raise
        load_dotenv(tmp_path / "nonexistent")


class TestProjectConfig:
    def test_paths(self, tmp_path: Path):
        cfg = ProjectConfig(
            project_dir=tmp_path,
            script_dir=tmp_path / ".odoo-deploy",
            odoo_version="18.0",
            python_version="3.12",
            project_name="test-project",
        )

        assert cfg.venv_path == tmp_path / ".venv"
        assert cfg.config_file == tmp_path / "conf" / "odoo.conf"
        assert cfg.docker_config_file == tmp_path / ".odoo-deploy" / "odoo.conf"
        assert cfg.odoo_bin == tmp_path / "odoo" / "odoo-bin"
        assert cfg.addons_dir == tmp_path / "addons"


class TestLoadConfig:
    def test_loads_defaults(self, tmp_path: Path, monkeypatch):
        # Create minimal git repo
        (tmp_path / ".git").mkdir()

        # Clear env vars that might interfere
        monkeypatch.delenv("ODOO_VERSION", raising=False)
        monkeypatch.delenv("PYTHON_VERSION", raising=False)

        cfg = load_config(tmp_path)

        assert cfg.project_dir == tmp_path
        assert cfg.odoo_version == "19.0"  # default
        assert cfg.python_version == "3.12"  # default
        assert cfg.project_name == tmp_path.name

    def test_respects_env_file(self, tmp_path: Path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".env").write_text("ODOO_VERSION=17.0\nPYTHON_VERSION=3.11\n")

        monkeypatch.delenv("ODOO_VERSION", raising=False)
        monkeypatch.delenv("PYTHON_VERSION", raising=False)

        cfg = load_config(tmp_path)

        assert cfg.odoo_version == "17.0"
        assert cfg.python_version == "3.11"
