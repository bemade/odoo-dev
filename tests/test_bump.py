"""Tests for the `bump` command and its manifest helpers."""

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from odoo_dev.cli import app
from odoo_dev.utils.manifest import bump_version_string, read_version, set_version

runner = CliRunner()


@pytest.mark.parametrize(
    "version,level,expected",
    [
        ("19.0.1.2.3", "patch", "19.0.1.2.4"),
        ("19.0.1.2.3", "minor", "19.0.1.3.0"),
        ("19.0.1.2.3", "major", "19.0.2.0.0"),
        ("1.0.0", "patch", "1.0.1"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
    ],
)
def test_bump_version_string(version, level, expected):
    assert bump_version_string(version, level) == expected


def test_minor_needs_three_segments():
    with pytest.raises(ValueError):
        bump_version_string("19.0", "minor")


def test_read_set_roundtrip():
    text = "{\n 'name': 'Foo',\n 'version': '19.0.1.0.0',\n}\n"
    assert read_version(text) == "19.0.1.0.0"
    assert read_version(set_version(text, "19.0.1.0.1")) == "19.0.1.0.1"


def _make_module(tmp_path: Path, version: str) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    mod = tmp_path / "addons" / "acme"
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text(
        "{\n 'name': 'Acme',\n 'version': '%s',\n}\n" % version
    )
    return mod


def test_bump_command_patch(tmp_path):
    mod = _make_module(tmp_path, "19.0.1.0.0")
    result = runner.invoke(app, ["bump", str(mod)])
    assert result.exit_code == 0
    assert read_version((mod / "__manifest__.py").read_text()) == "19.0.1.0.1"


def test_bump_command_rejects_bad_level(tmp_path):
    mod = _make_module(tmp_path, "19.0.1.0.0")
    result = runner.invoke(app, ["bump", str(mod), "nonsense"])
    assert result.exit_code != 0
