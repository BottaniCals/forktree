"""forktree.doctor — read-only diagnostics, always exits 0 (REQ-20)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from forktree import git as g
from forktree import output
from forktree import preflight
from forktree.config import Config, Provenance, resolve_config, project_config_path, global_config_path
from forktree.errors import EXIT_OK, emit_stderr


__all__ = ["DoctorReport", "collect_report", "run_doctor"]


@dataclass(frozen=True, slots=True)
class DoctorReport:
    sections: list[tuple[str, list[str]]]
    problems: list[str]


def _resolve(project_path: Path | None, cli_overrides: Mapping[str, Any], environ: Mapping[str, str], strict: bool):
    if project_path is None:
        project_path = Path.cwd()
    return resolve_config(project_path=project_path, cli_overrides=cli_overrides, environ=environ, strict=strict)


def collect_report(
    project_path: Path | None,
    *,
    environ: Mapping[str, str],
    cli_overrides: Mapping[str, Any],
    strict: bool,
) -> DoctorReport:
    sections: list[tuple[str, list[str]]] = []
    problems: list[str] = []

    pp = (project_path or Path.cwd()).resolve()

    try:
        cfg, prov = _resolve(pp, cli_overrides, environ, strict)
    except Exception as e:  # noqa: BLE001
        problems.append(f"config: {e}")
        return DoctorReport(sections=[("config", ["could not resolve config"])], problems=problems)

    # 1. Resolved config
    cfg_lines = ["resolved config (layer per key):"]
    flat_keys = (
        "worktree.base_ref", "worktree.max_count", "worktree.warn_disk_pct",
        "worktree.fail_disk_gib", "worktree.setup_script",
        "paths.worktrees_dir", "paths.allowed_root",
        "gc.idle_days", "gc.prune",
    )
    for k in flat_keys:
        layer = prov.get(k, "default")
        v = getattr(cfg, _attr_for(k))
        if v is None:
            v = "<unset>"
        cfg_lines.append(f"  {k} = {v}  [{layer}]")
    sections.append(("config", cfg_lines))

    # 2. Git version
    try:
        ver = g.git_version()
    except Exception as e:  # noqa: BLE001
        ver = f"unavailable: {e}"
        problems.append(f"git: {e}")
    sections.append(("git", [ver]))

    # 3. Current worktrees
    try:
        rows = []
        if g.is_git_repo(pp):
            from forktree.worktree import list_worktrees
            rows = list_worktrees(pp, cfg)
        wt_lines = [f"{len(rows)} worktrees:"]
        for r in rows:
            wt_lines.append(f"  {r.slug}  {r.path}  {r.branch}  dirty={'yes' if r.dirty else 'no'}  age_days={r.age_days}")
        sections.append(("worktrees", wt_lines))
    except Exception as e:  # noqa: BLE001
        problems.append(f"worktrees: {e}")
        sections.append(("worktrees", [f"error: {e}"]))

    # 4. Cap usage
    try:
        if g.is_git_repo(pp):
            items = g.worktree_list_porcelain(pp)
            count = sum(1 for it in items if it.get("worktree"))
        else:
            count = 0
        cap_lines = [f"current count = {count}, max_count = {cfg.max_count}"]
        sections.append(("cap", cap_lines))
    except Exception as e:  # noqa: BLE001
        problems.append(f"cap: {e}")
        sections.append(("cap", [f"error: {e}"]))

    # 5. Disk estimate
    try:
        if g.is_git_repo(pp):
            checkout = preflight.estimate_checkout_bytes(pp)
            try:
                usage = shutil.disk_usage(pp)
            except OSError:
                usage = None
            if usage is not None:
                need = preflight.required_free_bytes(
                    usage.total, checkout,
                    pct=cfg.warn_disk_pct, floor_gib=cfg.fail_disk_gib,
                )
                need_gib = need / (1024 ** 3)
                free_gib = usage.free / (1024 ** 3)
                disk_lines = [
                    f"checkout estimate = {checkout} bytes",
                    f"required free     = {need_gib:.1f} GiB",
                    f"available free    = {free_gib:.1f} GiB",
                ]
            else:
                disk_lines = ["disk_usage unavailable"]
        else:
            disk_lines = ["not a git repo — skip disk estimate"]
        sections.append(("disk", disk_lines))
    except Exception as e:  # noqa: BLE001
        problems.append(f"disk: {e}")
        sections.append(("disk", [f"error: {e}"]))

    return DoctorReport(sections=sections, problems=problems)


def _attr_for(dotted: str) -> str:
    return {
        "worktree.base_ref": "base_ref",
        "worktree.max_count": "max_count",
        "worktree.warn_disk_pct": "warn_disk_pct",
        "worktree.fail_disk_gib": "fail_disk_gib",
        "worktree.setup_script": "setup_script",
        "paths.worktrees_dir": "worktrees_dir",
        "paths.allowed_root": "allowed_root",
        "gc.idle_days": "gc_idle_days",
        "gc.prune": "gc_prune",
    }[dotted]


def run_doctor(
    project_path: Path | None,
    *,
    environ: Mapping[str, str],
    cli_overrides: Mapping[str, Any],
    strict: bool,
) -> int:
    report = collect_report(project_path, environ=environ, cli_overrides=cli_overrides, strict=strict)
    for title, lines in report.sections:
        emit_stderr(f"== {title} ==")
        for ln in lines:
            emit_stderr(ln)
    if report.problems:
        emit_stderr("== problems ==")
        for p in report.problems:
            emit_stderr(f"- {p}")
    return EXIT_OK