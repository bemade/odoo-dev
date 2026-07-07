"""``vendor check``: prove ``vendored/`` matches ``addons.lock`` — the CI gate.

Assertions (any failure => non-empty problem list => CI red):
  1. lockfile <-> vendored consistency (no orphan on either side);
  2. byte/mode/symlink identity of each vendored addon vs its pinned commit;
  3. moved-tag tripwire (when the entry carries a ``version`` tag);
  4. external python deps of vendored manifests are present in ``requirements.txt``;
  5. no addon name in both ``addons/`` and ``vendored/`` (double-load);
  6. (``allow_hybrid=False`` only) no ``addons/`` symlink still points into a
     ``.repos/`` submodule — i.e. the repo is fully vendored, not a hybrid.
The gate writes nothing.
"""

from __future__ import annotations

import ast
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.materialize import extract_subtree, tree_diff
from odoo_dev.vendor.sources import get_source_at, tag_resolves_to

_MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


def _normalize(pkg: str) -> str:
    return re.sub(r"[-_.]+", "-", pkg.strip().lower())


def _pkg_name(spec: str) -> str:
    """Bare, normalized distribution name from a requirement spec.

    Strips version specifiers, extras, and env markers, so
    ``caldav>=1.3.9,<=2.0.1`` and ``icalendar<6.0`` and ``foo[bar]`` all reduce to
    their package name. Used for BOTH requirements.txt lines and a manifest's
    ``external_dependencies['python']`` entries (which may carry the same syntax).
    """
    token = re.split(r"[<>=!~;\[\s(]", spec.strip(), 1)[0]
    return _normalize(token)


def requirements_names(project_dir: Path) -> set:
    """Normalized package names declared in the repo-root ``requirements.txt``."""
    req = Path(project_dir) / "requirements.txt"
    if not req.exists():
        return set()
    names = set()
    for line in req.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or "://" in line:
            continue
        name = _pkg_name(line)
        if name:
            names.add(name)
    return names


def manifest_python_deps(addon_dir: Path) -> list:
    """The ``external_dependencies['python']`` list from an addon's manifest."""
    for name in _MANIFEST_NAMES:
        mf = Path(addon_dir) / name
        if mf.is_file():
            try:
                data = ast.literal_eval(mf.read_text().strip())
            except Exception:
                return []
            if isinstance(data, dict):
                ext = data.get("external_dependencies") or {}
                if isinstance(ext, dict):
                    py = ext.get("python") or []
                    if isinstance(py, (list, tuple)):
                        return [str(p) for p in py]
            return []
    return []


def hybrid_submodule_addons(project_dir: Path) -> list:
    """``addons/`` symlinks that still source an addon from a ``.repos/`` submodule.

    A fully-vendored repo has none. Their presence means the repo is a *hybrid*
    (some addons vendored, some still submodule-backed) — which is unsafe for the
    work-plane's "skip submodule land when ``addons.lock`` exists" shortcut, since
    the still-submodule'd addons would be silently dropped from the land step.
    """
    project_dir = Path(project_dir)
    addons = project_dir / "addons"
    if not addons.exists():
        return []
    repos = (project_dir / ".repos").resolve()
    hybrids = []
    for p in sorted(addons.iterdir()):
        if not p.is_symlink():
            continue
        target = Path(os.readlink(p))
        if ".repos" in target.parts:
            hybrids.append(p.name)
            continue
        try:
            abs_target = (p.parent / target).resolve()
            abs_target.relative_to(repos)
        except (OSError, ValueError):
            continue
        hybrids.append(p.name)
    return hybrids


def verify(
    project_dir: Path,
    lock: Lockfile,
    cache_dir: Optional[Path] = None,
    allow_hybrid: bool = True,
) -> list:
    """Return a list of human-readable problems; empty means the gate is green.

    ``allow_hybrid=False`` (the CI gate for a repo that declares itself fully
    vendored) additionally fails if any ``addons/`` symlink still points into a
    ``.repos/`` submodule.
    """
    project_dir = Path(project_dir)
    vendored = project_dir / "vendored"
    addons = project_dir / "addons"
    problems: list = []

    vendored_dirs = (
        {p.name for p in vendored.iterdir() if p.is_dir()}
        if vendored.exists()
        else set()
    )
    lock_names = set(lock.entries)

    for name in sorted(lock_names - vendored_dirs):
        problems.append(f"{name}: in addons.lock but not materialized under vendored/")
    for name in sorted(vendored_dirs - lock_names):
        problems.append(f"{name}: under vendored/ but has no addons.lock entry")

    reqs = requirements_names(project_dir)

    for name in sorted(lock_names & vendored_dirs):
        entry = lock.entries[name]
        try:
            repo = get_source_at(entry.source, entry.commit, cache_dir, entry.branch)
        except Exception as exc:  # unfetchable source/commit
            problems.append(f"{name}: cannot resolve source pin: {exc}")
            continue

        with tempfile.TemporaryDirectory() as td:
            ref = Path(td) / name
            try:
                extract_subtree(repo, entry.commit, name, ref)
            except Exception as exc:
                problems.append(f"{name}: cannot extract pinned subtree: {exc}")
                continue
            for d in tree_diff(ref, vendored / name):
                problems.append(f"{name}: vendored copy differs from pin — {d}")

        if entry.version:
            tag = f"{name}/{entry.version}"
            if not tag_resolves_to(repo, tag, entry.commit):
                problems.append(
                    f"{name}: tag {tag} does not resolve to pinned commit "
                    f"{entry.commit[:12]} (moved/mismatched tag)"
                )

        for dep in manifest_python_deps(vendored / name):
            if _pkg_name(dep) not in reqs:
                problems.append(
                    f"{name}: external python dep '{dep}' not in requirements.txt "
                    f"(unsatisfiable on Odoo.sh)"
                )

    if addons.exists():
        addon_names = {p.name for p in addons.iterdir() if p.is_dir() or p.is_symlink()}
        for name in sorted(addon_names & vendored_dirs):
            problems.append(
                f"{name}: present in BOTH addons/ and vendored/ (double-load)"
            )

    if not allow_hybrid:
        for name in hybrid_submodule_addons(project_dir):
            problems.append(
                f"{name}: addons/{name} still symlinks into .repos/ — hybrid "
                f"submodule+vendored repo not allowed (finish 'vendor migrate')"
            )

    return problems
