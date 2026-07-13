"""``vendor add`` / ``vendor bump``: edit a lockfile pin and re-materialize.

Plain pin-and-sync — no dependency-closure resolution. If an addon's ``depends``
aren't vendored, the CI module-load/test pass catches it loudly and a human adds
them. Auto-closure is a future convenience, not a correctness gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from odoo_dev.vendor.lock import LockEntry, Lockfile
from odoo_dev.vendor.sources import resolve_commit
from odoo_dev.vendor.sync import sync_addons


class EditError(Exception):
    pass


def _resolve_pin(
    name: str,
    source: str,
    version: Optional[str],
    commit: Optional[str],
    branch: Optional[str],
    cache_dir: Optional[Path],
) -> str:
    """Pick the commit a pin should point at, from version/commit/branch."""
    if commit:
        return resolve_commit(source, commit, cache_dir)
    if version:
        return resolve_commit(source, f"{name}/{version}", cache_dir)
    if branch:
        return resolve_commit(source, branch, cache_dir)
    raise EditError(f"{name}: give one of --version, --commit, or --branch")


def add_addon(
    project_dir: Path,
    name: str,
    source: str,
    version: Optional[str] = None,
    commit: Optional[str] = None,
    branch: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> LockEntry:
    """Add a new vendored addon: write the lock entry and materialize it."""
    project_dir = Path(project_dir)
    lock = Lockfile.load(project_dir / "addons.lock")
    if name in lock.entries:
        raise EditError(f"{name}: already in addons.lock (use 'vendor bump')")
    sha = _resolve_pin(name, source, version, commit, branch, cache_dir)
    entry = LockEntry(
        name=name, source=source, commit=sha, version=version, branch=branch
    )
    lock.entries[name] = entry
    lock.dump(project_dir / "addons.lock")
    sync_addons(project_dir, lock, cache_dir=cache_dir, names=[name])
    return entry


def bump_addon(
    project_dir: Path,
    name: str,
    version: Optional[str] = None,
    commit: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> LockEntry:
    """Move an existing addon's pin to a new version/commit (or its branch HEAD)."""
    project_dir = Path(project_dir)
    lock = Lockfile.load(project_dir / "addons.lock")
    if name not in lock.entries:
        raise EditError(f"{name}: not in addons.lock (use 'vendor add')")
    entry = lock.entries[name]
    sha = _resolve_pin(name, entry.source, version, commit, entry.branch, cache_dir)
    entry.commit = sha
    # ``version`` is the tag-intent metadata, and ``vendor check``'s moved-tag
    # tripwire (verify.py) requires ``<name>/<version>`` to still resolve to
    # ``commit``. A ``--commit`` / branch-HEAD bump moves the pin off the tagged
    # commit, so the old ``version`` is now stale and would (correctly) fail the
    # tripwire. Set it to whatever the bump was keyed on: the new tag for a
    # ``--version`` bump, or ``None`` for a raw ``--commit`` / branch bump — a
    # commit pin carries no version metadata (matching how ``migrate`` renders
    # untagged pins).
    entry.version = version
    lock.entries[name] = entry
    lock.dump(project_dir / "addons.lock")
    sync_addons(project_dir, lock, cache_dir=cache_dir, names=[name])
    return entry
