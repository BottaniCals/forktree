"""Integration test for forktree remove."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import config, preflight, worktree
from forktree.errors import PreflightError


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, check=True)


def _make_repo(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@e.com")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("x")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")
    _git(path, "branch", "-M", "main")


def _commit(path: Path, name: str, content: str) -> None:
    (path / name).write_text(content)
    _git(path, "add", name)
    _git(path, "commit", "-q", "-m", name)


def _squash_merge(project: Path, branch: str) -> None:
    _git(project, "merge", "--squash", branch)
    _git(project, "commit", "-q", "-m", f"squash merge {branch}")


@unittest.skipUnless(shutil.which("git"), "git not on PATH")
class TestRemove(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_such_worktree(self):
        cfg = config.Config()
        with self.assertRaises(PreflightError):
            worktree.remove(self.project, "missing", force_if_lossless=False, cfg=cfg, verbose=False)

    def test_create_then_remove(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="x", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        worktree.create(ctx, results, base_sha, slug)
        worktree.remove(self.project, "x", force_if_lossless=True, cfg=cfg, verbose=False)
        self.assertFalse((self.project / ".worktrees" / "x").exists())

    def test_remove_squash_merged_branch_without_force(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="squashed", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        created = worktree.create(ctx, results, base_sha, slug)
        _commit(created.path, "feature.txt", "feature")
        _squash_merge(self.project, "squashed")

        worktree.remove(self.project, "squashed", force_if_lossless=False, cfg=cfg, verbose=False)
        self.assertFalse(created.path.exists())
