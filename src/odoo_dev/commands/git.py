"""``odoo-dev git`` — ref hygiene and honest "did this ship?" answers.

Three questions this repeatedly gets wrong in a multi-branch Odoo project, and
the traps behind each:

**"Is this branch merged?"**  ``git branch --no-merged`` reads *local* refs. A
local branch that is behind its origin counterpart is reported as merged while
origin's tip is not, so the local form is the optimistic lie. Always fetch and
ask against remote refs.

**"Did this feature ship?"**  ``--contains`` / ``--no-merged`` answer a question
about *object identity*, not content. Anything squashed, cherry-picked or
re-created reads as unmerged forever even when the code is live. The only
honest answer diffs the files.

**"What are these stale refs?"**  Per-task clone workflows leave orphaned
remote-tracking refs behind. ``fetch --prune`` cannot clean them, because there
is no configured remote left to prune against -- they simply persist, and show
up in every ref listing as branches that do not exist.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Annotated, Optional

import typer

from odoo_dev.utils.console import error, info, success, warning

app = typer.Typer(
    name="git", help="Git ref hygiene and merge-state answers.", no_args_is_help=True
)


def _git(*args: str, check: bool = True) -> str:
    """Run a git command and return stripped stdout."""
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout.strip()


def _ok(*args: str) -> bool:
    """True when the git command exits 0 (for --is-ancestor and friends)."""
    return (
        subprocess.run(["git", *args], capture_output=True, text=True).returncode == 0
    )


def _configured_remotes() -> set[str]:
    return {ln for ln in _git("remote").splitlines() if ln}


@app.command(name="prune-refs")
def prune_refs(
    apply: Annotated[
        bool, typer.Option("--apply", help="Actually delete. Default is a dry run.")
    ] = False,
    namespaces: Annotated[
        Optional[str],
        typer.Option(
            "--namespaces",
            help="Comma-separated extra ref namespaces to sweep, e.g. 'refs/test,refs/wip'.",
        ),
    ] = None,
) -> None:
    """Delete remote-tracking refs whose remote no longer exists, plus custom namespaces.

    Per-task clone workflows leave refs like
    ``refs/remotes/task-3629/feature/...`` behind. ``git fetch --prune`` never
    removes them: pruning happens per configured remote, and that remote is
    gone, so nothing owns them. They then show up forever in ref listings and
    in any script that walks ``refs/remotes``.

    Dry-run by default. Deletion of a ref is not recoverable through the reflog
    once the objects are gc'd, so nothing is removed without ``--apply``.
    """
    remotes = _configured_remotes()
    if not remotes:
        error("no configured remotes -- refusing to guess what is stale")
        raise typer.Exit(2)

    info(f"configured remotes: {', '.join(sorted(remotes))}")

    doomed: list[str] = []
    for ref in _git("for-each-ref", "--format=%(refname)", "refs/remotes").splitlines():
        # refs/remotes/<remote>/<branch...>
        parts = ref.split("/", 3)
        if len(parts) < 4:
            continue
        if parts[2] not in remotes:
            doomed.append(ref)

    for ns in (n.strip() for n in (namespaces or "").split(",") if n.strip()):
        doomed.extend(
            r for r in _git("for-each-ref", "--format=%(refname)", ns).splitlines() if r
        )

    if not doomed:
        success("nothing stale -- every ref belongs to a configured remote")
        return

    warning(f"{len(doomed)} stale ref(s):")
    for r in doomed:
        info(f"  {r}")

    if not apply:
        info("\nDRY RUN -- nothing deleted. Re-run with --apply.")
        return

    # update-ref requires FULLY-QUALIFIED refnames. It deliberately will not
    # DWIM-shorten the way checkout/log/branch do, because deleting the wrong
    # ref is unrecoverable -- so it refuses anything that is not already a
    # valid ref path rather than guessing the namespace.
    for r in doomed:
        _git("update-ref", "-d", r)
        success(f"deleted {r}")
    info("\nRun `git gc --prune=now` to reclaim the objects.")


@app.command()
def unmerged(
    target: Annotated[
        str, typer.Argument(help="Target branch, e.g. 19.0-prod")
    ] = "19.0-prod",
    remote: Annotated[str, typer.Option("--remote", help="Remote name")] = "origin",
    no_fetch: Annotated[
        bool, typer.Option("--no-fetch", help="Skip the fetch --prune first")
    ] = False,
) -> None:
    """List remote branches not merged into TARGET, using remote refs only.

    This is the form that tells the truth. ``git branch --no-merged`` consults
    local refs, which are only as good as your last fetch: a local branch
    sitting behind its origin counterpart is reported as merged while origin's
    tip is not, and nothing warns you. That discrepancy is how a stale tip gets
    merged into a release and quietly drops commits.

    Object identity only, so treat the output as candidates. A squashed or
    cherry-picked branch appears here forever -- confirm with ``git shipped``.
    """
    if not no_fetch:
        info(f"fetching {remote} --prune ...")
        _git("fetch", "--prune", "--quiet", remote)

    tgt = f"{remote}/{target}"
    if not _ok("rev-parse", "--verify", tgt):
        error(f"{tgt} does not exist")
        raise typer.Exit(2)

    rows: list[tuple[str, str, str]] = []
    for line in _git(
        "for-each-ref",
        "--format=%(refname:short)%09%(committerdate:short)%09%(authorname)",
        f"refs/remotes/{remote}",
    ).splitlines():
        ref, date, author = (line.split("\t") + ["", ""])[:3]
        short = ref[len(remote) + 1 :]
        if short in ("HEAD", target):
            continue
        if _ok("merge-base", "--is-ancestor", ref, tgt):
            continue
        rows.append((short, date, author))

    if not rows:
        success(f"every {remote} branch is merged into {target}")
        return

    warning(f"{len(rows)} branch(es) not merged into {target} (by object identity):")
    for short, date, author in sorted(rows, key=lambda r: r[1], reverse=True):
        info(f"  {date}  {short:<52} {author}")
    info(
        "\nSquashed/cherry-picked work also lands here. Verify with `odoo-dev git shipped`."
    )


@app.command()
def shipped(
    ref: Annotated[str, typer.Argument(help="Branch or commit that may have shipped")],
    paths: Annotated[
        Optional[list[str]],
        typer.Argument(
            help="Files/dirs to compare. Omit to use the files REF itself changed."
        ),
    ] = None,
    target: Annotated[
        str, typer.Option("--target", help="Where it should have landed")
    ] = "origin/19.0-prod",
    grep: Annotated[
        Optional[list[str]],
        typer.Option(
            "--grep",
            help="Marker string that must appear in TARGET's copy. Repeatable. "
            "This is what actually settles 'did it ship' when paths differ.",
        ),
    ] = None,
) -> None:
    """Did REF's work reach TARGET? Answered by content, never by ancestry.

    ``--contains`` and ``--no-merged`` compare commit objects, so a squashed,
    cherry-picked or re-created branch reads as unmerged even when its code is
    live in production -- and as a result people go looking for "missing"
    features that shipped months ago.

    With no paths given it derives them -- the files REF itself changed -- which
    is almost always the right set. It then diffs those between REF and TARGET
    and reports what actually differs. An empty diff means the content is identical. A non-empty diff is
    not proof of absence either: the target may simply have moved on since,
    which is why the per-path detail is printed rather than a verdict.
    """
    for r in (ref, target):
        if not _ok("rev-parse", "--verify", r):
            error(f"{r} does not exist")
            raise typer.Exit(2)

    # Ancestry is ASYMMETRIC evidence, which is the whole subtlety here.
    #
    #   True  -> conclusive. Every commit in REF is reachable from TARGET, so
    #            the work is there by definition. A content diff can only muddy
    #            a settled answer, because the target may have moved on and
    #            "differs" would then read as doubt.
    #   False -> proves nothing. Squashed, cherry-picked or re-created work is
    #            never an ancestor even when it is live in production. Fall
    #            through to content, which is the only honest test.
    is_ancestor = _ok("merge-base", "--is-ancestor", ref, target)

    if is_ancestor:
        success(
            f"{ref} IS an ancestor of {target} -- every commit is reachable, "
            f"so this work shipped."
        )
        if not grep:
            info("  Ancestry is conclusive in this direction; no content check needed.")
            return
        # `--grep` is an explicit content question, so honour it anyway: the
        # caller may be checking that a marker SURVIVED, not merely that the
        # commits landed. Reachable does not mean un-reverted.
        info(
            "  Ancestry settles reachability; checking your markers anyway, "
            "since a later commit can still have removed them."
        )
    else:
        info(f"ancestry: {ref} is NOT an ancestor of {target}")
        info("  (proves nothing on its own -- content below is what counts)")

    # Deriving the paths is almost always what you want: git already knows
    # which files REF touched, and naming them by hand risks checking the wrong
    # ones. A whole-tree path such as `.` always differs against a target that
    # has moved on, which cannot distinguish "did not ship" from "shipped, then
    # the repo continued".
    if not paths:
        if is_ancestor:
            # merge-base(REF, TARGET) == REF here, so that diff is empty by
            # construction. What REF *introduced* is the diff against its first
            # parent -- which for a merge commit is the branch it merged in.
            spec = (f"{ref}^1", ref)
        else:
            base = _git("merge-base", ref, target, check=False)
            if not base:
                error(
                    f"no common ancestor between {ref} and {target} -- pass paths explicitly"
                )
                raise typer.Exit(2)
            spec = (base, ref)
        paths = [
            p for p in _git("diff", "--name-only", *spec, check=False).splitlines() if p
        ]
        if not paths:
            success(f"{ref} changes no files -- nothing to compare.")
            return
        info(
            f"comparing the {len(paths)} file(s) {ref} changed "
            f"(derived; pass paths to override)"
        )
    elif any(p in (".", "./", "") for p in paths):
        warning(
            "  '.' compares the entire tree and will always differ -- omit the "
            "path argument to compare only what REF changed."
        )

    identical, differs, missing = [], [], []
    for p in paths:
        in_ref = _ok("cat-file", "-e", f"{ref}:{p}")
        in_tgt = _ok("cat-file", "-e", f"{target}:{p}")
        if in_ref and not in_tgt:
            missing.append(p)
        elif not _git("diff", "--name-only", ref, target, "--", p, check=False):
            identical.append(p)
        else:
            differs.append(p)

    for p in identical:
        success(f"  identical   {p}")
    for p in differs:
        warning(f"  differs     {p}")
    for p in missing:
        error(f"  ABSENT from {target}: {p}")

    # Markers are the decisive test when paths differ. A file that has moved on
    # still contains the feature's fingerprints if the feature shipped; if the
    # markers are gone, the work was reverted or never landed.
    missing_markers: list[str] = []
    if grep:
        info("")
        for pat in grep:
            hits = 0
            for p in paths:
                if not _ok("cat-file", "-e", f"{target}:{p}"):
                    continue
                body = _git("show", f"{target}:{p}", check=False)
                hits += sum(1 for ln in body.splitlines() if pat in ln)
            if hits:
                success(f"  marker present in {target}: {pat!r} ({hits} line(s))")
            else:
                error(f"  marker ABSENT from {target}: {pat!r}")
                missing_markers.append(pat)

    if missing:
        info(
            "\nPaths absent from the target are the real signal -- that work did not ship."
        )
        raise typer.Exit(1)
    if missing_markers:
        info(
            "\nMarkers absent -- this work is NOT in the target, whatever ancestry says."
        )
        raise typer.Exit(1)
    if grep and differs:
        if is_ancestor:
            success(
                "\nPaths differ because the target moved on, but every marker "
                "survived: the work is reachable AND still present."
            )
        else:
            success(
                "\nPaths differ but every marker is present: the work SHIPPED and "
                "the target has since moved on. This is exactly the case ancestry "
                "reports wrongly."
            )
        return
    if differs:
        info("\nDiffering paths may just mean the target moved on. Inspect with:")
        for p in differs:
            info(f"  git diff {ref} {target} -- {p}")
    else:
        success("\nEvery path matches -- this work is present in the target.")


# --- sweep -------------------------------------------------------------------
#
# The classification ladder below is the one that survived a real cleanup of two
# long-lived client repos (89 and 41 branches). Its shape is dictated by what
# each test can actually prove:
#
#   KEEP          long-lived lines. Never a candidate, whatever their age.
#   IN-FLIGHT     an open MR/PR names it as source. Deleting one of these closes
#                 the request out from under its author.
#   CONTAINED     `merge-base --is-ancestor` says every commit is reachable from
#                 a branch we keep. This is the ONLY class that proves deletion
#                 loses nothing, and so the only one pre-checked.
#   STALE-BY-BASE not contained, and its diff against the target mass-deletes
#                 paths the target owns -- the fingerprint of a branch cut before
#                 a structural change (e.g. submodules -> vendored files). These
#                 look mergeable and are not: an MR would propose deleting the
#                 target's tree. Never auto-select.
#   UNKNOWN       everything else. Genuinely needs a human.
#
# Deliberately absent: proving supersession by content across a base gap. The
# obvious implementation -- diff the paths the old branch touched against its
# replacement -- reads as "identical" for branches whose fork point predates a
# tree reorganisation, because the derived path set is dominated by the
# reorganisation rather than the branch's own work. `odoo-dev git shipped`
# answers that question properly, per branch, with markers. A branch superseded
# by an open MR becomes CONTAINED for free once that MR merges, so the honest
# move is to wait rather than guess.

_KEEP_RE = re.compile(r"^(\d+\.\d+(-(prod|staging))?|main|master)$")


def _default_targets(remote: str) -> list[str]:
    """Long-lived lines, by name. Version branches plus main/master."""
    out = []
    for line in _git(
        "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}"
    ).splitlines():
        short = line[len(remote) + 1 :]
        if short and short != "HEAD" and _KEEP_RE.match(short):
            out.append(short)
    return sorted(out)


def _open_request_sources(remote: str) -> tuple[set[str], Optional[str]]:
    """Source branches of open MRs/PRs. Returns (branches, warning_or_None).

    JSON endpoints only. Scraping the human-readable `glab mr list` table looks
    easier and is a trap: its header line ("... (Page 1)") satisfies a naive
    "text in parentheses" match and yields a phantom branch named `Page 1`.
    """
    url = _git("remote", "get-url", remote, check=False)
    if not url:
        return set(), f"no URL for remote {remote!r} -- skipping request lookup"

    if "github" in url:
        tool, args = "gh", [
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "headRefName",
        ]
    else:
        tool, args = "glab", [
            "api",
            "projects/:id/merge_requests?state=opened&per_page=100",
        ]

    if not shutil.which(tool):
        return set(), (
            f"{tool} not installed -- cannot see open requests. Branches with an "
            f"open MR/PR will appear as UNKNOWN, not as safe to delete."
        )

    r = subprocess.run([tool, *args], capture_output=True, text=True)
    if r.returncode != 0:
        return set(), (
            f"{tool} failed ({(r.stderr or r.stdout).strip().splitlines()[:1]}) -- "
            f"treating all branches as having no open request."
        )
    try:
        payload = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return set(), f"could not parse {tool} output as JSON"

    key = "headRefName" if tool == "gh" else "source_branch"
    return {item[key] for item in payload if item.get(key)}, None


def _missing_share(target: str, ref: str) -> tuple[int, float]:
    """(count, share) of TARGET's paths that REF does not have.

    The SHARE is what distinguishes the two cases, and using the raw count
    instead is a false-positive generator:

      * a branch merely BEHIND a fast-moving target legitimately lacks whatever
        was added since -- dozens of files, but a tiny fraction of the tree;
      * a branch cut before a structural change (submodules -> vendored files,
        a big reorganisation) lacks most of the tree.

    Only the second is dangerous to merge, and only a ratio separates them.
    """
    out = _git("diff", "--name-status", target, ref, check=False)
    missing = sum(1 for ln in out.splitlines() if ln.startswith("D\t"))
    total = len(_git("ls-tree", "-r", "--name-only", target, check=False).splitlines())
    return missing, (missing / total if total else 0.0)


@app.command()
def sweep(
    targets: Annotated[
        Optional[list[str]],
        typer.Option(
            "--target",
            "-t",
            help="Branch that counts as 'kept'. Repeatable. "
            "Default: version branches (19.0, 19.0-prod, 19.0-staging...) plus main/master.",
        ),
    ] = None,
    remote: Annotated[str, typer.Option("--remote", help="Remote name")] = "origin",
    apply: Annotated[
        bool, typer.Option("--apply", help="Actually delete. Default is a dry run.")
    ] = False,
    no_fetch: Annotated[
        bool, typer.Option("--no-fetch", help="Skip the fetch --prune first")
    ] = False,
    check_requests: Annotated[
        bool,
        typer.Option(
            "--check-requests/--no-check-requests",
            help="Ask glab/gh which branches have an open MR/PR.",
        ),
    ] = True,
    stale_ratio: Annotated[
        float,
        typer.Option(
            "--stale-ratio",
            help="Share of the target's tree a branch must be missing to count "
            "as STALE-BY-BASE. A branch that is merely behind lacks a few "
            "files; one cut before a tree change lacks most of them.",
        ),
    ] = 0.25,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Skip the picker and take exactly the CONTAINED set.",
        ),
    ] = False,
) -> None:
    """Classify remote branches and delete the ones you select. DRY RUN unless --apply.

    Writes a manifest of every branch with its SHA *before* deleting anything,
    so a branch removed here is restorable with::

        git push <remote> <sha>:refs/heads/<branch>

    That matters for anything outside CONTAINED: once such a branch is gone its
    commits are unreachable, and the SHA in the manifest is the only way back.
    """
    if not no_fetch:
        info(f"fetching {remote} --prune ...")
        _git("fetch", "--prune", "--quiet", remote)

    keep = list(targets) if targets else _default_targets(remote)
    if not keep:
        error(
            "no target branches found -- pass --target explicitly. Refusing to "
            "classify anything as deletable with nothing to measure against."
        )
        raise typer.Exit(2)
    info(f"targets: {', '.join(keep)}")

    for t in keep:
        if not _ok("rev-parse", "--verify", f"{remote}/{t}"):
            error(f"{remote}/{t} does not exist")
            raise typer.Exit(2)

    in_flight: set[str] = set()
    if check_requests:
        in_flight, warn = _open_request_sources(remote)
        if warn:
            warning(f"  {warn}")
        else:
            info(f"  {len(in_flight)} branch(es) have an open MR/PR")

    rows: list[dict] = []
    for line in _git(
        "for-each-ref",
        "--format=%(refname:short)%09%(objectname)%09%(committerdate:short)",
        f"refs/remotes/{remote}",
    ).splitlines():
        ref, sha, date = (line.split("\t") + ["", ""])[:3]
        short = ref[len(remote) + 1 :]
        if not short or short == "HEAD":
            continue
        if short in keep:
            cls, why = "KEEP", "long-lived line"
        elif short in in_flight:
            cls, why = "IN-FLIGHT", "open MR/PR names it as source"
        else:
            holder = next(
                (
                    t
                    for t in keep
                    if _ok("merge-base", "--is-ancestor", ref, f"{remote}/{t}")
                ),
                None,
            )
            if holder:
                cls, why = "CONTAINED", f"contained in {remote}/{holder}"
            else:
                worst_n, worst_share, worst_t = 0, 0.0, ""
                for t in keep:
                    n, share = _missing_share(f"{remote}/{t}", ref)
                    if share > worst_share:
                        worst_n, worst_share, worst_t = n, share, t
                if worst_share >= stale_ratio:
                    cls = "STALE-BY-BASE"
                    why = (
                        f"lacks {worst_n} paths ({worst_share:.0%}) of {worst_t} "
                        f"-- cut before a tree change"
                    )
                else:
                    cls, why = "UNKNOWN", "not contained; needs a human"
        rows.append({"branch": short, "sha": sha, "date": date, "cls": cls, "why": why})

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["cls"]] = counts.get(r["cls"], 0) + 1
    info("")
    for cls in ("KEEP", "IN-FLIGHT", "CONTAINED", "STALE-BY-BASE", "UNKNOWN"):
        if counts.get(cls):
            info(f"  {cls:<14} {counts[cls]}")

    candidates = [r for r in rows if r["cls"] not in ("KEEP", "IN-FLIGHT")]
    if not candidates:
        success("\nnothing to sweep -- every branch is a keeper or in flight")
        return

    man = _write_manifest(rows, remote)
    success(f"\nmanifest: {man}")

    contained = [r for r in candidates if r["cls"] == "CONTAINED"]
    if non_interactive or not sys.stdin.isatty():
        chosen = [r["branch"] for r in contained]
        info(f"non-interactive: taking the {len(chosen)} CONTAINED branch(es) only")
    else:
        chosen = _pick(candidates, apply=apply)

    if not chosen:
        info("nothing selected -- done")
        return

    warning(f"\n{len(chosen)} branch(es) selected:")
    for b in chosen:
        r = next(x for x in rows if x["branch"] == b)
        info(f"  {r['cls']:<14} {b}")

    if not apply:
        info("\nDRY RUN -- nothing deleted. Re-run with --apply.")
        return

    # Re-verify containment immediately before deleting: the survey and the
    # delete are separated by however long the picker was open, and another
    # session pushing in that window is not hypothetical.
    for b in chosen:
        r = next(x for x in rows if x["branch"] == b)
        if r["cls"] == "CONTAINED":
            holder = r["why"].rsplit("/", 1)[-1]
            if not _ok(
                "merge-base", "--is-ancestor", f"{remote}/{b}", f"{remote}/{holder}"
            ):
                error(
                    f"{b} is no longer contained in {holder} -- aborting, nothing deleted"
                )
                raise typer.Exit(1)

    failed = []
    for b in chosen:
        for attempt in (1, 2, 3):
            r = subprocess.run(
                ["git", "push", remote, "--delete", b], capture_output=True, text=True
            )
            if r.returncode == 0:
                success(f"  deleted {b}")
                break
            if attempt < 3:
                time.sleep(attempt)
        else:
            error(f"  FAILED {b}: {(r.stderr or r.stdout).strip().splitlines()[-1:]}")
            failed.append(b)

    if failed:
        error(f"\n{len(failed)} deletion(s) failed -- rerun to retry them")
        raise typer.Exit(1)
    success(f"\n{len(chosen)} branch(es) deleted. Restore any of them with:")
    info(f"  git push {remote} <sha>:refs/heads/<branch>   # SHAs in {man}")


def _write_manifest(rows: list[dict], remote: str) -> str:
    """Record every branch and SHA under .git/ before anything is deleted."""
    d = os.path.join(_git("rev-parse", "--git-dir"), "odoo-dev")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"sweep-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.tsv")
    with open(path, "w") as fh:
        fh.write(
            f"# odoo-dev git sweep -- {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}\n"
        )
        fh.write(f"# restore with: git push {remote} <sha>:refs/heads/<branch>\n")
        fh.write("branch\tsha\tlast_commit\tclass\tevidence\n")
        for r in rows:
            fh.write(
                f"{r['branch']}\t{r['sha']}\t{r['date']}\t{r['cls']}\t{r['why']}\n"
            )
    return path


def _pick(candidates: list[dict], apply: bool = False) -> list[str]:
    """Checkbox picker. CONTAINED pre-checked; nothing else is."""
    import questionary

    order = {"CONTAINED": 0, "STALE-BY-BASE": 1, "UNKNOWN": 2}
    ordered = sorted(candidates, key=lambda r: (order.get(r["cls"], 9), r["date"]))
    choices = [
        questionary.Choice(
            title=f"{r['cls']:<14} {r['date']}  {r['branch']:<48} {r['why']}",
            value=r["branch"],
            checked=r["cls"] == "CONTAINED",
        )
        for r in ordered
    ]
    prompt = (
        "Select branches to DELETE (space toggles, enter confirms):"
        if apply
        else "Select branches (DRY RUN -- the selection is only reported):"
    )
    picked = questionary.checkbox(prompt, choices=choices).ask()
    return picked or []
