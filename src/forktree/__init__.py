"""forktree — a stdlib-only Python CLI that wraps ``git worktree add/list/remove``
with safety pre-flights, TOML configuration, and an opt-in setup hook.

The package exposes a single public version string; everything else lives in
the sibling modules (``cli``, ``config``, ``preflight``, ``worktree``,
``doctor``, ``git``, ``output``, ``errors``).
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
