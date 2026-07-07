"""Tests for ``vendor develop`` (local dev overlay for a vendored addon).

The overlay lets you edit a vendored addon against a live, writable clone of its
source repo and exercise it inside the client's Odoo, while the committed
``vendored/<addon>`` copy stays byte-for-byte pristine (so ``vendor check`` stays
green and nothing dev-only can leak into a commit).
"""

import subprocess
from pathlib import Path

import pytest

from odoo_dev.vendor.develop import (
    DevelopError,
    develop_state,
    read_addons_path,
    start_develop,
    stop_develop,
)
from odoo_dev.vendor.edit import add_addon


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_repo(tmp_path: Path) -> Path:
    """A source repo with two tagged addons at the repo root."""
    repo = tmp_path / "src"
    (repo / "shared_addon").mkdir(parents=True)
    (repo / "shared_addon" / "__manifest__.py").write_text(
        "{'name': 'shared', 'version': '18.0.1.0.0'}\n"
    )
    (repo / "shared_addon" / "m.py").write_text("v = 1\n")
    (repo / "other_addon").mkdir(parents=True)
    (repo / "other_addon" / "__manifest__.py").write_text(
        "{'name': 'other', 'version': '18.0.1.0.0'}\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1")
    _git(repo, "tag", "shared_addon/18.0.1.0.0")
    _git(repo, "tag", "other_addon/18.0.1.0.0")
    return repo


def _client(tmp_path: Path, repo: Path) -> tuple[Path, Path]:
    """A client project with shared_addon vendored + a minimal odoo.conf."""
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(
        proj, "shared_addon", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c"
    )
    conf = proj / "conf" / "odoo.conf"
    conf.parent.mkdir()
    conf.write_text(
        "[options]\n"
        f"addons_path = {proj / 'addons'},{proj / 'vendored'}\n"
        "admin_passwd = admin\n"
    )
    return proj, conf


def test_start_develop_sets_up_overlay_and_conf(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)

    entry = start_develop(proj, "shared_addon", conf_file=conf)
    dev = proj / ".vendor-dev"

    # A real, writable clone we can commit in.
    assert (Path(entry.repo) / ".git").exists()
    # The overlay exposes exactly the develop-mode addon, via a symlink to the clone.
    link = dev / "overlay" / "shared_addon"
    assert link.is_symlink()
    assert (link / "m.py").read_text() == "v = 1\n"
    assert [p.name for p in (dev / "overlay").iterdir()] == ["shared_addon"]
    # The overlay is first on the addons path, so it shadows vendored/.
    assert read_addons_path(conf)[0] == str(dev / "overlay")
    # The committed vendored copy is untouched.
    assert (proj / "vendored" / "shared_addon" / "m.py").read_text() == "v = 1\n"
    # .vendor-dev/ is gitignored so the overlay/clone can't be committed.
    assert ".vendor-dev/" in (proj / ".gitignore").read_text().splitlines()


def test_start_develop_checks_out_workbranch_at_pin(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)

    entry = start_develop(proj, "shared_addon", conf_file=conf)
    clone = Path(entry.repo)
    assert entry.branch == "vendor-dev/shared_addon"
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "vendor-dev/shared_addon"
    # Editing upstream in the clone does NOT touch the vendored copy.
    (clone / "shared_addon" / "m.py").write_text("v = 99\n")
    assert (proj / "vendored" / "shared_addon" / "m.py").read_text() == "v = 1\n"
    # ...but the overlay (what Odoo loads) reflects the live edit.
    assert (proj / ".vendor-dev" / "overlay" / "shared_addon" / "m.py").read_text() == (
        "v = 99\n"
    )


def test_start_develop_custom_branch(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    entry = start_develop(proj, "shared_addon", branch="feat/x", conf_file=conf)
    assert entry.branch == "feat/x"
    assert _git(Path(entry.repo), "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"


def test_start_unknown_addon_raises(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    with pytest.raises(DevelopError, match="not in addons.lock"):
        start_develop(proj, "nope", conf_file=conf)


def test_start_missing_conf_raises(tmp_path):
    repo = _source_repo(tmp_path)
    proj, _ = _client(tmp_path, repo)
    with pytest.raises(DevelopError, match="setup"):
        start_develop(proj, "shared_addon", conf_file=proj / "conf" / "nope.conf")


def test_start_develop_is_idempotent(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    start_develop(proj, "shared_addon", conf_file=conf)
    start_develop(proj, "shared_addon", conf_file=conf)
    overlay = str(proj / ".vendor-dev" / "overlay")
    assert read_addons_path(conf).count(overlay) == 1
    assert (proj / ".gitignore").read_text().count(".vendor-dev/") == 1


def test_develop_state_lists_active(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    start_develop(proj, "shared_addon", conf_file=conf)
    state = develop_state(proj)
    assert "shared_addon" in state
    assert state["shared_addon"].source == str(repo)


def test_stop_develop_cleans_up_but_keeps_clone(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    entry = start_develop(proj, "shared_addon", conf_file=conf)

    stop_develop(proj, "shared_addon", conf_file=conf)
    dev = proj / ".vendor-dev"
    # Overlay symlink and the (now empty) overlay dir are gone.
    assert not (dev / "overlay" / "shared_addon").is_symlink()
    assert not (dev / "overlay").exists()
    # The conf prepend is removed.
    assert str(dev / "overlay") not in read_addons_path(conf)
    # The clone is preserved — it may hold unpushed work.
    assert Path(entry.repo).exists()
    assert develop_state(proj) == {}


def test_stop_unknown_addon_raises(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    with pytest.raises(DevelopError, match="not in develop mode"):
        stop_develop(proj, "shared_addon", conf_file=conf)


def test_two_addons_share_overlay(tmp_path):
    repo = _source_repo(tmp_path)
    proj, conf = _client(tmp_path, repo)
    add_addon(
        proj, "other_addon", str(repo), version="18.0.1.0.0", cache_dir=tmp_path / "c"
    )
    start_develop(proj, "shared_addon", conf_file=conf)
    start_develop(proj, "other_addon", conf_file=conf)
    dev = proj / ".vendor-dev"
    assert sorted(p.name for p in (dev / "overlay").iterdir()) == [
        "other_addon",
        "shared_addon",
    ]
    # Stopping one leaves the overlay prepended (the other is still developed).
    stop_develop(proj, "shared_addon", conf_file=conf)
    assert str(dev / "overlay") in read_addons_path(conf)
    assert [p.name for p in (dev / "overlay").iterdir()] == ["other_addon"]
