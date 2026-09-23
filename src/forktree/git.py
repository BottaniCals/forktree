"""forktree.git — sole boundary to the ``git`` and ``du`` executables.

Wraps ``subprocess.run`` with argv lists (no shell) so branch/path values cannot
inject commands. All other modules go through this single mockable seam
(REQ-4, REQ-28; SPEC §6 Security).
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from forktree.errors import GitError


__all__ = [
    "GitResult",
    "run_tool",
    "run_git",
    "git_version",
    "is_git_repo",
    "rev_parse",
    "rev_parse_verify",
    "status_porcelain",
    "last_commit_epoch",
    "default_branch",
    "worktree_add",
    "worktree_remove",
    "worktree_prune",
    "did_worktree_add_fail_busy",
    "branch_exists",
    "branch_delete",
    "is_branch_merged",
    "has_unpushed_commits",
    "worktree_list_porcelain",
    "count_objects_verbose",
    "du_bytes",
]


@dataclass(frozen=True, slots=True)
class GitResult:
    """Captured result of one subprocess invocation."""
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def _trim(text: str, *, max_lines: int = 3) -> str:
    """Tail a stderr text to a short single-line-ish string."""
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tail = lines[-max_lines:] if lines else []
    return " | ".join(tail)


def run_tool(
    argv: list[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float = 30.0,
    check: bool = True,
    subcommand: str = "?",
) -> GitResult:
    """Run an external command (argv list, no shell). On nonzero return + check=True, raise GitError."""
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd is not None else None,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError(
            subcommand=subcommand,
            reason=f"timeout after {timeout}s: {' '.join(argv)}",
            argv=tuple(argv),
            stderr_tail="",
        ) from e
    res = GitResult(
        argv=tuple(argv),
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    if check and proc.returncode != 0:
        raise GitError(
            subcommand=subcommand,
            reason=_trim(res.stderr) or f"exit {proc.returncode}",
            argv=res.argv,
            stderr_tail=_trim(res.stderr),
        )
    return res


def run_git(
    project_path: Optional[Path],
    *args: str,
    check: bool = True,
    timeout: float = 30.0,
    subcommand: str = "?",
) -> GitResult:
    """Build `git -C <project_path> <args>` and run it."""
    argv = ["git"]
    if project_path is not None:
        argv.extend(["-C", str(project_path)])
    argv.extend(args)
    return run_tool(argv, timeout=timeout, check=check, subcommand=subcommand)


def git_version() -> str:
    """Return `git --version` output (trimmed)."""
    res = run_tool(["git", "--version"], check=True, subcommand="doctor")
    return (res.stdout or "").strip() or (res.stderr or "").strip()


def is_git_repo(project_path: Path) -> bool:
    """True iff `git -C <p> rev-parse --git-dir` exits 0."""
    try:
        run_git(project_path, "rev-parse", "--git-dir", check=True, subcommand="doctor")
        return True
    except GitError:
        return False


def rev_parse(project_path: Path, rev: str) -> Optional[str]:
    """Resolve rev to a SHA. None if not resolvable."""
    try:
        res = run_git(project_path, "rev-parse", rev, check=True, subcommand="create")
    except GitError:
        return None
    out = (res.stdout or "").strip()
    return out or None


def rev_parse_verify(project_path: Path, rev: str) -> Optional[str]:
    """Resolve rev^{commit} to a SHA. None if not resolvable."""
    try:
        res = run_git(project_path, "rev-parse", f"{rev}^{{commit}}", check=True, subcommand="create")
    except GitError:
        return None
    out = (res.stdout or "").strip()
    return out or None


def status_porcelain(project_path: Path) -> str:
    """Return stdout of `git status --porcelain`. Empty string means clean."""
    res = run_git(project_path, "status", "--porcelain", check=True, subcommand="create")
    return res.stdout or ""


def last_commit_epoch(project_path: Path, rev: str) -> Optional[int]:
    """Return epoch seconds of the last commit on rev. None if no commits."""
    try:
        res = run_git(project_path, "log", "-1", "--format=%ct", rev, check=True, subcommand="list")
    except GitError:
        return None
    out = (res.stdout or "").strip()
    if not out.isdigit():
        return None
    return int(out)


def default_branch(project_path: Path) -> str:
    """Best-effort project default branch. Falls back to 'main'."""
    try:
        res = run_git(
            project_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
            check=True, subcommand="doctor",
        )
        ref = (res.stdout or "").strip()
        if ref.startswith("origin/"):
            return ref[len("origin/"):]
        return ref or "main"
    except GitError:
        return "main"


# ----- worktree/branch wrappers -----


def worktree_add(project_path: Path, path: Path, branch: str, base_sha: str) -> GitResult:
    """`git -C <project> worktree add <path> -B <branch> <base_sha>`."""
    return run_git(
        project_path, "worktree", "add", str(path), "-B", branch, base_sha,
        check=False, subcommand="create",
    )


def worktree_remove(project_path: Path, path: Path, *, force: bool = False) -> GitResult:
    """`git worktree remove [--force] <path>`."""
    argv = ["worktree", "remove"]
    if force:
        argv.append("--force")
    argv.append(str(path))
    return run_git(project_path, *argv, check=False, subcommand="remove")


def worktree_prune(project_path: Path) -> GitResult:
    """`git worktree prune`."""
    return run_git(project_path, "worktree", "prune", check=False, subcommand="create")


def did_worktree_add_fail_busy(res: GitResult) -> bool:
    """True iff a `worktree add` failed with 'worktree busy'."""
    msg = (res.stderr or "").lower()
    return "worktree busy" in msg


def branch_exists(project_path: Path, branch: str) -> bool:
    """True iff `git show-ref --verify refs/heads/<branch>` succeeds."""
    try:
        run_git(
            project_path, "show-ref", "--verify", f"refs/heads/{branch}",
            check=True, subcommand="create",
        )
        return True
    except GitError:
        return False


def branch_delete(project_path: Path, branch: str, *, force: bool = False) -> GitResult:
    """`git branch (-d|-D) <branch>`."""
    flag = "-D" if force else "-d"
    return run_git(project_path, "branch", flag, branch, check=False, subcommand="create")


def is_branch_merged(project_path: Path, branch: str, into: str) -> bool:
    """True iff <branch> is an ancestor of <into>."""
    try:
        run_git(
            project_path, "merge-base", "--is-ancestor", branch, into,
            check=True, subcommand="remove",
        )
        return True
    except GitError:
        return False


def has_unpushed_commits(project_path: Path, branch: str) -> bool:
    """True iff branch has commits not present on origin/<branch>."""
    try:
        run_git(
            project_path, "rev-parse", "--verify", f"origin/{branch}",
            check=True, subcommand="remove",
        )
    except GitError:
        # No origin tracking ref — treat as having unpushed commits.
        return True
    try:
        res = run_git(
            project_path,
            "log",
            f"origin/{branch}..{branch}",
            "--oneline",
            check=True,
            subcommand="remove",
        )
    except GitError:
        return True
    return bool((res.stdout or "").strip())


def worktree_list_porcelain(project_path: Path) -> list[dict[str, str]]:
    """Parse `git worktree list --porcelain` into a list of dicts."""
    res = run_git(project_path, "worktree", "list", "--porcelain", check=False, subcommand="list")
    if res.returncode != 0:
        return []
    blocks: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for raw in (res.stdout or "").splitlines():
        if raw.strip() == "":
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        if raw.startswith(" "):
            continue
        if " " in raw:
            k, v = raw.split(" ", 1)
        else:
            k, v = raw, ""
        cur[k] = v
    if cur:
        blocks.append(cur)
    return blocks


def count_objects_verbose(project_path: Path) -> dict[str, int]:
    """Parse `git count-objects --verbose`. `size` is in KiB, multiplied by 1024."""
    try:
        res = run_git(project_path, "count-objects", "--verbose", check=False, subcommand="create")
    except GitError:
        return {}
    out: dict[str, int] = {}
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        if not v:
            continue
        try:
            n = int(v.split()[0])
        except ValueError:
            continue
        # Verified correction: `size` is in KiB, convert to bytes.
        if k == "size":
            n *= 1024
        out[k] = n
    return out


def du_bytes(path: Path) -> Optional[int]:
    """Run `du -sb <path>`. Returns None if du is unavailable or empty output."""
    if not shutil.which("du"):
        return None
    try:
        res = run_tool(["du", "-sb", str(path)], check=True, subcommand="create")
    except GitError:
        return None
    out = (res.stdout or "").strip()
    if not out:
        return None
    first = out.split()[0]
    try:
        return int(first)
    except ValueError:
        return None
