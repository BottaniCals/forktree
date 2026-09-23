"""forktree.preflight — 7 ordered fail-fast checks + helpers (REQ-5..REQ-12, REQ-25)."""
from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from forktree import git as g
from forktree.config import Config
from forktree.errors import PreflightError, emit_stderr


__all__ = [
    "PreflightContext",
    "PreflightResult",
    "SLUG_RE",
    "is_valid_slug",
    "slugify",
    "estimate_checkout_bytes",
    "required_free_bytes",
    "check_project_path",
    "check_active_operation",
    "check_slug",
    "resolve_base_ref",
    "check_disk",
    "check_cap",
    "check_clean",
    "enforce_allowlist",
    "run_preflights",
]


SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_NON_SLUG: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_RE.fullmatch(slug))


def slugify(name: str) -> str:
    """Lower-case, [^a-z0-9]+ -> '-', trim leading/trailing '-'."""
    s = name.lower()
    s = _NON_SLUG.sub("-", s)
    s = s.strip("-")
    return s


@dataclass(frozen=True, slots=True)
class PreflightContext:
    project_path: Path      # already .resolve()d
    slug: str               # post-slugify if --name
    requested_ref: str      # --base-ref or cfg.base_ref
    cfg: Config
    skip_disk_check: bool = False
    skip_dirty_check: bool = False


@dataclass(frozen=True, slots=True)
class PreflightResult:
    name: str
    ok: bool
    reason: str | None = None
    elapsed_ms: float = 0.0


# ---------- helpers ----------


def estimate_checkout_bytes(project_path: Path) -> int:
    """du -sb with fallback to git count-objects --verbose."""
    sz = g.du_bytes(project_path)
    if sz is not None and sz > 0:
        return sz
    obj = g.count_objects_verbose(project_path)
    return int(obj.get("size", 0))


def required_free_bytes(volume_total: int, checkout_bytes: int, *, pct: int, floor_gib: int) -> int:
    """max(pct% * total, floor_gib GiB) + 2 * checkout."""
    pct_part = (pct * volume_total) // 100
    floor_part = floor_gib * (1024 ** 3)
    base = max(pct_part, floor_part)
    return base + 2 * max(0, int(checkout_bytes))


# ---------- checks ----------


def check_project_path(ctx: PreflightContext) -> None:
    p = ctx.project_path
    if not p.exists():
        raise PreflightError(
            check_name="project_path",
            reason=f"project_path does not exist: {p}",
            subcommand="create",
        )
    if not p.is_dir():
        raise PreflightError(
            check_name="project_path",
            reason=f"project_path is not a directory: {p}",
            subcommand="create",
        )
    if not g.is_git_repo(p):
        raise PreflightError(
            check_name="project_path",
            reason=f"not a git repository: {p}",
            subcommand="create",
        )


_ACTIVE_FILES: Final[tuple[tuple[str, str], ...]] = (
    (".git/index.lock", "git operation in progress: index.lock present"),
    (".git/rebase-merge", "git rebase in progress"),
    (".git/rebase-apply", "git rebase in progress"),
    (".git/MERGE_HEAD", "git merge in progress"),
    (".git/CHERRY_PICK_HEAD", "git cherry-pick in progress"),
    (".git/REVERT_HEAD", "git revert in progress"),
)


def check_active_operation(ctx: PreflightContext) -> None:
    git_dir = ctx.project_path / ".git"
    for rel, msg in _ACTIVE_FILES:
        if (git_dir / rel).exists():
            raise PreflightError(
                check_name="active_operation",
                reason=msg,
                subcommand="create",
            )


def check_slug(ctx: PreflightContext) -> None:
    if not is_valid_slug(ctx.slug):
        raise PreflightError(
            check_name="slug",
            reason=f"invalid slug: {ctx.slug}",
            subcommand="create",
        )


def resolve_base_ref(project_path: Path, ref: str) -> tuple[str, str]:
    """Try <ref> then origin/<ref>. Return (sha, resolved_ref_name). PreflightError on failure."""
    sha = g.rev_parse_verify(project_path, ref)
    if sha is not None:
        return sha, ref
    sha = g.rev_parse_verify(project_path, f"origin/{ref}")
    if sha is not None:
        return sha, f"origin/{ref}"
    raise PreflightError(
        check_name="base_ref",
        reason=f"base ref unresolved: {ref}",
        subcommand="create",
    )


def check_disk(ctx: PreflightContext) -> None:
    if ctx.skip_disk_check:
        return
    try:
        usage = shutil.disk_usage(ctx.project_path)
    except OSError:
        return
    checkout = estimate_checkout_bytes(ctx.project_path)
    need = required_free_bytes(
        usage.total,
        checkout,
        pct=ctx.cfg.warn_disk_pct,
        floor_gib=ctx.cfg.fail_disk_gib,
    )
    if usage.free < need:
        need_gib = need / (1024 ** 3)
        free_gib = usage.free / (1024 ** 3)
        raise PreflightError(
            check_name="disk",
            reason=(
                f"disk space: only {free_gib:.1f} GiB free at {ctx.project_path} "
                f"(need {need_gib:.1f} GiB); aborting"
            ),
            subcommand="create",
        )


def check_cap(ctx: PreflightContext) -> None:
    items = g.worktree_list_porcelain(ctx.project_path)
    n = sum(1 for it in items if it.get("worktree"))
    if n >= ctx.cfg.max_count:
        raise PreflightError(
            check_name="cap",
            reason=f"worktree cap reached: {n} >= {ctx.cfg.max_count}",
            subcommand="create",
        )


def check_clean(ctx: PreflightContext) -> None:
    if ctx.skip_dirty_check:
        out = g.status_porcelain(ctx.project_path)
        if out:
            emit_stderr("forktree: warning: --skip-dirty-check set; source tree is dirty")
        return
    out = g.status_porcelain(ctx.project_path)
    if out:
        raise PreflightError(
            check_name="clean",
            reason="source tree is dirty; pass --skip-dirty-check to override",
            subcommand="create",
        )


def enforce_allowlist(project_path: Path, allowed_root: str) -> None:
    """Realpath-prefix check. No-op when allowed_root empty."""
    if not allowed_root:
        return
    root = Path(allowed_root).expanduser().resolve()
    p = project_path.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise PreflightError(
            check_name="allowlist",
            reason=f"project path outside allowed_root: {p}",
            subcommand="create",
        )


# ---------- orchestration ----------


def _timed(name: str, fn, *args, **kwargs) -> PreflightResult:
    t0 = time.monotonic()
    try:
        fn(*args, **kwargs)
    except PreflightError as e:
        return PreflightResult(
            name=name,
            ok=False,
            reason=e.reason,
            elapsed_ms=(time.monotonic() - t0) * 1000.0,
        )
    return PreflightResult(
        name=name,
        ok=True,
        elapsed_ms=(time.monotonic() - t0) * 1000.0,
    )


_CHECKS = (
    ("project_path", check_project_path),
    ("active_operation", check_active_operation),
    ("slug", check_slug),
    ("base_ref", None),   # special: needs base_sha + resolved_ref name
    ("disk", check_disk),
    ("cap", check_cap),
    ("clean", check_clean),
)


def run_preflights(
    ctx: PreflightContext,
) -> tuple[list[PreflightResult], str, str]:
    """Run checks 1..7 in order. Fail-fast. Return (results, base_sha, effective_slug)."""
    results: list[PreflightResult] = []

    # allowlist first (not a numbered check)
    t0 = time.monotonic()
    try:
        enforce_allowlist(ctx.project_path, ctx.cfg.allowed_root)
    except PreflightError as e:
        results.append(PreflightResult("allowlist", False, e.reason, (time.monotonic() - t0) * 1000.0))
        raise
    results.append(PreflightResult("allowlist", True, elapsed_ms=(time.monotonic() - t0) * 1000.0))

    base_sha = ""
    resolved_name = ctx.requested_ref
    for name, fn in _CHECKS:
        if name == "base_ref":
            t0 = time.monotonic()
            try:
                base_sha, resolved_name = resolve_base_ref(ctx.project_path, ctx.requested_ref)
                results.append(PreflightResult(name, True, elapsed_ms=(time.monotonic() - t0) * 1000.0))
            except PreflightError as e:
                results.append(PreflightResult(name, False, e.reason, (time.monotonic() - t0) * 1000.0))
                raise
            continue
        t0 = time.monotonic()
        try:
            fn(ctx)
            results.append(PreflightResult(name, True, elapsed_ms=(time.monotonic() - t0) * 1000.0))
        except PreflightError as e:
            results.append(PreflightResult(name, False, e.reason, (time.monotonic() - t0) * 1000.0))
            raise

    return results, base_sha, ctx.slug
