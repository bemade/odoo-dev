"""``vendor migrate``: convert a submodule+symlink repo to a vendored one.

Reads the ``addons/<addon>`` symlinks that point into ``.repos/*`` submodules,
derives a per-addon pin (submodule remote URL = source, recorded gitlink = commit,
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
from odoo_dev.vendor.verify import gitignored_under_vendored


class MigrateError(Exception):
    pass


_NEGATION = "!vendored/**"
_NEGATION_BLOCK = (
    "\n# Vendored addons must match addons.lock byte-for-byte, so no repo-wide\n"
    "# ignore rule may strip files out of them. Keep last.\n"
    f"{_NEGATION}\n"
)


def ensure_vendored_not_ignored(project_dir: Path) -> bool:
    """Append a ``!vendored/**`` negation when ``.gitignore`` would eat vendored files.

    ``migrate`` is the command that creates the hazard — it turns submodule content
    (governed by the submodule's own ignore rules) into real files under the
    superproject's — so it is the right place to repair it, in the same shape as
    ``ensure_addons_path`` fixing up ``conf/odoo.conf``. Idempotent; returns True
    only when it actually wrote.
    """
    project_dir = Path(project_dir)
    if not gitignored_under_vendored(project_dir):
        return False
    gitignore = project_dir / ".gitignore"
    text = gitignore.read_text() if gitignore.exists() else ""
    if any(line.strip() == _NEGATION for line in text.splitlines()):
        # Already negated yet still ignored: a later rule re-excludes the path, or
        # the negation cannot apply. Leave it — `vendor check` reports the files.
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    gitignore.write_text(text + _NEGATION_BLOCK)
    return True


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


def _gitlink_commit(project_dir: Path, sub_path: str) -> str:
    """The commit the SUPERPROJECT records for ``sub_path`` — the authoritative pin.

    Read from the superproject tree, never from the submodule working copy. An
    uninitialized submodule is an empty directory, so ``git -C <sub> rev-parse
    HEAD`` walks up to the enclosing repo, returns the SUPERPROJECT's head and
    exits 0 — pinning every addon across every source repo to one wrong sha, in a
    lockfile that ``vendor check`` then happily validates against itself.
    ``ls-tree`` cannot walk up, and the ``160000`` mode proves it is a gitlink.
    """
    res = subprocess.run(
        ["git", "-C", str(project_dir), "ls-tree", "HEAD", "--", sub_path],
        capture_output=True,
        text=True,
    )
    line = res.stdout.strip()
    if res.returncode != 0 or not line:
        raise MigrateError(
            f"{sub_path}: no submodule recorded at this path in HEAD — cannot "
            f"derive a pin (commit the submodule, or fix .gitmodules)."
        )
    mode, _, rest = line.partition(" ")
    obj_type, _, rest = rest.partition(" ")
    sha = rest.split("\t", 1)[0].strip()
    if mode != "160000" or obj_type != "commit":
        raise MigrateError(
            f"{sub_path}: recorded in HEAD as a {obj_type}, not a submodule "
            f"gitlink — cannot derive a pin."
        )
    return sha


def _submodule_checkout(project_dir: Path, sub_path: str) -> Optional[str]:
    """The commit the submodule working copy is actually on, or None if absent.

    Only meaningful for an initialized submodule (which owns a ``.git``); the
    caller uses it to warn when the checkout has drifted off the gitlink.
    """
    sub_root = Path(project_dir) / sub_path
    if not (sub_root / ".git").exists():
        return None
    res = subprocess.run(
        ["git", "-C", str(sub_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else None


def uninitialized_submodules(project_dir: Path) -> list:
    """Submodule paths git reports as not checked out (``-`` prefix)."""
    res = subprocess.run(
        ["git", "-C", str(project_dir), "submodule", "status"],
        capture_output=True,
        text=True,
    )
    paths = []
    for line in res.stdout.splitlines():
        if not line.startswith("-"):
            continue
        parts = line[1:].split()
        if len(parts) >= 2:
            paths.append(parts[1])
    return paths


def plan_migration(project_dir: Path, addons: Optional[Iterable[str]] = None) -> list:
    """Return a list of planned pins without changing anything.

    Each item: dict(name, source, commit, version, checkout, symlink, sub_path).
    ``checkout`` is the submodule's actual HEAD, so the caller can warn when it
    has drifted off the recorded gitlink the pin comes from.

    Raises :class:`MigrateError` if any submodule being migrated is uninitialized:
    its addon content and manifest are simply not on disk, and its pin cannot be
    trusted to mean anything.
    """
    project_dir = Path(project_dir)
    addons_dir = project_dir / "addons"
    if not addons_dir.exists():
        return []
    subs = read_gitmodules(project_dir)
    only = set(addons) if addons is not None else None
    uninit = set(uninitialized_submodules(project_dir))
    blocked = []

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
        if s_path in uninit:
            blocked.append((name, s_path))
            continue
        sub_root = (project_dir / s_path).resolve()
        subpath = real.relative_to(sub_root)
        if str(subpath) != name:
            raise MigrateError(
                f"{name}: addon sits at '{subpath}' inside submodule {s_path}, not at "
                f"the root as '{name}'. Nested addons aren't handled yet — migrate by hand."
            )
        commit = _gitlink_commit(project_dir, s_path)
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
                checkout=_submodule_checkout(project_dir, s_path),
                symlink=link,
                sub_path=s_path,
            )
        )

    if blocked:
        paths = sorted({s_path for _, s_path in blocked})
        names = ", ".join(sorted(name for name, _ in blocked))
        raise MigrateError(
            f"uninitialized submodule(s): {', '.join(paths)} — needed by {names}. "
            f"Run 'git submodule update --init' first; migrating without them "
            f"would pin every addon to the superproject's own HEAD."
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
