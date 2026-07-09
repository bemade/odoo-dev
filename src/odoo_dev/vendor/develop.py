"""``vendor develop``: edit a vendored addon against a live source clone.

The committed ``vendored/<addon>`` copy is authoritative-downstream: it's what
CI and prod ship, and ``vendor bump`` clobbers it on every re-sync. So you can't
just edit it in place. ``vendor develop`` instead:

1. clones the addon's source repo (writable, full) into a git-ignored
   ``.vendor-dev/<repo>/`` and checks out a work branch at the pinned commit;
2. exposes the live addon through ``.vendor-dev/overlay/<addon>`` (a symlink) and
   **prepends that overlay dir to the local ``conf/odoo.conf`` addons_path**, so
   Odoo loads the live tree (first path wins) instead of the vendored copy.

Only the *local* conf is touched — never the Docker/CI conf — so the overlay is
structurally incapable of leaking to CI or prod. The overlay holds one symlink
per develop-mode addon, so developing one addon never shadows sibling addons that
this project pinned at a different commit. ``vendored/`` itself never changes.

The loop: edit in the clone, run/test in the client's Odoo, commit + push
upstream, then ``vendor bump <addon>`` once the new version is tagged.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from odoo_dev.vendor.lock import Lockfile
from odoo_dev.vendor.sources import _cache_key, _clone_url

DEV_DIRNAME = ".vendor-dev"
OVERLAY = "overlay"
STATE = "state.yaml"
GITIGNORE_LINE = ".vendor-dev/"


class DevelopError(Exception):
    pass


@dataclass
class DevelopEntry:
    """One addon currently in develop mode."""

    name: str
    source: str
    repo: str  # abs path to the writable clone
    branch: str
    base_commit: str

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "repo": self.repo,
            "branch": self.branch,
            "base_commit": self.base_commit,
        }

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "DevelopEntry":
        return cls(
            name=name,
            source=d["source"],
            repo=d["repo"],
            branch=d["branch"],
            base_commit=d["base_commit"],
        )


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=check, capture_output=True, text=True)


def _is_local_repo(source: str) -> bool:
    p = Path(source).expanduser()
    return p.is_dir() and (p / ".git").exists()


def _clone_arg(source: str) -> str:
    """A path/URL git can clone: local repos as-is, remotes via _clone_url."""
    return str(Path(source).expanduser()) if _is_local_repo(source) else _clone_url(
        source
    )


def _dev_clone(source: str, dest: Path) -> Path:
    """Full, writable clone of ``source`` at ``dest`` (fetch if already present)."""
    dest = Path(dest)
    if (dest / ".git").exists():
        _run("git", "-C", str(dest), "fetch", "--tags", "origin", check=False)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run("git", "clone", _clone_arg(source), str(dest))
    return dest


def _resolve_ref(clone: Path, ref: str) -> str:
    for cand in (ref, f"origin/{ref}", f"refs/tags/{ref}"):
        r = _run(
            "git", "-C", str(clone), "rev-parse", "--verify", "-q", f"{cand}^{{commit}}",
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    raise DevelopError(f"cannot resolve base ref {ref!r} in {clone}")


def _checkout_workbranch(clone: Path, branch: str, base_commit: str) -> None:
    exists = (
        _run(
            "git", "-C", str(clone), "rev-parse", "--verify", "-q",
            f"refs/heads/{branch}", check=False,
        ).returncode
        == 0
    )
    if exists:
        _run("git", "-C", str(clone), "checkout", "-q", branch)
    else:
        _run("git", "-C", str(clone), "checkout", "-q", "-b", branch, base_commit)


# --- conf addons_path editing (local conf only) ---------------------------------


def read_addons_path(conf_file: Path) -> list[str]:
    for line in Path(conf_file).read_text().splitlines():
        s = line.strip()
        if s.startswith("addons_path") and "=" in s:
            _, _, v = s.partition("=")
            return [p.strip() for p in v.split(",") if p.strip()]
    return []


def _write_addons_path(conf_file: Path, paths: list[str]) -> None:
    conf = Path(conf_file)
    lines = conf.read_text().splitlines()
    out: list[str] = []
    done = False
    for line in lines:
        s = line.strip()
        if not done and s.startswith("addons_path") and "=" in s:
            out.append(f"addons_path = {','.join(paths)}")
            done = True
        else:
            out.append(line)
    if not done:
        # No addons_path line: insert one right after [options], else at top.
        insert_at = next(
            (i + 1 for i, ln in enumerate(out) if ln.strip() == "[options]"), 0
        )
        out.insert(insert_at, f"addons_path = {','.join(paths)}")
    conf.write_text("\n".join(out) + "\n")


def prepend_addons_path(conf_file: Path, path: str) -> None:
    paths = read_addons_path(conf_file)
    if path in paths:  # keep a single entry, moved to the front (idempotent)
        paths.remove(path)
    paths.insert(0, path)
    _write_addons_path(conf_file, paths)


def remove_addons_path(conf_file: Path, path: str) -> None:
    _write_addons_path(conf_file, [p for p in read_addons_path(conf_file) if p != path])


def ensure_addons_path(conf_file: Path, path: str) -> bool:
    """Append ``path`` to the conf's addons_path if it isn't already listed.

    Idempotent; returns True only when it actually added the entry. Used by
    ``vendor migrate`` to wire ``vendored/`` into a conf that predates vendoring
    (``setup`` adds it for fresh confs but never overwrites an existing one).
    """
    paths = read_addons_path(conf_file)
    if path in paths:
        return False
    paths.append(path)
    _write_addons_path(conf_file, paths)
    return True


# --- overlay / gitignore / state ------------------------------------------------


def _overlay_dir(dev_dir: Path) -> Path:
    return Path(dev_dir) / OVERLAY


def _link_overlay(dev_dir: Path, addon: str, target: Path) -> None:
    ov = _overlay_dir(dev_dir)
    ov.mkdir(parents=True, exist_ok=True)
    link = ov / addon
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


def _unlink_overlay(dev_dir: Path, addon: str) -> None:
    link = _overlay_dir(dev_dir) / addon
    if link.is_symlink() or link.exists():
        link.unlink()


def _ensure_gitignore(project_dir: Path) -> None:
    gi = Path(project_dir) / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if GITIGNORE_LINE not in lines:
        lines.append(GITIGNORE_LINE)
        gi.write_text("\n".join(lines) + "\n")


def _state_path(dev_dir: Path) -> Path:
    return Path(dev_dir) / STATE


def _load_state(dev_dir: Path) -> dict[str, DevelopEntry]:
    p = _state_path(dev_dir)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text()) or {}
    return {n: DevelopEntry.from_dict(n, d) for n, d in raw.items()}


def _save_state(dev_dir: Path, state: dict[str, DevelopEntry]) -> None:
    Path(dev_dir).mkdir(parents=True, exist_ok=True)
    _state_path(dev_dir).write_text(
        yaml.safe_dump(
            {n: state[n].to_dict() for n in sorted(state)}, sort_keys=False
        )
    )


# --- public API -----------------------------------------------------------------


def start_develop(
    project_dir: Path,
    addon: str,
    *,
    branch: Optional[str] = None,
    base: Optional[str] = None,
    conf_file: Optional[Path] = None,
    dev_dir: Optional[Path] = None,
) -> DevelopEntry:
    """Put ``addon`` into develop mode; return its :class:`DevelopEntry`."""
    project_dir = Path(project_dir)
    conf_file = Path(conf_file) if conf_file else project_dir / "conf" / "odoo.conf"
    dev_dir = Path(dev_dir) if dev_dir else project_dir / DEV_DIRNAME

    if not conf_file.exists():
        raise DevelopError(f"{conf_file} not found — run 'odoo-dev setup' first")
    lock = Lockfile.load(project_dir / "addons.lock")
    if addon not in lock.entries:
        raise DevelopError(
            f"{addon}: not in addons.lock (vendor it with 'vendor add' first)"
        )
    entry = lock.entries[addon]

    clone = _dev_clone(entry.source, dev_dir / _cache_key(entry.source))
    base_commit = _resolve_ref(clone, base) if base else entry.commit
    branch = branch or f"vendor-dev/{addon}"
    _checkout_workbranch(clone, branch, base_commit)

    live = clone / addon
    if not live.exists():
        raise DevelopError(
            f"{addon}: not found at the repo root of {entry.source}"
        )
    _link_overlay(dev_dir, addon, live.resolve())
    prepend_addons_path(conf_file, str(_overlay_dir(dev_dir)))
    _ensure_gitignore(project_dir)

    dentry = DevelopEntry(
        name=addon,
        source=entry.source,
        repo=str(clone),
        branch=branch,
        base_commit=base_commit,
    )
    state = _load_state(dev_dir)
    state[addon] = dentry
    _save_state(dev_dir, state)
    return dentry


def stop_develop(
    project_dir: Path,
    addon: str,
    *,
    conf_file: Optional[Path] = None,
    dev_dir: Optional[Path] = None,
) -> None:
    """Take ``addon`` out of develop mode. The clone is preserved (may hold work)."""
    project_dir = Path(project_dir)
    conf_file = Path(conf_file) if conf_file else project_dir / "conf" / "odoo.conf"
    dev_dir = Path(dev_dir) if dev_dir else project_dir / DEV_DIRNAME

    state = _load_state(dev_dir)
    if addon not in state:
        raise DevelopError(f"{addon}: not in develop mode")
    _unlink_overlay(dev_dir, addon)
    del state[addon]
    _save_state(dev_dir, state)

    ov = _overlay_dir(dev_dir)
    remaining = list(ov.iterdir()) if ov.exists() else []
    if not remaining:
        if conf_file.exists():
            remove_addons_path(conf_file, str(ov))
        if ov.exists():
            ov.rmdir()


def develop_state(
    project_dir: Path, *, dev_dir: Optional[Path] = None
) -> dict[str, DevelopEntry]:
    dev_dir = Path(dev_dir) if dev_dir else Path(project_dir) / DEV_DIRNAME
    return _load_state(dev_dir)
