# AGENTS.md — forktree

_Project house rules for Cedar and OpenProse subagents._

## What this is

`forktree` is a Python 3.11+ stdlib-only CLI wrapping `git worktree add/list/remove` with safety pre-flights, TOML configuration, and an opt-in setup hook. Public MVP.

The full design is in `SPEC.md` — read it first, treat it as authoritative for scope, CLI surface, error model, and exit codes.

## Stack

- **Language:** Python 3.11+ (uses `tomllib`, `subprocess`, `pathlib`, `argparse`, `unittest`).
- **Deps:** stdlib only. No third-party. No `pip install` of extras for the runtime.
- **Dev deps:** none required; tests are stdlib `unittest`. Add `pytest` only if a contributor asks for it.
- **Platforms:** Linux + macOS. Windows is out of MVP scope.

## Repository layout (target)

```
forktree/
├── SPEC.md             # authoritative spec — do not edit casually
├── AGENTS.md           # this file
├── LICENSE
├── README.md           # generated/curated by implementer; keep short
├── pyproject.toml      # PEP 621; entry point `forktree = forktree.cli:main`
├── src/forktree/
│   ├── __init__.py
│   ├── cli.py          # argparse + entry point
│   ├── config.py       # TOML loading + 4-layer resolution
│   ├── worktree.py     # create / remove / list / gc
│   ├── preflight.py    # disk, dirty, cap, base-ref, slug
│   ├── git.py          # subprocess wrappers, output parsing
│   ├── doctor.py
│   ├── output.py       # porcelain / json / human tables
│   └── errors.py       # exit codes + stderr formatting
└── tests/
    ├── test_create.py
    ├── test_list.py
    ├── test_remove.py
    ├── test_gc.py
    ├── test_init.py
    ├── test_doctor.py
    ├── test_config.py
    ├── test_setup_hook.py
    └── test_smoke.py
```

`src/`-layout is fine; `flat` is also fine if the implementer prefers. Don't bikeshed.

## Conventions

- **Stdout = data, stderr = diagnostics.** One-line absolute path on `create` stdout. Everything else (progress under `-v`, warnings, errors) on stderr. This is an agent-capture contract — do not break it.
- **Exit codes are 0/1/2/3** exactly as specified. Don't add new ones.
- **No interactivity, ever.** No prompts, no TTY assumptions, no `input()`.
- **No third-party deps.** Resist the urge to add `click`, `rich`, `pyyaml`, etc.
- **TOML errors under strict mode** exit `3`. Malformed under permissive mode warns and falls back to defaults (see SPEC §4.3).
- **Slug regex** is `^[a-z0-9][a-z0-9-]{0,63}$`. Validate early.
- **Branch name == slug by default.** No `--branch` flag (per SPEC §3 / `create` execution).
- **Time fields** come from `git log -1 --format=%ct`, never `time.time()` — keeps determinism.
- **JSON output keys** are sorted and stable.
- **Disk estimate** uses `du -sb` on the source worktree; falls back to `git count-objects --verbose` for new/empty repos.

## Dev commands

```bash
# Install editable
python3.11 -m pip install --user -e .

# Run CLI
forktree --help

# Tests (stdlib unittest, no extra deps)
python3.11 -m unittest discover -s tests -v

# Smoke test (full create/list/remove/gc cycle on a throwaway repo)
python3.11 -m unittest tests.test_smoke -v
```

## Things to NOT do

- Don't add Windows support, sparse-checkout profiles, Btrfs/APFS awareness, daemons, TUI/web UI, or snapshot/restore. All explicitly out of MVP scope per SPEC §1.
- Don't fold `init` into `doctor`. They're separate subcommands (SPEC §11, lean: separate).
- Don't make `setup_script` default-on. Opt-in via `[worktree].setup_script` only.
- Don't write data to stdout for `create` other than the absolute worktree path. No "Created worktree at..." prose on stdout — that's a stderr message at most.
- Don't introduce a package manager file other than `pyproject.toml`.

## Release process (out of scope for this MVP)

PyPI publish: `python3.11 -m build && python3.11 -m twine upload dist/*`. Verify name availability before publishing — there are squatters on similar names. Renald handles the actual publish.
