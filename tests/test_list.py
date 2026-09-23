"""Integration test for forktree list."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import config, output, worktree, preflight


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
class TestList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_returns_no_rows(self):
        cfg = config.Config()
        rows = worktree.list_worktrees(self.project, cfg)
        # Source tree is one worktree; but it's not under worktrees_dir.
        self.assertEqual(rows, [])

    def test_create_then_list_one_row(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="x", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        worktree.create(ctx, results, base_sha, slug)
        rows = worktree.list_worktrees(self.project, cfg)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].slug, "x")
        self.assertEqual(rows[0].branch, "x")

    def test_json_keys_sorted(self):
        rows = []
        from src.forktree.worktree import WorktreeInfo
        rows.append(WorktreeInfo(
            slug="s", path=Path("/tmp/s"), branch="s", dirty=False, age_days=0,
        ))
        out = output.json_rows(rows, pretty=False)
        # keys must be sorted: age_days, branch, dirty, path, slug
        keys = list(json.loads(out)[0].keys())
        self.assertEqual(keys, sorted(keys))
