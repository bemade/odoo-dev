"""Pins on unmerged upstream branches: ``bump --branch`` and the mainline gate.

A client may pin a shared addon to an upstream FEATURE branch while the change
is tested on its staging. Production must only carry commits that reached the
source's mainline: ``verify(..., mainline="18.0")`` (``vendor check
--mainline``) fails any pin whose commit is not in the mainline's history,
unless the entry is marked ``allow_unmerged: true`` (an intentional long-lived
branch pin).
"""

import subprocess
from pathlib import Path

from odoo_dev.vendor.edit import add_addon, bump_addon
from odoo_dev.vendor.lock import Lockfile, LockEntry
from odoo_dev.vendor.sync import sync_addons
from odoo_dev.vendor.verify import verify


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_with_feature(tmp_path: Path):
    """Source repo: mainline ``18.0`` and an unmerged ``feat`` branch."""
    repo = tmp_path / "src"
    (repo / "shared_addon").mkdir(parents=True)
    (repo / "shared_addon" / "__manifest__.py").write_text(
        "{'name': 'shared', 'version': '18.0.1.0.0'}\n"
    )
    (repo / "shared_addon" / "m.py").write_text("v = 1\n")
    _git(repo, "init", "-q", "-b", "18.0")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1")
    main_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-qb", "feat")
    (repo / "shared_addon" / "m.py").write_text("v = 2\n")
    _git(repo, "commit", "-qam", "feature")
    feat_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "18.0")
    return repo, main_sha, feat_sha


def _pinned(tmp_path, repo, sha, **kw):
    proj = tmp_path / "client"
    proj.mkdir(exist_ok=True)
    lock = Lockfile(entries={"shared_addon": LockEntry("shared_addon", str(repo), sha, **kw)})
    lock.dump(proj / "addons.lock")
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    return proj, lock


def test_mainline_gate_refuses_unmerged_pin(tmp_path):
    repo, _main, feat = _source_with_feature(tmp_path)
    proj, lock = _pinned(tmp_path, repo, feat, branch="feat")
    problems = verify(proj, lock, cache_dir=tmp_path / "cache", mainline="18.0")
    assert len(problems) == 1
    assert "not on 18.0" in problems[0]


def test_mainline_gate_passes_once_merged(tmp_path):
    repo, _main, feat = _source_with_feature(tmp_path)
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge feat", "feat")
    proj, lock = _pinned(tmp_path, repo, feat, branch="feat")
    assert verify(proj, lock, cache_dir=tmp_path / "cache", mainline="18.0") == []


def test_allow_unmerged_opts_out_and_round_trips(tmp_path):
    repo, _main, feat = _source_with_feature(tmp_path)
    proj, lock = _pinned(tmp_path, repo, feat, branch="feat", allow_unmerged=True)
    assert verify(proj, lock, cache_dir=tmp_path / "cache", mainline="18.0") == []
    reloaded = Lockfile.load(proj / "addons.lock")
    assert reloaded.entries["shared_addon"].allow_unmerged is True
    assert "allow_unmerged" in (proj / "addons.lock").read_text()


def test_mainline_pin_passes_and_flag_is_omitted_by_default(tmp_path):
    repo, main, _feat = _source_with_feature(tmp_path)
    proj, lock = _pinned(tmp_path, repo, main, branch="18.0")
    assert verify(proj, lock, cache_dir=tmp_path / "cache", mainline="18.0") == []
    assert "allow_unmerged" not in (proj / "addons.lock").read_text()


def test_without_mainline_a_branch_pin_is_fine(tmp_path):
    repo, _main, feat = _source_with_feature(tmp_path)
    proj, lock = _pinned(tmp_path, repo, feat, branch="feat")
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []


def test_bump_to_a_branch_tracks_it(tmp_path):
    repo, main, feat = _source_with_feature(tmp_path)
    proj = tmp_path / "client"
    proj.mkdir()
    add_addon(proj, "shared_addon", str(repo), commit=main, cache_dir=tmp_path / "cache")
    entry = bump_addon(proj, "shared_addon", branch="feat", cache_dir=tmp_path / "cache")
    assert entry.branch == "feat"
    assert entry.commit == feat
    assert entry.version is None
    assert (proj / "vendored" / "shared_addon" / "m.py").read_text() == "v = 2\n"
    # an explicit commit wins over the branch head, and the branch is recorded
    entry = bump_addon(proj, "shared_addon", commit=main, branch="18.0",
                       cache_dir=tmp_path / "cache")
    assert (entry.branch, entry.commit) == ("18.0", main)
