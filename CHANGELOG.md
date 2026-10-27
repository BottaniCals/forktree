# Changelog

All notable changes to `forktree` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] — 2026-10-27

### Fixed

- The dirty pre-flight no longer trips over `forktree`'s own worktrees root. The source-tree check ran a bare `git status --porcelain`, so the worktrees directory (`<project>/<worktrees_dir>/`) counted as user dirt — the first `create` succeeded and every later one failed with `forktree: create: source tree is dirty; pass --skip-dirty-check to override` (exit `1`). The status query now excludes the worktrees root, and the root is appended once to the repository-local `.git/info/exclude` so the user's own `git status` stays clean. The tracked `.gitignore` is never modified.
- The dirty pre-flight no longer fails open on a degenerate `paths.worktrees_dir`. When the worktrees root resolved to the repository top level (`"."`) or to an ancestor of the project directory (`".."`), the emitted exclusion covered the whole repository: the status query came back empty, the pre-flight reported "clean", and `forktree create` exited `0` on a genuinely dirty source tree with no warning. The exclusion is now never wider than the worktrees root, and no `.git/info/exclude` entry is written for those layouts.

### Added

- New git seam wrappers `repo_toplevel()`, `exclude_file_path()` and `status_porcelain_excluding()` in `forktree.git`.
- New preflight helpers `worktrees_root()` and `ensure_worktrees_ignored()` in `forktree.preflight`.

### Changed

- The package version is read dynamically from `forktree.__version__` instead of being hardcoded in `pyproject.toml`, so the packaging metadata and the runtime version string share one source of truth. The version is now `0.1.1`; the `v0.1.1` tag is not cut yet.

## [0.1.0] — 2026-09-23

### Added

- Initial public release: the `create`, `list`, `remove`, `gc`, `init` and `doctor` subcommands, the seven ordered safety pre-flights, four-layer TOML configuration resolution, and the opt-in setup hook.

[Unreleased]: https://github.com/BottaniCals/forktree/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BottaniCals/forktree/releases/tag/v0.1.0
