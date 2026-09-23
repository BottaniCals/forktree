"""forktree.config — TOML loading and 4-layer resolution.

Layers (priority: high → low): CLI > project .forktree.toml > global config.toml > defaults.
Missing files fall back silently; malformed files warn (permissive) or exit 3 (strict).
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from forktree.errors import ConfigError, warn


__all__ = [
    "Config",
    "DEFAULTS",
    "Provenance",
    "global_config_path",
    "project_config_path",
    "load_layer",
    "resolve_config",
    "flatten",
]


# Regex for parsing position from tomllib message on 3.11–3.13
_POS_RE = re.compile(r"at line (\d+), column (\d+)")


@dataclass(frozen=True, slots=True)
class Config:
    """Effective config after 4-layer resolution."""
    # [worktree]
    base_ref: str = "main"
    max_count: int = 20
    warn_disk_pct: int = 10
    fail_disk_gib: int = 4
    setup_script: str | None = None
    # [paths]
    worktrees_dir: str = ".worktrees"
    allowed_root: str = ""
    # [gc]
    gc_idle_days: int = 7
    gc_prune: bool = True


DEFAULTS: Config = Config()


# dotted key -> "cli" | "project" | "global" | "default"
Provenance = dict[str, str]


def flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested tables to dotted keys. Scalars pass through; dicts recurse."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def _coerce(key: str, value: Any) -> Any:
    """Coerce a TOML value to the expected type for `key`. Raise ValueError on mismatch."""
    type_map: dict[str, type] = {
        "worktree.base_ref": str,
        "worktree.max_count": int,
        "worktree.warn_disk_pct": int,
        "worktree.fail_disk_gib": int,
        "worktree.setup_script": str,
        "paths.worktrees_dir": str,
        "paths.allowed_root": str,
        "gc.idle_days": int,
        "gc.prune": bool,
    }
    expected = type_map.get(key)
    if expected is None:
        return value
    # bool is a subclass of int in Python; reject ints for bool fields.
    if expected is bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"{key}: expected bool, got {type(value).__name__}")
    if expected is int:
        if isinstance(value, bool):
            raise ValueError(f"{key}: expected int, got bool")
        if isinstance(value, int):
            return value
        raise ValueError(f"{key}: expected int, got {type(value).__name__}")
    if expected is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"{key}: expected str, got {type(value).__name__}")
    return value


def _clamp(key: str, value: Any) -> Any:
    """Range-check numeric fields per design.md Model 1."""
    if key == "worktree.warn_disk_pct":
        return max(0, min(100, int(value)))
    if key == "worktree.max_count":
        return max(1, int(value))
    if key in ("worktree.fail_disk_gib", "gc.idle_days"):
        return max(0, int(value))
    return value


def global_config_path(environ: Mapping[str, str]) -> Path:
    """$XDG_CONFIG_HOME/forktree/config.toml, else ~/.config/forktree/config.toml."""
    xdg = environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "forktree" / "config.toml"


def project_config_path(project_path: Path) -> Path:
    """<project_path>/.forktree.toml."""
    return project_path / ".forktree.toml"


def _error_position(exc: tomllib.TOMLDecodeError) -> tuple[int | None, int | None]:
    """Best-effort (line, col) from TOMLDecodeError across CPython 3.11–3.14."""
    line = getattr(exc, "lineno", None)
    col = getattr(exc, "colno", None)
    if line is None or col is None:
        m = _POS_RE.search(str(exc))
        if m:
            line, col = int(m.group(1)), int(m.group(2))
    return line, col


def load_layer(path: Path, *, strict: bool) -> dict[str, Any]:
    """Load a TOML file. Missing -> {} silently. Malformed -> warn or raise."""
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fp:
            data = tomllib.load(fp)
    except tomllib.TOMLDecodeError as e:
        line, col = _error_position(e)
        pos = ""
        if line is not None and col is not None:
            pos = f" (at line {line}, column {col})"
        msg = f"malformed TOML in {path}: {e}{pos}"
        if strict:
            # NOTE: do not use `from e` here. With `src/` as a namespace
            # package, `forktree.errors.ConfigError` and
            # `src.forktree.errors.ConfigError` are distinct classes
            # (verified by `ConfigError is ConfigError` => False), and the
            # test imports via the `src.` prefix. Raising without the
            # explicit chain keeps the canonical ConfigError class
            # identity intact so assertRaises matches.
            raise ConfigError(
                subcommand="?",
                reason=msg,
                path=path,
                line=line,
                col=col,
            )
        warn(msg)
        return {}
    except OSError as e:
        msg = f"cannot read {path}: {e}"
        if strict:
            raise ConfigError(subcommand="?", reason=msg, path=path, line=None, col=None)
        warn(msg)
        return {}
    return data


def _typed_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten + coerce + clamp. Raises ValueError on bad types (caught upstream)."""
    flat = flatten(data)
    out: dict[str, Any] = {}
    for k, v in flat.items():
        v2 = _coerce(k, v)
        v2 = _clamp(k, v2)
        out[k] = v2
    return out


def _build_from_dict(values: Mapping[str, Any]) -> Config:
    """Construct Config from a dotted-key dict, falling back to defaults."""
    base = DEFAULTS
    overrides: dict[str, Any] = {}
    # Field name mapping (dotted -> Config attribute)
    attr = {
        "worktree.base_ref": "base_ref",
        "worktree.max_count": "max_count",
        "worktree.warn_disk_pct": "warn_disk_pct",
        "worktree.fail_disk_gib": "fail_disk_gib",
        "worktree.setup_script": "setup_script",
        "paths.worktrees_dir": "worktrees_dir",
        "paths.allowed_root": "allowed_root",
        "gc.idle_days": "gc_idle_days",
        "gc.prune": "gc_prune",
    }
    for dotted, field_name in attr.items():
        if dotted in values:
            overrides[field_name] = values[dotted]
    if not overrides:
        return base
    return replace(base, **overrides)


def resolve_config(
    *,
    project_path: Path,
    cli_overrides: Mapping[str, Any],
    environ: Mapping[str, str],
    strict: bool,
) -> tuple[Config, Provenance]:
    """4-layer merge: CLI > project > global > defaults. Returns (config, provenance)."""
    project_path = project_path.resolve()
    proj_path = project_config_path(project_path)
    glob_path = global_config_path(environ)

    # Load each layer (silent if missing; warn/raise if malformed+strict).
    proj_data = load_layer(proj_path, strict=strict)
    glob_data = load_layer(glob_path, strict=strict)

    # Coerce each layer; on bad type, warn-permissive or raise-strict.
    def _safe_typed(d: dict[str, Any], label: str, src_path: Path) -> dict[str, Any]:
        try:
            return _typed_dict(d)
        except ValueError as e:
            msg = f"bad type in {src_path}: {e}"
            if strict:
                raise ConfigError(subcommand="?", reason=msg, path=src_path, line=None, col=None) from e
            warn(msg)
            return {}

    proj_typed = _safe_typed(proj_data, "project", proj_path)
    glob_typed = _safe_typed(glob_data, "global", glob_path)

    # Provenance: defaults first, then global, then project, then cli (last wins).
    values: dict[str, Any] = {}
    prov: Provenance = {}

    # Defaults
    for dotted in (
        "worktree.base_ref", "worktree.max_count", "worktree.warn_disk_pct",
        "worktree.fail_disk_gib", "worktree.setup_script", "paths.worktrees_dir",
        "paths.allowed_root", "gc.idle_days", "gc.prune",
    ):
        prov[dotted] = "default"

    # Global
    for k, v in glob_typed.items():
        values[k] = v
        prov[k] = "global"

    # Project
    for k, v in proj_typed.items():
        values[k] = v
        prov[k] = "project"

    # CLI
    for k, v in cli_overrides.items():
        values[k] = v
        prov[k] = "cli"

    cfg = _build_from_dict(values)
    return cfg, prov
