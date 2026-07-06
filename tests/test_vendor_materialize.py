"""Tests for subtree extraction and the byte/mode/symlink-aware directory compare.

These are the integrity core of ``vendor sync``/``vendor check``: extraction must
reproduce a source addon subtree exactly, and the compare must catch content,
executable-bit, and symlink differences (a plain ``diff -r`` misses the latter two).
"""

import os
import subprocess
from pathlib import Path

import pytest

from odoo_dev.vendor.materialize import extract_subtree, tree_diff


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_source_repo(tmp_path: Path) -> tuple[Path, str]:
    """A git repo containing an addon ``my_addon`` with a subdir, an executable
    script, and an internal symlink. Returns (repo_path, commit_sha)."""
    repo = tmp_path / "src_repo"
    (repo / "my_addon" / "models").mkdir(parents=True)
    (repo / "my_addon" / "__manifest__.py").write_text("{'name': 'my_addon'}\n")
    (repo / "my_addon" / "models" / "thing.py").write_text("x = 1\n")
    script = repo / "my_addon" / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)
    # internal symlink within the addon
    (repo / "my_addon" / "latest.py").symlink_to("models/thing.py")
    # a second addon that must NOT be extracted
    (repo / "other_addon").mkdir()
    (repo / "other_addon" / "__manifest__.py").write_text("{'name': 'other'}\n")

    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_extract_only_the_named_subtree(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    dest = tmp_path / "vendored" / "my_addon"
    extract_subtree(repo, sha, "my_addon", dest)

    assert (dest / "__manifest__.py").read_text() == "{'name': 'my_addon'}\n"
    assert (dest / "models" / "thing.py").read_text() == "x = 1\n"
    # the sibling addon is not dragged in
    assert not (dest.parent / "other_addon").exists()
    assert not (dest / "other_addon").exists()


def test_extract_preserves_exec_bit_and_symlink(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    dest = tmp_path / "vendored" / "my_addon"
    extract_subtree(repo, sha, "my_addon", dest)

    assert os.access(dest / "run.sh", os.X_OK)
    link = dest / "latest.py"
    assert link.is_symlink()
    assert os.readlink(link) == "models/thing.py"


def test_extract_is_idempotent_and_replaces_stale_content(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    dest = tmp_path / "vendored" / "my_addon"
    extract_subtree(repo, sha, "my_addon", dest)
    # a stale file left from a previous vendored version must be gone after re-extract
    (dest / "STALE.txt").write_text("old\n")
    extract_subtree(repo, sha, "my_addon", dest)
    assert not (dest / "STALE.txt").exists()


def test_tree_diff_clean(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    extract_subtree(repo, sha, "my_addon", a)
    extract_subtree(repo, sha, "my_addon", b)
    assert tree_diff(a, b) == []


def test_tree_diff_detects_content_change(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    extract_subtree(repo, sha, "my_addon", a)
    extract_subtree(repo, sha, "my_addon", b)
    (b / "models" / "thing.py").write_text("x = 2\n")
    diffs = tree_diff(a, b)
    assert any("thing.py" in d for d in diffs)


def test_tree_diff_detects_exec_bit_change(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    extract_subtree(repo, sha, "my_addon", a)
    extract_subtree(repo, sha, "my_addon", b)
    (b / "run.sh").chmod(0o644)
    diffs = tree_diff(a, b)
    assert any("run.sh" in d and "mode" in d.lower() for d in diffs)


def test_tree_diff_detects_symlink_retarget(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    extract_subtree(repo, sha, "my_addon", a)
    extract_subtree(repo, sha, "my_addon", b)
    link = b / "latest.py"
    link.unlink()
    link.symlink_to("__manifest__.py")
    diffs = tree_diff(a, b)
    assert any("latest.py" in d for d in diffs)


def test_tree_diff_detects_missing_and_extra_files(tmp_path):
    repo, sha = _make_source_repo(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    extract_subtree(repo, sha, "my_addon", a)
    extract_subtree(repo, sha, "my_addon", b)
    (b / "extra.py").write_text("nope\n")
    (a / "models" / "thing.py").unlink()
    diffs = tree_diff(a, b)
    assert any("extra.py" in d for d in diffs)
    assert any("thing.py" in d for d in diffs)


def test_extract_bad_commit_raises(tmp_path):
    repo, _ = _make_source_repo(tmp_path)
    with pytest.raises(Exception):
        extract_subtree(
            repo, "0000000000000000000000000000000000000000", "my_addon", tmp_path / "x"
        )
