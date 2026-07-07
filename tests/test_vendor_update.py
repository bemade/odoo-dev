"""Tests for ``vendor update`` (the pull side: find + apply newer upstream)."""
import subprocess
from pathlib import Path

from odoo_dev.vendor.edit import add_addon
from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.update import (
    _version_key,
    apply_update,
    find_updates,
    latest_version,
)
from odoo_dev.vendor.verify import verify


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source(tmp_path: Path) -> Path:
    repo = tmp_path / "src"
    (repo / "shared").mkdir(parents=True)
    (repo / "shared" / "__manifest__.py").write_text(
        "{'name': 'shared', 'version': '18.0.1.0.0'}\n"
    )
    (repo / "shared" / "m.py").write_text("v = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1")
    _git(repo, "branch", "-M", "18.0")
    _git(repo, "tag", "shared/18.0.1.0.0")
    return repo


def _cut_version(repo: Path, version: str, val: int) -> str:
    (repo / "shared" / "m.py").write_text(f"v = {val}\n")
    (repo / "shared" / "__manifest__.py").write_text(
        f"{{'name': 'shared', 'version': '{version}'}}\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", version)
    _git(repo, "tag", f"shared/{version}")
    return _git(repo, "rev-parse", "HEAD")


def test_version_key_orders_odoo_versions():
    assert _version_key("18.0.1.10.0") > _version_key("18.0.1.9.0")
    assert _version_key("19.0.1.0.0") > _version_key("18.0.9.9.9")


def test_latest_version_picks_highest_tag(tmp_path):
    repo = _source(tmp_path)
    _cut_version(repo, "18.0.1.1.0", 2)
    _cut_version(repo, "18.0.1.10.0", 3)  # 1.10 > 1.1 numerically
    assert latest_version(str(repo), "shared", tmp_path / "c") == "18.0.1.10.0"


def test_find_updates_version_tracked(tmp_path):
    repo = _source(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(proj, "shared", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c")
    _cut_version(repo, "18.0.1.1.0", 2)

    updates = find_updates(proj, Lockfile.load(proj / "addons.lock"), cache_dir=tmp_path / "c2")
    assert updates == [
        {"name": "shared", "kind": "version", "current": "18.0.1.0.0", "latest": "18.0.1.1.0"}
    ]


def test_find_updates_none_when_current(tmp_path):
    repo = _source(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(proj, "shared", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c")
    # No newer tag cut.
    assert find_updates(proj, Lockfile.load(proj / "addons.lock"), cache_dir=tmp_path / "c2") == []


def test_apply_update_bumps_and_rematerializes(tmp_path):
    repo = _source(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(proj, "shared", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c")
    _cut_version(repo, "18.0.1.1.0", 2)

    lock = Lockfile.load(proj / "addons.lock")
    (u,) = find_updates(proj, lock, cache_dir=tmp_path / "c2")
    apply_update(proj, u, cache_dir=tmp_path / "c2")

    assert (proj / "vendored" / "shared" / "m.py").read_text() == "v = 2\n"
    lock2 = Lockfile.load(proj / "addons.lock")
    assert lock2.entries["shared"].version == "18.0.1.1.0"
    assert verify(proj, lock2, cache_dir=tmp_path / "c3") == []


def test_find_updates_branch_tracked(tmp_path):
    repo = _source(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    # Track the 18.0 branch instead of a version tag.
    add_addon(proj, "shared", str(repo), branch="18.0", cache_dir=tmp_path / "c")
    head = _cut_version(repo, "18.0.1.1.0", 2)  # moves 18.0 HEAD

    updates = find_updates(proj, Lockfile.load(proj / "addons.lock"), cache_dir=tmp_path / "c2")
    assert len(updates) == 1
    assert updates[0]["kind"] == "branch"
    assert updates[0]["commit"] == head


def test_find_updates_skips_bare_commit_pin(tmp_path):
    repo = _source(tmp_path)
    sha = _git(repo, "rev-parse", "HEAD")
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(proj, "shared", str(repo), commit=sha, cache_dir=tmp_path / "c")
    _cut_version(repo, "18.0.1.1.0", 2)
    # A bare-commit pin (no version, no branch) is deliberately fixed.
    assert find_updates(proj, Lockfile.load(proj / "addons.lock"), cache_dir=tmp_path / "c2") == []
