"""Tests for resolving refs against a source repo (``vendor/sources.py``)."""

import subprocess
from pathlib import Path

from odoo_dev.vendor.sources import resolve_commit


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, content: str) -> str:
    (repo / "m.py").write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", content)
    return _git(repo, "rev-parse", "HEAD")


def _upstream(tmp_path: Path) -> Path:
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "18.0")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _commit(repo, "v = 1\n")
    return repo


def test_branch_resolves_to_fetched_tip_not_clone_time_local_branch(tmp_path):
    """A cached clone keeps a local branch frozen at clone time; fetch only moves
    ``origin/<branch>``. Resolving the branch must follow the remote, or every
    ``add``/``bump --branch`` silently pins the tip as of the first clone."""
    upstream = _upstream(tmp_path)
    source = f"file://{upstream}"
    cache = tmp_path / "cache"
    resolve_commit(source, "18.0", cache)  # first use: clones into the cache

    new_tip = _commit(upstream, "v = 2\n")

    assert resolve_commit(source, "18.0", cache) == new_tip


def test_local_source_resolves_its_own_branch(tmp_path):
    """A local-path source is the user's repo, used as-is: its local branch is
    the truth, even when it also has a (stale) ``origin/<branch>``."""
    upstream = _upstream(tmp_path)
    local = tmp_path / "local"
    subprocess.run(
        ["git", "clone", "-q", str(upstream), str(local)], check=True, capture_output=True
    )
    _git(local, "config", "user.email", "t@t")
    _git(local, "config", "user.name", "t")
    local_tip = _commit(local, "v = local\n")

    assert resolve_commit(str(local), "18.0") == local_tip
