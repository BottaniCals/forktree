"""forktree.cli — argparse parser, dispatch, and main() exit-code boundary (REQ-1..REQ-4, REQ-14)."""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

from forktree import output, worktree, doctor, preflight
from forktree import __version__
from forktree.config import Config, Provenance, resolve_config
from forktree.errors import (
    EXIT_OK,
    EXIT_PREFLIGHT,
    EXIT_GIT,
    EXIT_CONFIG,
    ForktreeError,
    PreflightError,
    GitError,
    ConfigError,
    emit_error,
)


_STDOUT_STDERR_NOTE = (
    "stdout = data only; stderr = diagnostics only. "
    "Exit codes: 0=ok, 1=preflight/input, 2=git/setup-hook/usage, 3=config (strict)."
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forktree",
        description=f"forktree — git worktree wrapper with safety preflights. {_STDOUT_STDERR_NOTE}",
    )
    p.add_argument("--strict", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"forktree {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common_strict(sp):
        sp.add_argument("--strict", action="store_true", help=argparse.SUPPRESS)

    # create
    sp_c = sub.add_parser("create", help="Create a new worktree.", description=_STDOUT_STDERR_NOTE)
    sp_c.add_argument("project_path")
    sp_c.add_argument("slug")
    sp_c.add_argument("--base-ref", default=None)
    sp_c.add_argument("--name", default=None, help="Human name; slugified into the effective slug.")
    sp_c.add_argument("--skip-disk-check", action="store_true")
    sp_c.add_argument("--skip-dirty-check", action="store_true")
    sp_c.add_argument("-v", "--verbose", action="store_true")
    common_strict(sp_c)

    # list
    sp_l = sub.add_parser("list", help="List worktrees.", description=_STDOUT_STDERR_NOTE)
    sp_l.add_argument("project_path")
    sp_l.add_argument("--porcelain", action="store_true")
    sp_l.add_argument("--json", action="store_true")
    common_strict(sp_l)

    # remove
    sp_r = sub.add_parser("remove", help="Remove a worktree.", description=_STDOUT_STDERR_NOTE)
    sp_r.add_argument("project_path")
    sp_r.add_argument("slug")
    sp_r.add_argument("--force-if-lossless", action="store_true")
    sp_r.add_argument("-v", "--verbose", action="store_true")
    common_strict(sp_r)

    # gc
    sp_g = sub.add_parser("gc", help="Garbage-collect stale worktrees.", description=_STDOUT_STDERR_NOTE)
    sp_g.add_argument("project_path")
    sp_g.add_argument("--idle-days", type=int, default=None)
    sp_g.add_argument("--dry-run", action="store_true")
    sp_g.add_argument("-v", "--verbose", action="store_true")
    common_strict(sp_g)

    # init
    sp_i = sub.add_parser("init", help="Write .forktree.toml with effective config.", description=_STDOUT_STDERR_NOTE)
    sp_i.add_argument("project_path", nargs="?", default=None)
    sp_i.add_argument("--force", action="store_true")
    common_strict(sp_i)

    # doctor
    sp_d = sub.add_parser("doctor", help="Diagnostics report (always exits 0).", description=_STDOUT_STDERR_NOTE)
    sp_d.add_argument("project_path", nargs="?", default=None)
    common_strict(sp_d)

    return p


def _normalize_project_path(raw: str | None) -> Path:
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def _strict_enabled(args: argparse.Namespace, environ: Mapping[str, str]) -> bool:
    if getattr(args, "strict", False):
        return True
    return environ.get("FORKTREE_STRICT") == "1"


def _resolve(args, environ):
    pp = _normalize_project_path(getattr(args, "project_path", None))
    cli_overrides: dict[str, Any] = {}
    if getattr(args, "base_ref", None):
        cli_overrides["worktree.base_ref"] = args.base_ref
    cfg, prov = resolve_config(
        project_path=pp,
        cli_overrides=cli_overrides,
        environ=environ,
        strict=_strict_enabled(args, environ),
    )
    return pp, cfg, prov


def _cli_overrides(args) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if getattr(args, "base_ref", None):
        out["worktree.base_ref"] = args.base_ref
    return out


def _cmd_create(args, environ) -> int:
    pp = _normalize_project_path(args.project_path)
    cfg, _ = resolve_config(
        project_path=pp,
        cli_overrides=_cli_overrides(args),
        environ=environ,
        strict=_strict_enabled(args, environ),
    )
    requested = cfg.base_ref
    if args.base_ref:
        requested = args.base_ref
    raw_slug = args.slug
    if args.name:
        slugified = preflight.slugify(args.name)
        if not slugified:
            raise PreflightError(
                check_name="slug",
                reason=f"slugify produced empty slug from --name {args.name}",
                subcommand="create",
            )
        effective_slug = slugified
    else:
        effective_slug = raw_slug
        if not preflight.is_valid_slug(effective_slug):
            raise PreflightError(
                check_name="slug",
                reason=f"invalid slug: {effective_slug}",
                subcommand="create",
            )

    ctx = preflight.PreflightContext(
        project_path=pp,
        slug=effective_slug,
        requested_ref=requested,
        cfg=cfg,
        skip_disk_check=args.skip_disk_check,
        skip_dirty_check=args.skip_dirty_check,
    )
    results, base_sha, eff_slug = preflight.run_preflights(ctx)
    res = worktree.create(ctx, results, base_sha, eff_slug)
    output.print_path(res.path)
    return EXIT_OK


def _cmd_list(args, environ) -> int:
    pp, cfg, _ = _resolve(args, environ)
    rows = worktree.list_worktrees(pp, cfg)
    if args.json:
        pretty = output.is_tty(sys.stdout) and not os.environ.get("NO_COLOR")
        sys.stdout.write(output.json_rows(rows, pretty=pretty) + "\n")
    elif args.porcelain or not output.is_tty(sys.stdout):
        text = output.porcelain_rows(rows)
        if text:
            sys.stdout.write(text + "\n")
    else:
        text = output.human_table(rows)
        if text:
            sys.stdout.write(text + "\n")
    return EXIT_OK


def _cmd_remove(args, environ) -> int:
    pp, cfg, _ = _resolve(args, environ)
    worktree.remove(
        pp, args.slug,
        force_if_lossless=args.force_if_lossless,
        cfg=cfg, verbose=args.verbose,
    )
    return EXIT_OK


def _cmd_gc(args, environ) -> int:
    pp, cfg, _ = _resolve(args, environ)
    res = worktree.gc(
        pp,
        idle_days=args.idle_days,
        dry_run=args.dry_run,
        cfg=cfg,
        verbose=args.verbose,
    )
    if args.dry_run:
        text = output.render_gc_plan(res.removed)
        if text:
            sys.stdout.write(text + "\n")
        return EXIT_OK
    if res.removed:
        emit_error("gc", f"removed: {' '.join(res.removed)}")  # stderr confirmation
    if res.failed:
        return EXIT_GIT
    return EXIT_OK


def _cmd_init(args, environ) -> int:
    pp = _normalize_project_path(args.project_path)
    cfg, prov = resolve_config(
        project_path=pp,
        cli_overrides={},
        environ=environ,
        strict=_strict_enabled(args, environ),
    )
    target = pp / ".forktree.toml"
    if target.exists() and not args.force:
        raise PreflightError(
            check_name="init",
            reason="refusing to overwrite existing .forktree.toml (use --force)",
            subcommand="init",
        )
    lines: list[str] = ["# Generated by `forktree init`. Effective config (4-layer resolved).", ""]
    lines.append("[worktree]")
    lines.append(f'base_ref = "{cfg.base_ref}"')
    lines.append(f"max_count = {cfg.max_count}")
    lines.append(f"warn_disk_pct = {cfg.warn_disk_pct}")
    lines.append(f"fail_disk_gib = {cfg.fail_disk_gib}")
    if cfg.setup_script:
        lines.append(f'setup_script = "{cfg.setup_script}"')
    else:
        lines.append("# setup_script = \".forktree-setup.sh\"  # opt-in; relative to project_path")
    lines.append("")
    lines.append("[paths]")
    lines.append(f'worktrees_dir = "{cfg.worktrees_dir}"')
    if cfg.allowed_root:
        lines.append(f'allowed_root = "{cfg.allowed_root}"')
    else:
        lines.append('# allowed_root = ""  # empty = open; non-empty = realpath-prefix allowlist')
    lines.append("")
    lines.append("[gc]")
    lines.append(f"idle_days = {cfg.gc_idle_days}")
    lines.append(f"prune = {str(cfg.gc_prune).lower()}")
    lines.append("")
    target.write_text("\n".join(lines))
    emit_error("init", f"wrote {target}")
    return EXIT_OK


def _cmd_doctor(args, environ) -> int:
    pp = _normalize_project_path(args.project_path)
    return doctor.run_doctor(
        pp,
        environ=environ,
        cli_overrides=_cli_overrides(args),
        strict=_strict_enabled(args, environ),
    )


_HANDLERS = {
    "create": _cmd_create,
    "list": _cmd_list,
    "remove": _cmd_remove,
    "gc": _cmd_gc,
    "init": _cmd_init,
    "doctor": _cmd_doctor,
}


def main(argv: Sequence[str] | None = None) -> int:
    environ = os.environ
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = _HANDLERS[args.command]
    try:
        return handler(args, environ)
    except ConfigError as e:
        emit_error(args.command, e.reason)
        return EXIT_CONFIG
    except PreflightError as e:
        emit_error(args.command, e.reason)
        return EXIT_PREFLIGHT
    except GitError as e:
        emit_error(args.command, e.reason)
        return EXIT_GIT
    except ForktreeError as e:
        emit_error(args.command, e.reason)
        return EXIT_GIT
    except SystemExit as e:
        # argparse's native SystemExit(2) for usage/unknown-subcommand (R1 AC1/AC3)
        return int(e.code) if isinstance(e.code, int) else 2
    except Exception as e:  # noqa: BLE001
        emit_error(args.command, f"unexpected: {e}")
        traceback.print_exc(file=sys.stderr)
        return EXIT_GIT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())