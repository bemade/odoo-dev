"""Tests for the project-local data_dir and manifest dependency install."""

from pathlib import Path
from unittest.mock import patch

import pytest

from odoo_dev.commands.setup import (
    _ensure_data_dir_configured,
    _gitignore_data_dir,
    _install_manifest_python_deps,
    _manifest_test_deps,
    _setup_odoo_config,
)
from odoo_dev.config import DEFAULT_ODOO_DATA_DIR, ProjectConfig, read_data_dir


@pytest.fixture
def cfg(tmp_path: Path) -> ProjectConfig:
    (tmp_path / "conf").mkdir()
    return ProjectConfig(
        project_dir=tmp_path,
        script_dir=tmp_path / ".odoo-deploy",
        odoo_version="19.0",
        python_version="3.12",
        project_name="proj",
    )


def _write_manifest(addons_dir: Path, name: str, body: str) -> None:
    mod = addons_dir / name
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text(body)


class TestDataDirConfig:
    def test_generated_config_sets_project_local_data_dir(self, cfg):
        _setup_odoo_config(cfg)

        content = cfg.config_file.read_text()
        assert f"data_dir = {cfg.project_dir / '.odoo-data'}" in content

    def test_generated_config_gitignores_data_dir(self, cfg):
        _setup_odoo_config(cfg)

        assert ".odoo-data/" in (cfg.project_dir / ".gitignore").read_text()

    def test_existing_config_gains_data_dir(self, cfg):
        cfg.config_file.write_text("[options]\nadmin_passwd = admin\n")

        _setup_odoo_config(cfg)

        lines = cfg.config_file.read_text().splitlines()
        assert lines[0] == "[options]"
        assert lines[1] == f"data_dir = {cfg.data_dir}"
        assert "admin_passwd = admin" in lines

    def test_existing_data_dir_is_not_overwritten(self, cfg):
        cfg.config_file.write_text("[options]\ndata_dir = /srv/odoo-data\n")

        _ensure_data_dir_configured(cfg, cfg.config_file)

        assert "/srv/odoo-data" in cfg.config_file.read_text()
        assert str(cfg.data_dir) not in cfg.config_file.read_text()

    def test_gitignore_entry_is_not_duplicated(self, cfg):
        (cfg.project_dir / ".gitignore").write_text(".odoo-data/\n.venv/\n")

        _gitignore_data_dir(cfg)

        content = (cfg.project_dir / ".gitignore").read_text()
        assert content.count(".odoo-data/") == 1


class TestReadDataDir:
    def test_reads_configured_value(self, tmp_path: Path):
        conf = tmp_path / "odoo.conf"
        conf.write_text("[options]\ndata_dir = /srv/odoo-data\n")

        assert read_data_dir(conf) == Path("/srv/odoo-data")

    def test_falls_back_to_odoo_default(self, tmp_path: Path):
        conf = tmp_path / "odoo.conf"
        conf.write_text("[options]\nadmin_passwd = admin\n")

        assert read_data_dir(conf) == DEFAULT_ODOO_DATA_DIR

    def test_missing_file_falls_back_to_odoo_default(self, tmp_path: Path):
        assert read_data_dir(tmp_path / "nope.conf") == DEFAULT_ODOO_DATA_DIR


class TestManifestTestDeps:
    def test_collects_test_external_dependencies(self, tmp_path: Path):
        _write_manifest(
            tmp_path,
            "mod_a",
            "{'name': 'A', 'test_external_dependencies': {'python': ['pdfminer.six']}}",
        )

        assert _manifest_test_deps(tmp_path) == {"pdfminer.six"}

    def test_ignores_runtime_dependencies(self, tmp_path: Path):
        _write_manifest(
            tmp_path,
            "mod_a",
            "{'name': 'A', 'external_dependencies': {'python': ['openpyxl']}}",
        )

        assert _manifest_test_deps(tmp_path) == set()

    def test_skips_unparseable_manifest(self, tmp_path: Path):
        _write_manifest(tmp_path, "mod_a", "{'name': 'A', 'x': undefined_name}")
        _write_manifest(
            tmp_path,
            "mod_b",
            "{'name': 'B', 'test_external_dependencies': {'python': ['freezegun']}}",
        )

        assert _manifest_test_deps(tmp_path) == {"freezegun"}

    def test_missing_dir_is_empty(self, tmp_path: Path):
        assert _manifest_test_deps(tmp_path / "nope") == set()


class TestInstallManifestPythonDeps:
    def test_installs_runtime_and_test_deps_from_both_dirs(self, cfg):
        _write_manifest(
            cfg.addons_dir,
            "mod_a",
            "{'name': 'A', 'test_external_dependencies': {'python': ['freezegun']}}",
        )
        _write_manifest(
            cfg.vendored_dir,
            "mod_b",
            "{'name': 'B', 'test_external_dependencies': {'python': ['pdfminer.six']}}",
        )

        with patch("odoo_dev.commands.setup._manifest_runtime_deps") as runtime:
            runtime.side_effect = [{"openpyxl"}, {"xlsxwriter"}]
            with patch("odoo_dev.commands.setup.subprocess.run") as run:
                run.return_value.returncode = 0
                _install_manifest_python_deps(cfg, ["uv", "pip", "install"])

        installed = set(run.call_args[0][0][3:])
        assert installed == {"openpyxl", "xlsxwriter", "freezegun", "pdfminer.six"}

    def test_no_deps_installs_nothing(self, cfg):
        cfg.addons_dir.mkdir()

        with patch("odoo_dev.commands.setup._manifest_runtime_deps", return_value=set()):
            with patch("odoo_dev.commands.setup.subprocess.run") as run:
                _install_manifest_python_deps(cfg, ["uv", "pip", "install"])

        run.assert_not_called()


class TestAdminPasswd:
    """admin_passwd follows the same .env pattern as the DB settings."""

    def test_local_conf_defaults_to_admin(self, cfg, monkeypatch):
        monkeypatch.delenv("ADMIN_PASSWD", raising=False)

        _setup_odoo_config(cfg)

        assert "admin_passwd = admin\n" in cfg.config_file.read_text()

    def test_local_conf_honours_env(self, cfg, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWD", "s3cret")

        _setup_odoo_config(cfg)

        assert "admin_passwd = s3cret\n" in cfg.config_file.read_text()

    def test_docker_conf_honours_env(self, monkeypatch):
        from odoo_dev.commands.setup import _generate_docker_odoo_conf

        monkeypatch.setenv("ADMIN_PASSWD", "s3cret")

        assert "admin_passwd = s3cret\n" in _generate_docker_odoo_conf()
