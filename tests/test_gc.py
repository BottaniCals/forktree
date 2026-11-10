"""Integration test for forktree gc."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import config, git, preflight, worktree


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


def _commit(path: Path, name: str, content: str, message: str) -> None:
    (path / name).write_text(content)
    _git(path, "add", name)
    _git(path, "commit", "-q", "-m", message)


def _squash_merge(project: Path, branch: str) -> None:
    _git(project, "merge", "--squash", branch)
    _git(project, "commit", "-q", "-m", f"squash merge {branch}")


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

    def test_squash_merged_branch_is_gc_candidate(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="squashed", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        created = worktree.create(ctx, results, base_sha, slug)
        _commit(created.path, "one.txt", "one", "one")
        _commit(created.path, "two.txt", "two", "two")
        _squash_merge(self.project, "squashed")

        self.assertTrue(git.is_branch_merged(self.project, "squashed", "main"))
        res = worktree.gc(self.project, idle_days=0, dry_run=True, cfg=cfg, verbose=False)
        self.assertEqual(res.removed, ['squashed'])

    def test_unmerged_branch_is_not_gc_candidate(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="unmerged", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        created = worktree.create(ctx, results, base_sha, slug)
        _commit(created.path, "feature.txt", "feature", "feature")

        self.assertFalse(git.is_branch_merged(self.project, "unmerged", "main"))
        res = worktree.gc(self.project, idle_days=0, dry_run=True, cfg=cfg, verbose=False)
        self.assertEqual(res.removed, [])

    def test_unique_merge_commit_is_not_treated_as_merged(self):
        cfg = config.Config()
        ctx = preflight.PreflightContext(
            project_path=self.project, slug="topic", requested_ref="HEAD", cfg=cfg,
        )
        results, base_sha, slug = preflight.run_preflights(ctx)
        created = worktree.create(ctx, results, base_sha, slug)
        _commit(created.path, "shared.txt", "shared", "shared")
        shared_sha = _git(created.path, "rev-parse", "HEAD").stdout.strip()

        _git(self.project, "switch", "-c", "side")
        _commit(self.project, "unique.txt", "unique", "unique")
        _git(self.project, "switch", "main")
        _git(created.path, "merge", "--no-ff", "side", "-m", "merge side")
        _git(self.project, "cherry-pick", shared_sha)

        self.assertFalse(git.is_branch_merged(self.project, "topic", "main"))
