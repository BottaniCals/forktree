"""forktree.output — stdout/stderr sinks and renderers.

Only module allowed to write to sys.stdout / sys.stderr. Concentrating both sinks
here makes the "stdout = data only" rule structurally enforceable (REQ-2, REQ-28).
"""
from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, IO, Sequence

if TYPE_CHECKING:
    from forktree.worktree import WorktreeInfo


__all__ = [
    "emit_stdout",
    "emit_stderr",
    "print_path",
    "is_tty",
    "use_color",
    "human_table",
    "porcelain_rows",
    "json_rows",
    "render_gc_plan",
]


def emit_stdout(text: str) -> None:
    """Append exactly one newline and write to stdout."""
    if not text.endswith("\n"):
        text = text + "\n"
    sys.stdout.write(text)
    sys.stdout.flush()


def emit_stderr(text: str) -> None:
    """Append exactly one newline and write to stderr."""
    if not text.endswith("\n"):
        text = text + "\n"
    sys.stderr.write(text)
    sys.stderr.flush()


def print_path(path) -> None:
    """The only stdout write used by `create`: absolute path, one line."""
    emit_stdout(str(path))


def is_tty(stream: IO[str] | None = None) -> bool:
    """True iff stream is a TTY. Defaults to stdout."""
    s = stream if stream is not None else sys.stdout
    try:
        return bool(s.isatty())
    except Exception:
        return False


def use_color(stream: IO[str] | None = None) -> bool:
    """TTY + NO_COLOR/--no-color not set."""
    import os
    if os.environ.get("NO_COLOR"):
        return False
    return is_tty(stream)


def human_table(rows: "Sequence[WorktreeInfo]") -> str:
    """Aligned human table: slug, path, branch, dirty, age_days."""
    if not rows:
        return ""
    headers = ("SLUG", "PATH", "BRANCH", "DIRTY", "AGE_DAYS")
    body = [(r.slug, str(r.path), r.branch, "yes" if r.dirty else "no", str(r.age_days)) for r in rows]
    widths = [max(len(h), *(len(c) for c in col)) for h, col in zip(headers, zip(*body))]
    sep = "  "
    lines = [sep.join(h.ljust(w) for h, w in zip(headers, widths))]
    lines.append(sep.join("-" * w for w in widths))
    for row in body:
        lines.append(sep.join(c.ljust(w) for c, w in zip(row, widths)))
    return "\n".join(lines)


def porcelain_rows(rows: "Sequence[WorktreeInfo]") -> str:
    """One row per worktree: <slug>\\t<path>\\t<branch>\\t<dirty 0/1>\\t<age_days>."""
    out = []
    for r in rows:
        dirty = "1" if r.dirty else "0"
        out.append(f"{r.slug}\t{r.path}\t{r.branch}\t{dirty}\t{r.age_days}")
    return "\n".join(out)


def json_rows(rows: "Sequence[WorktreeInfo]", *, pretty: bool = False) -> str:
    """JSON array, keys sorted, stable field order."""
    payload = [
        {
            "slug": r.slug,
            "path": str(r.path),
            "branch": r.branch,
            "dirty": r.dirty,
            "age_days": r.age_days,
        }
        for r in rows
    ]
    if pretty:
        return json.dumps(payload, sort_keys=True, indent=2)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def render_gc_plan(slugs: Sequence[str]) -> str:
    """One slug per line, sorted."""
    return "\n".join(sorted(slugs))
