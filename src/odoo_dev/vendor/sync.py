"""``vendor sync``: materialize ``vendored/<addon>/`` from ``addons.lock``."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.materialize import extract_subtree
from odoo_dev.vendor.sources import get_source_at


def sync_addons(
    project_dir: Path,
    lock: Lockfile,
    cache_dir: Optional[Path] = None,
    names: Optional[Iterable[str]] = None,
) -> list:
    """Materialize each locked addon into ``<project_dir>/vendored/<addon>/``.

    Returns the list of addon names synced.
    """
    project_dir = Path(project_dir)
    vendored = project_dir / "vendored"
    only = set(names) if names is not None else None
    synced = []
    for name, entry in lock.entries.items():
        if only is not None and name not in only:
            continue
        repo = get_source_at(entry.source, entry.commit, cache_dir, entry.branch)
        extract_subtree(repo, entry.commit, name, vendored / name)
        synced.append(name)
    return synced
