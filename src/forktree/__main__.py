"""Entry point for ``python -m forktree``.

This thin module exists so that ``python -m forktree`` behaves identically to
the ``forktree`` console-script shim produced by ``pip install`` from
``pyproject.toml`` (which calls ``forktree.cli:main``). Keeping the dispatch
in one place — the ``main()`` function in ``forktree.cli`` — means there is
no second argparse tree to drift out of sync.
"""

from __future__ import annotations

from forktree.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
