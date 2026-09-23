"""Integration test for forktree gc."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import config, preflight, worktree


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, check=True)


def _make_repo(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@e.com")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("x")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")


@unittest.skipUnless(shutil.which("git"), "git not on PATH")
class TestGc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_on_empty(self):
        cfg = config.Config()
        res = worktree.gc(self.project, idle_days=0, dry_run=True, cfg=cfg, verbose=False)
        # Empty project, nothing to gc
        self.assertEqual(res.removed, [])

    def test_create_then_gc_dry_run(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="y", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        worktree.create(ctx, results, base_sha, slug)
        # Branch `y` is created from HEAD, so HEAD is an ancestor of `y`
        # (merge-base == HEAD), meaning `y` IS merged into HEAD per
        # `git merge-base --is-ancestor`. With idle_days=0, clean, and
        # merged, `y` qualifies for GC and `removed` contains 'y'.
        res = worktree.gc(self.project, idle_days=0, dry_run=True, cfg=cfg, verbose=False)
        self.assertEqual(res.removed, ['y'])
