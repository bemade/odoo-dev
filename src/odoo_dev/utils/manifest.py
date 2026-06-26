"""Read and bump the version string in an Odoo module's ``__manifest__.py``.

The version is treated **series-agnostically**: only the trailing
``major.minor.patch`` segments move, never the Odoo series prefix (e.g. the
``19.0`` in ``19.0.1.2.3``). patch -> last segment, minor -> second-to-last,
major -> third-to-last (zeroing everything after). A minor/major bump needs
>=3 segments so the series prefix is never touched.

NB: this logic is mirrored in the ``bemade/pre-commit-hooks`` repo
(``bemade_pre_commit_hooks/_manifest.py``), which enforces the bump in
pre-commit/CI. Keep the two in sync until they share a published dependency.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")
_VERSION_RE = re.compile(
    r"""(?P<prefix>["']version["']\s*:\s*)(?P<q>["'])(?P<ver>[^"']*)(?P=q)"""
)
_LEVEL_INDEX = {"patch": -1, "minor": -2, "major": -3}


def find_module_root(path: Path) -> Optional[Path]:
    for parent in [path, *path.parents]:
        if parent.is_dir() and any((parent / m).is_file() for m in MANIFEST_NAMES):
            return parent
    return None


def manifest_path(module_root: Path) -> Optional[Path]:
    for name in MANIFEST_NAMES:
        p = module_root / name
        if p.is_file():
            return p
    return None


def read_version(manifest_text: str) -> Optional[str]:
    m = _VERSION_RE.search(manifest_text)
    if m:
        return m.group("ver")
    try:
        data = ast.literal_eval(manifest_text.strip())
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            return data["version"]
    except Exception:
        pass
    return None


def set_version(manifest_text: str, new_version: str) -> str:
    def _sub(m: re.Match) -> str:
        return f"{m.group('prefix')}{m.group('q')}{new_version}{m.group('q')}"

    return _VERSION_RE.sub(_sub, manifest_text, count=1)


def bump_version_string(version: str, level: str) -> str:
    idx = _LEVEL_INDEX.get(level)
    if idx is None:
        raise ValueError(f"unknown bump level {level!r} (patch|minor|major)")
    parts = version.split(".")
    if len(parts) < -idx:
        raise ValueError(f"version {version!r} has too few segments for a {level} bump")
    if level in ("minor", "major") and len(parts) < 3:
        raise ValueError(
            f"refusing a {level} bump on {version!r}: need >=3 segments so the "
            f"series prefix is never touched"
        )
    try:
        parts[idx] = str(int(parts[idx]) + 1)
    except ValueError as exc:
        raise ValueError(f"non-numeric segment in version {version!r}") from exc
    for i in range(idx + 1, 0):
        parts[i] = "0"
    return ".".join(parts)
