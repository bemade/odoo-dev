"""Tests for filestore cleanup on the dropdb fallback path."""

from pathlib import Path

import pytest

from odoo_dev.commands.run import _drop_filestore
from odoo_dev.config import ProjectConfig


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


class TestDropFilestore:
    """The dropdb fallback must clean up the filestore odoo-bin would have."""

    def test_removes_filestore_for_dropped_db(self, cfg):
        cfg.config_file.write_text(f"[options]\ndata_dir = {cfg.data_dir}\n")
        filestore = cfg.data_dir / "filestore" / "test_123"
        filestore.mkdir(parents=True)
        (filestore / "blob").write_text("x")

        _drop_filestore(cfg, "test_123")

        assert not filestore.exists()

    def test_leaves_other_filestores_alone(self, cfg):
        cfg.config_file.write_text(f"[options]\ndata_dir = {cfg.data_dir}\n")
        keep = cfg.data_dir / "filestore" / "other_db"
        keep.mkdir(parents=True)

        _drop_filestore(cfg, "test_123")

        assert keep.exists()

    def test_missing_filestore_is_not_an_error(self, cfg):
        cfg.config_file.write_text(f"[options]\ndata_dir = {cfg.data_dir}\n")

        _drop_filestore(cfg, "test_123")

