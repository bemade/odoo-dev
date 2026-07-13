"""Tests for ``vendor add`` / ``vendor bump`` (plain pin-and-sync)."""

import subprocess
from pathlib import Path

import pytest

from odoo_dev.vendor.edit import add_addon, bump_addon, EditError
from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.verify import verify


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "src"
    (repo / "shared_addon").mkdir(parents=True)
    (repo / "shared_addon" / "__manifest__.py").write_text(
        "{'name': 'shared', 'version': '18.0.1.0.0'}\n"
    )
    (repo / "shared_addon" / "m.py").write_text("v = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1")
    _git(repo, "tag", "shared_addon/18.0.1.0.0")
    return repo


def _second_version(repo: Path) -> str:
    (repo / "shared_addon" / "m.py").write_text("v = 2\n")
    (repo / "shared_addon" / "__manifest__.py").write_text(
        "{'name': 'shared', 'version': '18.0.1.1.0'}\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v2")
    _git(repo, "tag", "shared_addon/18.0.1.1.0")
    return _git(repo, "rev-parse", "HEAD")


def test_add_by_version_pins_and_materializes(tmp_path):
    repo = _source_repo(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    entry = add_addon(
        proj, "shared_addon", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c"
    )
    assert entry.version == "18.0.1.0.0"
    assert (proj / "vendored" / "shared_addon" / "m.py").read_text() == "v = 1\n"
    lock = Lockfile.load(proj / "addons.lock")
    assert verify(proj, lock, cache_dir=tmp_path / "c") == []


def test_add_duplicate_raises(tmp_path):
    repo = _source_repo(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(
        proj, "shared_addon", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c"
    )
    with pytest.raises(EditError, match="already in addons.lock"):
        add_addon(
            proj,
            "shared_addon",
            str(repo),
            version="18.0.1.0.0",
            cache_dir=tmp_path / "c",
        )


def test_add_requires_a_ref(tmp_path):
    repo = _source_repo(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    with pytest.raises(EditError, match="one of"):
        add_addon(proj, "shared_addon", str(repo), cache_dir=tmp_path / "c")


def test_bump_moves_pin_and_rematerializes(tmp_path):
    repo = _source_repo(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(
        proj, "shared_addon", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c"
    )
    _second_version(repo)

    entry = bump_addon(
        proj, "shared_addon", version="18.0.1.1.0", cache_dir=tmp_path / "c"
    )
    assert entry.version == "18.0.1.1.0"
    assert (proj / "vendored" / "shared_addon" / "m.py").read_text() == "v = 2\n"
    lock = Lockfile.load(proj / "addons.lock")
    assert verify(proj, lock, cache_dir=tmp_path / "c") == []


def _untagged_commit(repo: Path) -> str:
    """A commit that is NOT a version tag (a between-releases pin target)."""
    (repo / "shared_addon" / "m.py").write_text("v = 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v3-untagged")
    return _git(repo, "rev-parse", "HEAD")


def test_bump_by_commit_clears_stale_version(tmp_path):
    """A ``--commit`` bump moves the pin off the tagged commit, so it must clear
    the now-stale ``version`` — otherwise ``vendor check``'s moved-tag tripwire
    (correctly) fails because ``<name>/<old-version>`` no longer resolves to the
    new pin. Regression for the bug where ``bump`` left ``version`` untouched.
    """
    repo = _source_repo(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(
        proj, "shared_addon", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c"
    )
    sha = _untagged_commit(repo)

    entry = bump_addon(proj, "shared_addon", commit=sha, cache_dir=tmp_path / "c")

    assert entry.commit == sha
    assert entry.version is None, "commit bump must clear the stale version tag"
    assert (proj / "vendored" / "shared_addon" / "m.py").read_text() == "v = 3\n"
    lock = Lockfile.load(proj / "addons.lock")
    assert "version" not in (lock.entries["shared_addon"].to_dict())
    # The moved-tag tripwire must NOT fire (it would if version stayed stale).
    assert verify(proj, lock, cache_dir=tmp_path / "c") == []


def test_bump_unknown_addon_raises(tmp_path):
    proj = tmp_path / "client"
    proj.mkdir()
    with pytest.raises(EditError, match="not in addons.lock"):
        bump_addon(proj, "nope", version="1.0.0", cache_dir=tmp_path / "c")
