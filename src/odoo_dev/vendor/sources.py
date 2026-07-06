"""Resolve a lockfile ``source`` to a local git repo that contains a given commit.

A ``source`` is either a local path (used in tests and local dev) or a remote
spec (``github.com/org/repo``, a full URL, or ``git@host:org/repo``). Remotes are
cloned once into a cache and fetched on demand. All network access lives here, so
the sync/verify logic stays testable against local fixture repos.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def default_cache_dir() -> Path:
    base = Path.home() / ".cache" / "odoo-dev" / "vendor"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _clone_url(source: str) -> str:
    if "://" in source or source.startswith("git@"):
        return source
    # host/org/repo -> https://host/org/repo(.git)
    url = "https://" + source
    return url if url.endswith(".git") else url + ".git"


def _cache_key(source: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", source.rstrip("/"))


def _has_commit(repo: Path, commit: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
        ).returncode
        == 0
    )


def _ensure_clone(source: str, cache_dir: Path | None = None) -> Path:
    """Return a local repo path for ``source`` (clone into cache if remote), fetched."""
    local = Path(source).expanduser()
    if local.is_dir() and (local / ".git").exists():
        return local
    cache_dir = cache_dir or default_cache_dir()
    repo = cache_dir / _cache_key(source)
    if not repo.exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", _clone_url(source), str(repo)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--tags", "origin"],
            capture_output=True,
            text=True,
        )
    return repo


def resolve_commit(source: str, ref: str, cache_dir: Path | None = None) -> str:
    """Resolve a ref (tag, branch, or sha) in ``source`` to a full commit sha."""
    repo = _ensure_clone(source, cache_dir)
    for candidate in (ref, f"origin/{ref}", f"refs/tags/{ref}"):
        res = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "rev-parse",
                "--verify",
                "-q",
                f"{candidate}^{{commit}}",
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    raise RuntimeError(f"{source}: cannot resolve ref {ref!r} to a commit")


def get_source_at(
    source: str, commit: str, cache_dir: Path | None = None, branch: str | None = None
) -> Path:
    """Return a local git repo path guaranteed to contain ``commit``.

    Local-path sources are used as-is (they must already contain the commit).
    Remote sources are cloned/fetched into ``cache_dir``.
    """
    local = Path(source).expanduser()
    if local.is_dir() and (local / ".git").exists():
        if not _has_commit(local, commit):
            raise RuntimeError(f"{source}: commit {commit} not present in local repo")
        return local

    cache_dir = cache_dir or default_cache_dir()
    repo = cache_dir / _cache_key(source)
    if not repo.exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", _clone_url(source), str(repo)],
            check=True,
            capture_output=True,
            text=True,
        )
    if not _has_commit(repo, commit):
        fetch = ["git", "-C", str(repo), "fetch", "--tags", "origin"]
        if branch:
            fetch.append(branch)
        subprocess.run(fetch, check=True, capture_output=True, text=True)
    if not _has_commit(repo, commit):
        # last resort: try to fetch the exact sha (supported by some servers)
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "origin", commit],
            capture_output=True,
            text=True,
        )
    if not _has_commit(repo, commit):
        raise RuntimeError(f"{source}: could not fetch commit {commit}")
    return repo


def tag_resolves_to(repo: Path, tag: str, commit: str) -> bool:
    """True if ``tag`` in ``repo`` dereferences to ``commit`` (the moved-tag tripwire)."""
    res = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "-n", "1", f"refs/tags/{tag}"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return False
    return res.stdout.strip() == _full_sha(repo, commit)


def _full_sha(repo: Path, commit: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{commit}^{{commit}}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
