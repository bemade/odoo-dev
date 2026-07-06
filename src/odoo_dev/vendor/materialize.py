"""Extract an addon subtree from a source git repo and compare trees exactly.

Extraction uses ``git archive <commit>:<addon>`` piped into ``tar -xp`` so file
modes and symlinks survive verbatim — the vendored copy is byte-identical to the
source subtree. :func:`tree_diff` then compares two trees on content, the
executable bit, and symlink targets (a plain ``diff -r`` silently ignores the
latter two and follows symlinks), which is what makes ``vendor check`` trustworthy.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def extract_subtree(repo: Path, commit: str, addon: str, dest: Path) -> None:
    """Materialize ``<commit>:<addon>/`` from ``repo`` into ``dest`` (verbatim).

    ``dest`` is fully replaced, so a re-extract drops any stale files from a
    previous vendored version.
    """
    repo = Path(repo)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # git archive of the tree-ish <commit>:<addon> yields a tar rooted at the
    # addon's *contents* (no leading addon/ prefix); tar -xp preserves modes and
    # recreates symlinks as symlinks.
    archive = subprocess.Popen(
        ["git", "-C", str(repo), "archive", "--format=tar", f"{commit}:{addon}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tar = subprocess.Popen(
        ["tar", "-x", "-p", "-C", str(dest)],
        stdin=archive.stdout,
        stderr=subprocess.PIPE,
    )
    archive.stdout.close()  # allow archive to receive SIGPIPE if tar exits
    tar_err = tar.communicate()[1]
    arch_rc = archive.wait()
    arch_err = archive.stderr.read()
    archive.stderr.close()

    if arch_rc != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(
            f"git archive {commit}:{addon} failed in {repo}: "
            f"{arch_err.decode(errors='replace').strip()}"
        )
    if tar.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(
            f"tar extract failed for {addon}: {tar_err.decode(errors='replace').strip()}"
        )


def _entries(root: Path) -> dict:
    """Map each path relative to ``root`` to a comparable fingerprint.

    - symlink -> ("link", target)          (never dereferenced)
    - file    -> ("file", exec_bit, sha1)
    - dir     -> ("dir",)
    """
    root = Path(root)
    out: dict = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Do not descend into symlinked directories; record them as links.
        real_dirs = []
        for d in dirnames:
            p = Path(dirpath) / d
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            else:
                out[rel] = ("dir",)
                real_dirs.append(d)
        dirnames[:] = real_dirs
        for f in filenames:
            p = Path(dirpath) / f
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", os.readlink(p))
            else:
                exec_bit = 1 if os.stat(p).st_mode & 0o100 else 0
                out[rel] = ("file", exec_bit, _sha1(p))
    return out


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_diff(a: Path, b: Path) -> list:
    """Return human-readable differences between trees ``a`` and ``b``.

    Empty list means byte-, mode-, and symlink-identical.
    """
    ea = _entries(a)
    eb = _entries(b)
    diffs: list = []
    for rel in sorted(set(ea) | set(eb)):
        va = ea.get(rel)
        vb = eb.get(rel)
        if va is None:
            diffs.append(f"extra in second tree: {rel}")
            continue
        if vb is None:
            diffs.append(f"missing in second tree: {rel}")
            continue
        if va[0] != vb[0]:
            diffs.append(f"type differs ({va[0]} vs {vb[0]}): {rel}")
            continue
        if va[0] == "link" and va[1] != vb[1]:
            diffs.append(f"symlink target differs ({va[1]} vs {vb[1]}): {rel}")
        elif va[0] == "file":
            if va[1] != vb[1]:
                diffs.append(f"mode/exec-bit differs: {rel}")
            if va[2] != vb[2]:
                diffs.append(f"content differs: {rel}")
    return diffs
