"""Tests for ``sync_addons`` and the ``verify`` gate, incl. each tamper case."""

import subprocess
from pathlib import Path

import pytest

from odoo_dev.vendor.lock import Lockfile, LockEntry
from odoo_dev.vendor.sync import sync_addons
from odoo_dev.vendor.verify import verify


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_repo(
    tmp_path: Path,
    *,
    python_dep: str | None = None,
    tag: str | None = None,
    extra: dict | None = None,
):
    """A source repo with addon ``shared_addon``; optional python dep + version tag.

    ``extra`` maps addon-relative paths to contents, for files whose NAME is what
    matters (e.g. a bundled ``package.json`` a repo-wide ignore rule would eat).
    """
    repo = tmp_path / "src"
    (repo / "shared_addon").mkdir(parents=True)
    manifest = {"name": "shared_addon", "version": "18.0.1.0.0"}
    if python_dep:
        manifest["external_dependencies"] = {"python": [python_dep]}
    (repo / "shared_addon" / "__manifest__.py").write_text(repr(manifest) + "\n")
    (repo / "shared_addon" / "models.py").write_text("y = 2\n")
    for rel, content in (extra or {}).items():
        p = repo / "shared_addon" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    sha = _git(repo, "rev-parse", "HEAD")
    if tag:
        _git(repo, "tag", tag, sha)
    return repo, sha


def _project(tmp_path: Path, entry: LockEntry) -> tuple[Path, Lockfile]:
    proj = tmp_path / "client"
    proj.mkdir()
    lock = Lockfile(entries={entry.name: entry})
    return proj, lock


def test_sync_materializes_from_lock(tmp_path):
    repo, sha = _source_repo(tmp_path)
    proj, lock = _project(
        tmp_path, LockEntry("shared_addon", str(repo), sha, version="18.0.1.0.0")
    )
    synced = sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    assert synced == ["shared_addon"]
    assert (proj / "vendored" / "shared_addon" / "models.py").read_text() == "y = 2\n"


def test_verify_green_after_sync(tmp_path):
    repo, sha = _source_repo(tmp_path, tag="shared_addon/18.0.1.0.0")
    proj, lock = _project(
        tmp_path, LockEntry("shared_addon", str(repo), sha, version="18.0.1.0.0")
    )
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []


def test_verify_red_on_handedit(tmp_path):
    repo, sha = _source_repo(tmp_path)
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    (proj / "vendored" / "shared_addon" / "models.py").write_text("y = 999\n")
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("differs from pin" in p for p in problems)


def test_verify_red_on_orphan_lock_entry(tmp_path):
    repo, sha = _source_repo(tmp_path)
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    # never synced -> vendored/ missing
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("not materialized" in p for p in problems)


def test_verify_red_on_orphan_vendored_dir(tmp_path):
    repo, sha = _source_repo(tmp_path)
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    # a vendored dir with no lock entry
    (proj / "vendored" / "rogue_addon").mkdir()
    (proj / "vendored" / "rogue_addon" / "__manifest__.py").write_text("{}\n")
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("rogue_addon" in p and "no addons.lock entry" in p for p in problems)


def test_verify_red_on_missing_python_dep(tmp_path):
    repo, sha = _source_repo(tmp_path, python_dep="stdnum")
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    # no requirements.txt -> dep unsatisfied
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("stdnum" in p and "requirements.txt" in p for p in problems)


def test_verify_green_when_python_dep_declared(tmp_path):
    repo, sha = _source_repo(tmp_path, python_dep="python-stdnum")
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    (proj / "requirements.txt").write_text("python-stdnum>=1.9\n")
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []


def test_verify_python_dep_specifier_matches_bare_requirement(tmp_path):
    # Manifest declares a version-specified dep; requirements.txt pins the bare
    # name — the check must compare package NAMES, not the whole spec string.
    repo, sha = _source_repo(tmp_path, python_dep="caldav>=1.3.9,<=2.0.1")
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    (proj / "requirements.txt").write_text("caldav==1.3.9\n")
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []


def test_verify_red_on_moved_tag(tmp_path):
    repo, sha = _source_repo(tmp_path, tag="shared_addon/18.0.1.0.0")
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    # claim a version whose tag doesn't resolve to the pinned commit
    lock.entries["shared_addon"].version = "18.0.9.9.9"
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("does not resolve" in p for p in problems)


def test_verify_red_on_double_load(tmp_path):
    repo, sha = _source_repo(tmp_path)
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    # same addon name also present under addons/
    (proj / "addons" / "shared_addon").mkdir(parents=True)
    (proj / "addons" / "shared_addon" / "__manifest__.py").write_text("{}\n")
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("double-load" in p for p in problems)


def _sync_clean(tmp_path):
    """A clean, fully-vendored project (no addons/ symlinks)."""
    repo, sha = _source_repo(tmp_path, tag="shared_addon/18.0.1.0.0")
    proj, lock = _project(
        tmp_path, LockEntry("shared_addon", str(repo), sha, version="18.0.1.0.0")
    )
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    return proj, lock


def test_verify_hybrid_symlink_ignored_by_default_flagged_when_strict(tmp_path):
    proj, lock = _sync_clean(tmp_path)
    # A leftover submodule-backed addon still surfaced via an addons/ symlink.
    (proj / ".repos" / "bemade-tools" / "legacy_addon").mkdir(parents=True)
    (proj / "addons").mkdir(exist_ok=True)
    (proj / "addons" / "legacy_addon").symlink_to(
        Path("../.repos/bemade-tools/legacy_addon")
    )

    # Lenient by default (partial migration is a valid transient state).
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []
    # Strict: the hybrid is flagged.
    strict = verify(proj, lock, cache_dir=tmp_path / "cache", allow_hybrid=False)
    assert any("legacy_addon" in p and "hybrid" in p for p in strict)


def test_verify_strict_green_on_fully_vendored_repo(tmp_path):
    proj, lock = _sync_clean(tmp_path)
    assert verify(proj, lock, cache_dir=tmp_path / "cache", allow_hybrid=False) == []


# --- .gitignore silently stripping files out of vendored/ ---------------------


def _git_project(tmp_path: Path, entry: LockEntry, gitignore: str) -> tuple:
    proj, lock = _project(tmp_path, entry)
    _git(proj, "init", "-q")
    _git(proj, "config", "user.email", "t@t")
    _git(proj, "config", "user.name", "t")
    (proj / ".gitignore").write_text(gitignore)
    return proj, lock


def test_verify_red_when_gitignore_would_drop_vendored_files(tmp_path):
    """Regression: repo-wide js-tooling ignores are harmless while shared addons
    live in submodules, but start applying the moment they become real files under
    vendored/. ``git add`` then skips them silently and the committed tree is
    incomplete — green locally, red only in CI, with an error that reads like an
    upstream problem.
    """
    repo, sha = _source_repo(
        tmp_path, extra={"static/src/lib/vendorlib/package.json": "{}\n"}
    )
    proj, lock = _git_project(
        tmp_path,
        LockEntry("shared_addon", str(repo), sha),
        "node_modules\npackage.json\n",
    )
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    problems = verify(proj, lock, cache_dir=tmp_path / "cache")
    assert any("package.json" in p and ".gitignore" in p for p in problems)


def test_verify_green_when_vendored_negation_present(tmp_path):
    repo, sha = _source_repo(
        tmp_path, extra={"static/src/lib/vendorlib/package.json": "{}\n"}
    )
    proj, lock = _git_project(
        tmp_path,
        LockEntry("shared_addon", str(repo), sha),
        "node_modules\npackage.json\n!vendored/**\n",
    )
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []


def test_verify_gitignore_check_is_silent_outside_a_git_repo(tmp_path):
    """A plain (non-git) project dir must not trip the new assertion."""
    repo, sha = _source_repo(tmp_path, extra={"package.json": "{}\n"})
    proj, lock = _project(tmp_path, LockEntry("shared_addon", str(repo), sha))
    sync_addons(proj, lock, cache_dir=tmp_path / "cache")
    assert verify(proj, lock, cache_dir=tmp_path / "cache") == []


def test_verify_strict_ignores_non_repos_symlink(tmp_path):
    proj, lock = _sync_clean(tmp_path)
    # A symlink that does NOT point into .repos/ is not a hybrid.
    (proj / "elsewhere").mkdir()
    (proj / "addons").mkdir(exist_ok=True)
    (proj / "addons" / "external").symlink_to(Path("../elsewhere"))
    assert verify(proj, lock, cache_dir=tmp_path / "cache", allow_hybrid=False) == []
