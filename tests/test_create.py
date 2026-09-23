"""Integration test for forktree create against a real git init repo (REQ-26 AC2)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import config, git, output, preflight, worktree, errors


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, check=True)


def _make_repo(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Tester")
    (path / "README.md").write_text("hello\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial")


@unittest.skipUnless(shutil.which("git"), "git not on PATH")
class TestCreate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path(self):
        cfg = config.Config(worktrees_dir=".worktrees")
        ctx = preflight.PreflightContext(
            project_path=self.project,
            slug="feature",
            requested_ref="HEAD",
            cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        res = worktree.create(ctx, results, base_sha, slug)
        self.assertTrue(res.path.exists())
        self.assertEqual(res.branch, "feature")
        # HEAD == base_sha
        actual = git.rev_parse(res.path, "HEAD")
        self.assertEqual(actual, base_sha)

    def test_invalid_slug_fails_preflight(self):
        from src.forktree.errors import PreflightError
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project,
            slug="BAD/SLUG",
            requested_ref="HEAD",
            cfg=cfg,
        )
        with self.assertRaises(PreflightError):
            preflight.run_preflights(ctx)

    def test_dirty_source_fails(self):
        # Make source dirty
        (self.project / "dirty.txt").write_text("dirty")
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project,
            slug="feature",
            requested_ref="HEAD",
            cfg=cfg,
        )
        from src.forktree.errors import PreflightError
        with self.assertRaises(PreflightError):
            preflight.run_preflights(ctx)
