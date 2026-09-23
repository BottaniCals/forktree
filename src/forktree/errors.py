"""forktree.errors — exit codes, exception hierarchy, and stderr formatting.

Single source of truth for the closed ``{0, 1, 2, 3}`` exit-code set and the
canonical ``forktree: <subcommand>: <reason>`` stderr line. Every non-zero
exit in the program originates here, which is what makes the exit-code
guarantee auditable in a single file (REQ-3, REQ-4, REQ-23).

Stdout = data, stderr = diagnostics (enforced structurally by ``output.py``).
This module only ever writes to stderr.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final, IO

__all__ = [
    # Exit codes
    "EXIT_OK",
    "EXIT_PREFLIGHT",
    "EXIT_GIT",
    "EXIT_CONFIG",
    # Exceptions
    "ForktreeError",
    "PreflightError",
    "GitError",
    "ConfigError",
    # Stderr sinks
    "format_error",
    "emit_error",
    "warn",
    "note",
    "tail",
    # Verbosity control
    "set_verbose",
    "is_verbose",
]


# ---------------------------------------------------------------------------
# Exit codes — closed set; no other values may be produced (REQ-3).
# ---------------------------------------------------------------------------

EXIT_OK: Final[int] = 0
EXIT_PREFLIGHT: Final[int] = 1
EXIT_GIT: Final[int] = 2
EXIT_CONFIG: Final[int] = 3


# ---------------------------------------------------------------------------
# Verbosity control for ``note()``.
#
# ``errors`` is a leaf module with no CLI/argparse dependency of its own.
# The CLI parses ``-v`` and calls ``set_verbose(True)`` early in ``main()``
# (see Task 21). ``note()`` is a no-op unless verbose is enabled, matching
# the design's "only under -v" requirement.
# ---------------------------------------------------------------------------

_VERBOSE: bool = False


def set_verbose(verbose: bool) -> None:
    """Toggle whether ``note()`` emits. Called once from CLI parsing."""
    global _VERBOSE
    _VERBOSE = bool(verbose)


def is_verbose() -> bool:
    """Return the current verbose state (for tests and diagnostics)."""
    return _VERBOSE


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class ForktreeError(Exception):
    """Base: carries the desired process exit code and a one-line reason.

    Constructor signature mirrors argparse's ``prog: message`` convention:

        ForktreeError(subcommand, reason, exit_code)

    Production code raises one of the three concrete subclasses below;
    the base class exists so ``except ForktreeError`` catches every
    domain error in one place (the single try/except boundary in
    ``cli.main``).
    """

    exit_code: int

    def __init__(self, subcommand: str, reason: str, exit_code: int) -> None:
        self.subcommand = subcommand
        self.reason = reason
        self.exit_code = exit_code
        # Pre-format the canonical message so str(exc) and the
        # traceback-free stderr line are both
        # "forktree: <subcommand>: <reason>".
        self.message = format_error(subcommand, reason)
        super().__init__(self.message)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class PreflightError(ForktreeError):
    """Preflight refused or invalid input. Exit code ``EXIT_PREFLIGHT`` (1)."""

    check_name: str

    def __init__(
        self,
        subcommand: str,
        reason: str,
        check_name: str = "",
    ) -> None:
        # Fold the check name into the reason once, but don't double-prefix
        # if the caller already wrote "check_name: ..." into reason.
        if check_name and not reason.lstrip().startswith(f"{check_name}:"):
            reason = f"{check_name}: {reason}"
        super().__init__(subcommand, reason, EXIT_PREFLIGHT)
        self.check_name = check_name


class GitError(ForktreeError):
    """A ``git`` invocation or setup hook failed. Exit code ``EXIT_GIT`` (2).

    ``argv`` carries the full argument vector that produced the failure
    (for diagnostics / future structured logging). ``stderr_tail`` is the
    last few lines of git's stderr, produced by ``tail()``, so the user
    sees only the relevant snippet rather than a wall of plumbing.
    """

    argv: tuple[str, ...]
    stderr_tail: str

    def __init__(
        self,
        subcommand: str,
        reason: str,
        *,
        argv: tuple[str, ...] = (),
        stderr_tail: str = "",
    ) -> None:
        super().__init__(subcommand, reason, EXIT_GIT)
        self.argv = tuple(argv)
        self.stderr_tail = stderr_tail


class ConfigError(ForktreeError):
    """Configuration error (malformed TOML under strict mode).

    Exit code ``EXIT_CONFIG`` (3). ``path`` points at the offending file;
    ``line`` and ``col`` are 1-based position hints when known (see
    ``config._error_position`` for how they're extracted from
    ``tomllib.TOMLDecodeError`` on Python 3.11+).
    """

    path: Path
    line: int | None
    col: int | None

    def __init__(
        self,
        subcommand: str,
        reason: str,
        *,
        path: Path | None = None,
        line: int | None = None,
        col: int | None = None,
    ) -> None:
        super().__init__(subcommand, reason, EXIT_CONFIG)
        self.path = Path() if path is None else Path(path)
        self.line = line
        self.col = col


# ---------------------------------------------------------------------------
# Stderr formatting
# ---------------------------------------------------------------------------


def _flatten(text: str) -> str:
    """Collapse any internal newlines so a single line stays single-line."""
    return (text or "").strip().replace("\r\n", " ").replace("\n", " ")


def format_error(subcommand: str, reason: str) -> str:
    """Return ``"forktree: <subcommand>: <reason>"`` (one line, no traceback).

    A blank ``subcommand`` or ``reason`` collapses safely rather than
    producing ``"forktree: :"`` with no information.
    """
    sub = (subcommand or "?").strip() or "?"
    rsn = _flatten(reason) or "unknown error"
    return f"forktree: {sub}: {rsn}"


def _format_warn(message: str) -> str:
    return f"forktree: warning: {_flatten(message)}"


def _format_note(message: str) -> str:
    return f"forktree: {_flatten(message)}"


def emit_error(
    subcommand: str,
    reason: str,
    *,
    stream: IO[str] | None = None,
) -> None:
    """Write the canonical error line to stderr (or ``stream`` in tests)."""
    target = stream if stream is not None else sys.stderr
    print(format_error(subcommand, reason), file=target)


def warn(message: str, *, stream: IO[str] | None = None) -> None:
    """Write ``"forktree: warning: <message>"`` to stderr.

    Not silenced by ``-q`` (there is no ``-q`` in the MVP — warnings are
    always shown, per REQ-2's "stderr = diagnostics" rule).
    """
    target = stream if stream is not None else sys.stderr
    print(_format_warn(message), file=target)


def note(message: str, *, stream: IO[str] | None = None) -> None:
    """Write ``"forktree: <message>"`` to stderr, but only under ``-v``.

    No-op when verbose is off, which is the default. Toggle via
    ``set_verbose(True)`` early in ``cli.main``.
    """
    if not _VERBOSE:
        return
    target = stream if stream is not None else sys.stderr
    print(_format_note(message), file=target)


def tail(text: str, *, max_lines: int = 3) -> str:
    """Trim a failing git / setup-script stderr to a short single-line tail.

    Returns the last ``max_lines`` non-empty lines (after stripping), joined
    by ``" | "``. Blank or whitespace-only input yields ``""``. A
    non-positive ``max_lines`` falls back to 3 so a misuse never crashes.
    """
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    if max_lines is None or max_lines <= 0:
        max_lines = 3
    return " | ".join(lines[-max_lines:])
