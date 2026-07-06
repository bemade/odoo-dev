"""The ``addons.lock`` model: one entry per vendored addon.

``commit`` is the pin (required, universal — valid for tagged and untagged
sources alike, and byte-reproducible even if a tag is later moved). ``version``
is optional metadata (the ``<addon>/<version>`` tag — readable intent and the
push-fan-out trigger). ``branch`` is optional (the target a scheduled update
check watches for untagged sources, e.g. passively-tracked OCA forks).

Entries serialize sorted by addon name so a bump produces a minimal diff.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


class LockError(Exception):
    """Raised when an ``addons.lock`` is malformed."""


@dataclass
class LockEntry:
    """A single pinned addon."""

    name: str
    source: str
    commit: str
    version: Optional[str] = None
    branch: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"source": self.source}
        if self.version is not None:
            d["version"] = self.version
        if self.branch is not None:
            d["branch"] = self.branch
        d["commit"] = self.commit
        return d

    @classmethod
    def from_dict(cls, name: str, data: dict) -> "LockEntry":
        if not isinstance(data, dict):
            raise LockError(
                f"{name}: entry must be a mapping, got {type(data).__name__}"
            )
        source = data.get("source")
        if not source:
            raise LockError(f"{name}: missing required 'source'")
        commit = data.get("commit")
        if not commit:
            raise LockError(f"{name}: missing required 'commit'")
        return cls(
            name=name,
            source=str(source),
            commit=str(commit),
            version=(str(data["version"]) if data.get("version") is not None else None),
            branch=(str(data["branch"]) if data.get("branch") is not None else None),
        )


@dataclass
class Lockfile:
    """The whole ``addons.lock``: addon name -> :class:`LockEntry`."""

    entries: dict

    @classmethod
    def load(cls, path: Path) -> "Lockfile":
        path = Path(path)
        if not path.exists():
            return cls(entries={})
        raw = yaml.safe_load(path.read_text()) or {}
        if not isinstance(raw, dict):
            raise LockError(f"{path}: top level must be a mapping of addon -> pin")
        entries = {name: LockEntry.from_dict(name, data) for name, data in raw.items()}
        return cls(entries=entries)

    def dump(self, path: Path) -> None:
        ordered = {name: self.entries[name].to_dict() for name in sorted(self.entries)}
        Path(path).write_text(
            yaml.safe_dump(ordered, sort_keys=False, default_flow_style=False)
        )
