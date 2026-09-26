# forktree

> A stdlib-only Python CLI that wraps `git worktree add/list/remove` with safety pre-flights, TOML configuration, and an agent-capture stdout/stderr contract.

`forktree` makes `git worktree` safe to call from a shell pipeline, a CI job, or an unattended coding agent. Every subcommand is non-interactive, exits with one of four codes, writes only data to stdout and only diagnostics to stderr, and resolves every path through `realpath`.

Linux and macOS. Python 3.11+. **No third-party dependencies.**

## Install

```bash
pip install forktree
```

For development:

```bash
git clone https://github.com/BottaniCals/forktree.git
cd forktree
python3.11 -m pip install --user -e .
forktree --help
```

## Quick start

```bash
# Create a worktree from the default base ref
wt=$(forktree create "$project_path" "$slug" 2>/tmp/forktree.err) || {
    cat /tmp/forktree.err
    exit 1
}
cd "$wt"
```

That idiom — capture stdout into a variable, route stderr to a file — is the whole point of the tool. If `forktree create` exits non-zero, the worktree was not created.

## Subcommands

| Subcommand | What it does                                                   |
| ---------- | -------------------------------------------------------------- |
| `create`   | Create a new worktree, after running seven safety pre-flights. |
| `list`     | List existing worktrees for a project.                         |
| `remove`   | Remove a worktree (with optional `--force-if-lossless`).       |
| `gc`       | Garbage-collect stale worktrees by age and merge status.       |
| `init`     | Write `.forktree.toml` with the effective resolved config.     |
| `doctor`   | Print a diagnostics report (always exits `0`).                 |

Run `forktree <subcommand> --help` for the full flag reference.

## Output contract

- **stdout** carries data only:
  - `create` → one line: the absolute path of the new worktree.
  - `list --porcelain` → one TSV line per worktree, no header.
  - `list --json` → one JSON array of objects; compact in a pipe, pretty-printed in a TTY. Keys sorted, field order stable.
  - `list` (TTY, default) → a human-readable table.
  - `gc --dry-run` → one slug per line (sorted), the worktrees that would be removed.
  - Everything else: empty on stdout.
- **stderr** carries progress under `-v`, warnings, errors, and the `doctor` diagnostics report.
- **Errors** are formatted exactly as: `forktree: <subcommand>: <one-line reason>`.

## Exit codes

| Code | Meaning                                          |
| ---- | ------------------------------------------------ |
| `0`  | Success                                          |
| `1`  | Preflight refused the operation                  |
| `2`  | Git op failed, setup hook failed, or usage error |
| `3`  | Config error in `--strict` / `FORKTREE_STRICT=1` |

## Configuration

TOML is resolved in this order: **CLI flags > project `.forktree.toml` > `~/.config/forktree/config.toml` > built-in defaults**. Missing files fall back silently. Malformed TOML under `--strict` exits `3`.

```toml
# .forktree.toml (per-project) or ~/.config/forktree/config.toml (global)
[worktree]
base_ref = "main"
max_count = 20
warn_disk_pct = 10
fail_disk_gib = 4
setup_script = ".forktree-setup.sh"   # opt-in; non-zero exit removes the worktree

[paths]
worktrees_dir = "../worktrees"
allowed_root = "/home/me/projects"    # empty = open

[gc]
idle_days = 14
prune = true
```

Environment variables:

- `FORKTREE_STRICT=1` — equivalent to `--strict` on every subcommand. TOML errors exit `3` instead of warning.
- `NO_COLOR=1` — disable ANSI color in human output.

## License

MIT — see [`LICENSE`](./LICENSE).
