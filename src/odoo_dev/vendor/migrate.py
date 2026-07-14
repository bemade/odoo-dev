"""``vendor migrate``: convert a submodule+symlink repo to a vendored one.

Reads the ``addons/<addon>`` symlinks that point into ``.repos/*`` submodules,
derives a per-addon pin (submodule remote URL = source, submodule HEAD = commit,
manifest version -> version ONLY when the ``<addon>/<version>`` tag resolves to
the pinned commit; a commit that isn't the tagged release (a pin behind or ahead
of the tag, or any intermediate commit) is left commit-only, no version),
writes ``addons.lock``, materializes ``vendored/<addon>/`` from the submodule,
and removes the now-redundant symlink. Client-private real dirs under ``addons/``
are left untouched; only symlinks into submodules are migrated. Submodule removal
(``.repos`` deinit) is left out by default — it is destructive and reported, not
done, unless ``deinit=True``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from odoo_dev.utils.manifest import manifest_path, read_version
from odoo_dev.vendor.lock import LockEntry, Lockfile
from odoo_dev.vendor.sources import tag_resolves_to
from odoo_dev.vendor.sync import sync_addons


class MigrateError(Exception):
    pass


def read_gitmodules(project_dir: Path) -> list:
    """Return [(name, path, url)] for each submodule declared in .gitmodules."""
    gm = Path(project_dir) / ".gitmodules"
    if not gm.exists():
        return []
    out = subprocess.run(
        ["git", "-C", str(project_dir), "config", "-f", ".gitmodules", "--list"],
        capture_output=True,
        text=True,
    ).stdout
    subs: dict = {}
    for line in out.splitlines():
        left, _, val = line.partition("=")
        if not left.startswith("submodule."):
            continue
        # <name> may itself contain dots/slashes (git defaults it to the path),
        # so the attribute is the segment after the LAST dot.
        rest = left[len("submodule.") :]
        name, _, attr = rest.rpartition(".")
        if name and attr:
            subs.setdefault(name, {})[attr] = val
    return [
        (name, d.get("path", ""), d.get("url", ""))
        for name, d in subs.items()
        if d.get("path")
    ]


def _submodule_head(project_dir: Path, sub_path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(Path(project_dir) / sub_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def plan_migration(project_dir: Path, addons: Optional[Iterable[str]] = None) -> list:
    """Return a list of planned pins without changing anything.

    Each item: dict(name, source, commit, version, symlink, sub_path).
    """
    project_dir = Path(project_dir)
    addons_dir = project_dir / "addons"
    if not addons_dir.exists():
        return []
    subs = read_gitmodules(project_dir)
    only = set(addons) if addons is not None else None

    plans = []
    for link in sorted(addons_dir.iterdir()):
        if not link.is_symlink():
            continue  # client-private real dirs are left alone
        name = link.name
        if only is not None and name not in only:
            continue
        target = os.readlink(link)
        real = (link.parent / target).resolve()
        # Which submodule does this symlink point into?
        sub = next(
            (
                (s_name, s_path, s_url)
                for (s_name, s_path, s_url) in subs
                if _is_under(real, (project_dir / s_path).resolve())
            ),
            None,
        )
        if sub is None:
            continue  # symlink not into a known submodule; skip
        s_name, s_path, s_url = sub
        sub_root = (project_dir / s_path).resolve()
        subpath = real.relative_to(sub_root)
        if str(subpath) != name:
            raise MigrateError(
                f"{name}: addon sits at '{subpath}' inside submodule {s_path}, not at "
                f"the root as '{name}'. Nested addons aren't handled yet — migrate by hand."
            )
        commit = _submodule_head(project_dir, s_path)
        version = None
        mf = manifest_path(real)
        if mf is not None:
            v = read_version(mf.read_text())
            # Only claim a ``version`` when the tag actually points at the pinned
            # commit. Checking mere tag EXISTENCE was wrong: the same manifest
            # version can live at several commits (the tag is cut at one of
            # them), so a pin at any other commit with that version would carry a
            # ``version`` whose tag resolves elsewhere — tripping ``vendor
            # check``'s moved-tag guard. A non-release pin is commit-only.
            if v is not None and tag_resolves_to(sub_root, f"{name}/{v}", commit):
                version = v
        plans.append(
            dict(
                name=name,
                source=s_url,
                commit=commit,
                version=version,
                symlink=link,
                sub_path=s_path,
            )
        )
    return plans


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def migrate_repo(
    project_dir: Path,
    addons: Optional[Iterable[str]] = None,
    deinit: bool = False,
    cache_dir: Optional[Path] = None,
) -> tuple:
    """Migrate symlinked submodule addons to vendored form.

    Returns (lock, unused_submodule_paths). Writes addons.lock, materializes
    vendored/, and removes the migrated symlinks. Does not remove submodules
    unless ``deinit`` is set.
    """
    project_dir = Path(project_dir)
    plans = plan_migration(project_dir, addons)
    if not plans:
        return Lockfile.load(project_dir / "addons.lock"), []

    lock = Lockfile.load(project_dir / "addons.lock")
    for p in plans:
        lock.entries[p["name"]] = LockEntry(
            name=p["name"], source=p["source"], commit=p["commit"], version=p["version"]
        )
    lock.dump(project_dir / "addons.lock")

    # Materialize from the freshly written lock (uses the submodule as the source).
    sync_addons(
        project_dir, lock, cache_dir=cache_dir, names=[p["name"] for p in plans]
    )

    # Remove the now-redundant symlinks (the addon lives under vendored/ now).
    for p in plans:
        link: Path = p["symlink"]
        if link.is_symlink():
            link.unlink()

    # Which submodules have no remaining symlinks into them?
    remaining = {
        (project_dir / "addons" / l.name)
        for l in (project_dir / "addons").iterdir()
        if l.is_symlink()
    }
    migrated_subpaths = {p["sub_path"] for p in plans}
    unused = []
    for sub_path in sorted(migrated_subpaths):
        sub_root = (project_dir / sub_path).resolve()
        still_used = any(
            _is_under((r.parent / os.readlink(r)).resolve(), sub_root)
            for r in remaining
        )
        if not still_used:
            unused.append(sub_path)

    if deinit:
        for sub_path in unused:
            subprocess.run(
                ["git", "-C", str(project_dir), "submodule", "deinit", "-f", sub_path],
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-C", str(project_dir), "rm", "-f", sub_path],
                capture_output=True,
                text=True,
            )

    return lock, unused
