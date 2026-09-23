"""Unit tests for forktree.config (REQ-21..REQ-25)."""
import os
import tempfile
import unittest
from pathlib import Path

from src.forktree import config


class TestFlatten(unittest.TestCase):
    def test_flat(self):
        self.assertEqual(config.flatten({"a": {"b": 1, "c": 2}}), {"a.b": 1, "a.c": 2})

    def test_mixed(self):
        self.assertEqual(
            config.flatten({"a": {"b": {"c": 1}}, "x": 2}),
            {"a.b.c": 1, "x": 2},
        )

    def test_empty(self):
        self.assertEqual(config.flatten({}), {})


class TestClamp(unittest.TestCase):
    def test_warn_disk_pct_clamped(self):
        self.assertEqual(config._clamp("worktree.warn_disk_pct", 150), 100)
        self.assertEqual(config._clamp("worktree.warn_disk_pct", -5), 0)

    def test_max_count_min_one(self):
        self.assertEqual(config._clamp("worktree.max_count", 0), 1)
        self.assertEqual(config._clamp("worktree.max_count", -1), 1)


class TestLoadLayer(unittest.TestCase):
    def test_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(config.load_layer(Path(t) / "nope.toml", strict=False), {})

    def test_malformed_permissive_warns(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "bad.toml"
            p.write_text("a = = 1\n")
            self.assertEqual(config.load_layer(p, strict=False), {})

    def test_malformed_strict_raises(self):
        from src.forktree.errors import ConfigError
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "bad.toml"
            p.write_text("a = = 1\n")
            with self.assertRaises(ConfigError):
                config.load_layer(p, strict=True)


class TestResolveConfig(unittest.TestCase):
    def test_defaults_only(self):
        with tempfile.TemporaryDirectory() as t:
            pp = Path(t)
            cfg, prov = config.resolve_config(
                project_path=pp,
                cli_overrides={},
                environ={"HOME": t},
                strict=False,
            )
            self.assertEqual(cfg.base_ref, "main")
            self.assertEqual(cfg.max_count, 20)
            self.assertEqual(prov["worktree.base_ref"], "default")

    def test_cli_overrides_win(self):
        with tempfile.TemporaryDirectory() as t:
            pp = Path(t)
            cfg, prov = config.resolve_config(
                project_path=pp,
                cli_overrides={"worktree.base_ref": "develop"},
                environ={"HOME": t},
                strict=False,
            )
            self.assertEqual(cfg.base_ref, "develop")
            self.assertEqual(prov["worktree.base_ref"], "cli")

    def test_project_overrides_global(self):
        with tempfile.TemporaryDirectory() as t:
            pp = Path(t)
            proj = pp / ".forktree.toml"
            proj.write_text('[worktree]\nbase_ref = "feature"\n')
            glob_dir = Path(t) / ".config" / "forktree"
            glob_dir.mkdir(parents=True)
            (glob_dir / "config.toml").write_text('[worktree]\nbase_ref = "global-base"\n')
            cfg, prov = config.resolve_config(
                project_path=pp,
                cli_overrides={},
                environ={"HOME": t, "XDG_CONFIG_HOME": str(Path(t) / ".config")},
                strict=False,
            )
            self.assertEqual(cfg.base_ref, "feature")
            self.assertEqual(prov["worktree.base_ref"], "project")


class TestAllowedRoot(unittest.TestCase):
    def test_enforce_passes_when_inside(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            sub = root / "project"
            sub.mkdir()
            config.enforce_allowlist(sub, str(root))  # should not raise

    def test_enforce_fails_outside(self):
        from src.forktree.errors import PreflightError
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            other = root / "other" / "project"
            other.mkdir(parents=True)
            with self.assertRaises(PreflightError):
                config.enforce_allowlist(other, str(root / "allowed"))

    def test_empty_allows_anywhere(self):
        with tempfile.TemporaryDirectory() as t:
            config.enforce_allowlist(Path(t), "")  # no raise
