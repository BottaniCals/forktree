"""forktree.worktree — create / list / remove / gc orchestration (REQ-13..REQ-18)."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from forktree import git as g
from forktree import output
from forktree.config import Config
from forktree.errors import GitError, PreflightError, emit_stderr
from forktree.preflight import PreflightContext, PreflightResult


__all__ = [
    "WorktreeInfo",
    "CreateResult",
    "GcResult",
    "candidate_path",
    "create",
    "list_worktrees",
    "remove",
    "gc",
    "run_setup_hook",
    "rollback",
]


_GIB = 1024 ** 3
_MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class WorktreeInfo:
    slug: str
    path: Path
    branch: str
    dirty: bool
    age_days: int
    head_sha: str | None = None
    merged: bool | None = None


@dataclass(frozen=True, slots=True)
class CreateResult:
    path: Path
    branch: str
    base_sha: str
    used_setup_hook: bool


@dataclass(frozen=True, slots=True)
class GcResult:
    removed: list[str]
    failed: list[tuple[str, str]]
    pruned: bool


def candidate_path(project_path: Path, cfg: Config, slug: str, base_sha: str, attempt: int) -> Path:
    base = project_path / cfg.worktrees_dir
    if attempt <= 0:
        return base / slug
    suffix = base_sha[:7]
    return base / f"{slug}-{suffix}"


def _ensure_branch_clean_on_failure(project_path: Path, branch: str, *, branch_created: bool) -> None:
    if not branch_created:
        return
    try:
        g.branch_delete(project_path, branch, force=True)
    except GitError:
        pass


def rollback(project_path: Path, worktree_path: Path, branch: str, *, branch_created: bool) -> None:
    """Best-effort, idempotent cleanup after a failed `create`."""
    try:
        g.worktree_remove(project_path, worktree_path, force=True)
    except GitError:
        pass
    try:
        g.worktree_prune(project_path)
    except GitError:
        pass
    _ensure_branch_clean_on_failure(project_path, branch, branch_created=branch_created)


def run_setup_hook(project_path: Path, worktree_path: Path, script_rel: str, base_ref: str) -> None:
    """Resolve and run an opt-in setup script. Missing -> warn+continue. Not executable -> GitError exit 2. Nonzero/timeout -> GitError."""
    script_path = (project_path / script_rel).resolve()
    if not script_path.exists():
        emit_stderr(f"forktree: warning: setup_script not found: {script_path}")
        return
    if not script_path.is_file() or not os.access(script_path, os.X_OK):
        raise GitError(
            subcommand="create",
            reason=f"setup_script not executable: {script_path}",
            argv=("setup", str(script_path)),
            stderr_tail="",
        )
    env = dict(os.environ)
    env["FORKTREE_WORKTREE_PATH"] = str(worktree_path)
    env["FORKTREE_PROJECT_PATH"] = str(project_path)
    env["FORKTREE_BASE_REF"] = base_ref
    try:
        proc = subprocess.run(
            [str(script_path)],
            cwd=str(worktree_path),
            env=env,
            shell=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError(
            subcommand="create",
            reason=f"setup_script failed: timeout after 120s",
            argv=("setup", str(script_path)),
            stderr_tail="",
        ) from e
    if proc.returncode != 0:
        tail_lines = (proc.stderr or "").splitlines()
        tail = " | ".join(ln.strip() for ln in tail_lines[-3:] if ln.strip())
        raise GitError(
            subcommand="create",
            reason=f"setup_script failed: {tail or f'exit {proc.returncode}'}",
            argv=("setup", str(script_path)),
            stderr_tail=tail,
        )


def _post_verify(project_path: Path, worktree_path: Path, base_sha: str, branch: str, branch_created: bool) -> None:
    actual = g.rev_parse(worktree_path, "HEAD")
    if actual != base_sha:
        rollback(project_path, worktree_path, branch, branch_created=branch_created)
        raise GitError(
            subcommand="create",
            reason=f"post-verify failed: HEAD {actual} != expected {base_sha}",
            argv=("git", "-C", str(worktree_path), "rev-parse", "HEAD"),
            stderr_tail="",
        )


def create(
    ctx: PreflightContext,
    results: list[PreflightResult],
    base_sha: str,
    effective_slug: str,
) -> CreateResult:
    """Run the create execution step: collision retry, worktree add, post-verify, setup hook."""
    branch = effective_slug
    used_hook = False

    for attempt in range(_MAX_ATTEMPTS):
        candidate = candidate_path(ctx.project_path, ctx.cfg, effective_slug, base_sha, attempt)
        if not candidate.exists():
            break
    else:
        raise PreflightError(
            check_name="collision",
            reason=f"worktree path collision after {_MAX_ATTEMPTS} attempts",
            subcommand="create",
        )

    branch_created = not g.branch_exists(ctx.project_path, branch)

    add_res = g.worktree_add(ctx.project_path, candidate, branch, base_sha)
    if add_res.returncode != 0:
        # If worktree add created some state, clean it up.
        rollback(ctx.project_path, candidate, branch, branch_created=branch_created)
        raise GitError(
            subcommand="create",
            reason=(add_res.stderr or "").strip().splitlines()[-1] if add_res.stderr else f"exit {add_res.returncode}",
            argv=add_res.argv,
            stderr_tail=(add_res.stderr or "").strip(),
        )

    _post_verify(ctx.project_path, candidate, base_sha, branch, branch_created)

    if ctx.cfg.setup_script:
        try:
            run_setup_hook(ctx.project_path, candidate, ctx.cfg.setup_script, ctx.requested_ref)
            used_hook = True
        except GitError:
            rollback(ctx.project_path, candidate, branch, branch_created=branch_created)
            raise

    return CreateResult(
        path=candidate.resolve(),
        branch=branch,
        base_sha=base_sha,
        used_setup_hook=used_hook,
    )


def _info_from_porcelain(project_path: Path, cfg: Config, blocks: list[dict[str, str]]) -> list[WorktreeInfo]:
    """Build WorktreeInfo rows from `git worktree list --porcelain` blocks."""
    rows: list[WorktreeInfo] = []
    wt_dir = (project_path / cfg.worktrees_dir).resolve()
    for b in blocks:
        path_str = b.get("worktree", "")
        if not path_str:
            continue
        path = Path(path_str).resolve()
        # Only worktrees under <project>/<worktrees_dir> are reported.
        try:
            path.relative_to(wt_dir)
        except ValueError:
            continue
        slug = path.name
        branch = b.get("branch", "")
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/"):]
        elif branch == "":
            branch = "detached"
        head_sha = b.get("HEAD")
        dirty = bool(g.status_porcelain(path).strip())
        rev_for_age = branch if branch != "detached" else head_sha or "HEAD"
        epoch = g.last_commit_epoch(path, rev_for_age) if rev_for_age else None
        if epoch is None:
            age_days = 0
        else:
            age_days = max(0, int((int(time.time()) - epoch) // 86400))
        rows.append(WorktreeInfo(
            slug=slug,
            path=path,
            branch=branch,
            dirty=dirty,
            age_days=age_days,
            head_sha=head_sha,
        ))
    return rows


def list_worktrees(project_path: Path, cfg: Config) -> list[WorktreeInfo]:
    blocks = g.worktree_list_porcelain(project_path)
    return _info_from_porcelain(project_path, cfg, blocks)


def remove(
    project_path: Path,
    slug: str,
    *,
    force_if_lossless: bool,
    cfg: Config,
    verbose: bool,
) -> None:
    """Gate order: exists → clean → (merged OR (no unpushed AND --force-if-lossless))."""
    wt_path = (project_path / cfg.worktrees_dir / slug).resolve()
    if not wt_path.exists():
        raise PreflightError(check_name="remove", reason=f"no such worktree: {slug}", subcommand="remove")

    if g.status_porcelain(wt_path).strip():
        raise PreflightError(check_name="remove", reason=f"worktree is dirty: {slug}", subcommand="remove")

    blocks = {Path(b.get("worktree", "")).resolve(): b for b in g.worktree_list_porcelain(project_path)}
    block = blocks.get(wt_path)
    branch = ""
    if block is not None:
        branch = block.get("branch", "")
        if branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/"):]

    default = g.default_branch(project_path)
    merged = bool(branch) and g.is_branch_merged(project_path, branch, default) if branch else False
    unpushed = bool(branch) and g.has_unpushed_commits(project_path, branch) if branch else True

    if not merged and unpushed and not force_if_lossless:
        raise PreflightError(
            check_name="remove",
            reason=f"branch not merged and has unpushed commits: {branch}",
            subcommand="remove",
        )

    res = g.worktree_remove(project_path, wt_path)
    if g.did_worktree_add_fail_busy(res) or (res.returncode != 0 and "busy" in (res.stderr or "").lower()):
        time.sleep(0.2)
        res = g.worktree_remove(project_path, wt_path)
    if res.returncode != 0:
        raise GitError(
            subcommand="remove",
            reason=(res.stderr or "").strip().splitlines()[-1] if res.stderr else f"exit {res.returncode}",
            argv=res.argv,
            stderr_tail=(res.stderr or "").strip(),
        )

    if branch:
        try:
            g.branch_delete(project_path, branch, force=False)
        except GitError:
            pass

    parent = wt_path.parent
    try:
        if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def gc(
    project_path: Path,
    *,
    idle_days: int | None,
    dry_run: bool,
    cfg: Config,
    verbose: bool,
) -> GcResult:
    """Filter = idle ∧ clean ∧ merged. --dry-run puts sorted slugs in `removed` and returns."""
    threshold = idle_days if idle_days is not None else cfg.gc_idle_days
    default = g.default_branch(project_path)
    rows = list_worktrees(project_path, cfg)
    plan: list[str] = []
    for r in rows:
        rev = r.branch if r.branch != "detached" else (r.head_sha or "HEAD")
        epoch = g.last_commit_epoch(project_path, rev) if rev else None
        age = 0 if epoch is None else max(0, (int(time.time()) - epoch) // 86400)
        clean = not r.dirty
        merged = r.branch != "detached" and bool(r.branch) and g.is_branch_merged(project_path, r.branch, default)
        if age >= threshold and clean and merged:
            plan.append(r.slug)
    plan_sorted = sorted(set(plan))

    if dry_run:
        return GcResult(removed=plan_sorted, failed=[], pruned=False)

    removed: list[str] = []
    failed: list[tuple[str, str]] = []
    for slug in plan_sorted:
        try:
            remove(project_path, slug, force_if_lossless=True, cfg=cfg, verbose=verbose)
            removed.append(slug)
        except (PreflightError, GitError) as e:
            failed.append((slug, e.reason))

    pruned = False
    if removed and cfg.gc_prune:
        try:
            g.worktree_prune(project_path)
            pruned = True
        except GitError:
            pruned = False

    return GcResult(removed=removed, failed=failed, pruned=pruned)
