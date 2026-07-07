"""``vendor update``: pull the latest available version for tracked addons.

The **pull** side of per-addon vendoring — a client owns its pins. For each
vendored addon that tracks upstream (has a ``version`` tag series, or a
``branch``), this finds the newest available and bumps to it. Run on a schedule
(each client's own CI, its own token) for routine propagation, and on-demand by
the ``bump_ship`` worker after a shared-addon change merges upstream. An addon
pinned to a bare commit (no ``version``/``branch``) is left alone — a deliberate
fixed pin.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Optional

from odoo_dev.vendor.edit import bump_addon
from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.sources import _ensure_clone, resolve_commit


def _version_key(v: str) -> tuple:
    """Comparable key for an Odoo version string like ``19.0.1.3.2``."""
    return tuple(int(p) if p.isdigit() else 0 for p in v.replace("-", ".").split("."))


def _series(v: str) -> str:
    """The major-series segment of a version — the cross-series guard.

    An Odoo addon carries both ``18.0.*`` and ``19.0.*`` version tags in its source;
    version-tracking must stay within the pin's own series (``18`` vs ``19``), since
    moving across Odoo series is a deliberate migration, never an auto-update.
    """
    return v.split(".", 1)[0]


def list_addon_versions(
    source: str,
    addon: str,
    cache_dir: Optional[Path] = None,
    series: Optional[str] = None,
) -> list[str]:
    """``<addon>/<version>`` tag versions in ``source``, optionally same-series only."""
    repo = _ensure_clone(source, cache_dir)
    r = subprocess.run(
        ["git", "-C", str(repo), "tag", "-l", f"{addon}/*"],
        capture_output=True,
        text=True,
    )
    versions = [
        t.split("/", 1)[1]
        for t in r.stdout.split()
        if t.startswith(f"{addon}/") and "/" in t
    ]
    if series is not None:
        versions = [v for v in versions if _series(v) == series]
    return versions


def latest_version(
    source: str,
    addon: str,
    cache_dir: Optional[Path] = None,
    series: Optional[str] = None,
) -> Optional[str]:
    versions = list_addon_versions(source, addon, cache_dir, series)
    return max(versions, key=_version_key) if versions else None


def find_updates(
    project_dir: Path,
    lock: Lockfile,
    names: Optional[Iterable[str]] = None,
    cache_dir: Optional[Path] = None,
) -> list[dict]:
    """Return the addons with a newer upstream than their pin.

    Each item: ``{name, kind, current, latest[, commit]}`` where ``kind`` is
    ``'version'`` (a newer ``<addon>/<version>`` tag) or ``'branch'`` (the tracked
    branch HEAD moved).
    """
    only = set(names) if names is not None else None
    updates = []
    for name, e in lock.entries.items():
        if only is not None and name not in only:
            continue
        if e.version:  # version-tracked (within the pin's own major series)
            latest = latest_version(e.source, name, cache_dir, series=_series(e.version))
            if latest and _version_key(latest) > _version_key(e.version):
                updates.append(
                    {
                        "name": name,
                        "kind": "version",
                        "current": e.version,
                        "latest": latest,
                    }
                )
        elif e.branch:  # branch-tracked
            head = resolve_commit(e.source, e.branch, cache_dir)
            if head != e.commit:
                updates.append(
                    {
                        "name": name,
                        "kind": "branch",
                        "current": e.commit[:12],
                        "latest": head[:12],
                        "commit": head,
                    }
                )
        # else: bare commit pin — deliberately fixed, never auto-updated.
    return updates


def apply_update(
    project_dir: Path, update: dict, cache_dir: Optional[Path] = None
):
    """Bump one addon to the update found by :func:`find_updates`."""
    if update["kind"] == "version":
        return bump_addon(
            project_dir, update["name"], version=update["latest"], cache_dir=cache_dir
        )
    return bump_addon(
        project_dir, update["name"], commit=update["commit"], cache_dir=cache_dir
    )
