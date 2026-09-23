"""Regression tests for the cap-counter filter (QA finding #3).

`forktree` should only count worktrees that live under
`<project>/<cfg.worktrees_dir>/`. The raw `git worktree list --porcelain`
count over-counts because it always includes the source checkout plus any
linked worktrees elsewhere in `.git/worktrees/` (e.g. `.kilo/worktrees/foo`).
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import cli, preflight
from src.forktree.config import DEFAULTS, Config
from src.forktree.worktree import count_forktree_worktrees


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True, text=True, check=True,
    )


def _make_repo(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@e.com")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("x")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")


@unittest.skipUnless(shutil.which("git"), "git not on PATH")
class TestCapFilterIgnoresNonForktreeWorktrees(unittest.TestCase):
    """A linked worktree at `.kilo/worktrees/foo` must not be counted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)
        self.kilo_path = self.project / ".kilo" / "worktrees" / "foo"
        _git(self.project, "worktree", "add", "--detach", str(self.kilo_path), "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def test_count_forktree_worktrees_is_zero(self):
        cfg = DEFAULTS
        self.assertEqual(count_forktree_worktrees(self.project, cfg), 0)

    def test_check_cap_allows_max_count_one(self):
        cfg = replace(DEFAULTS, max_count=1)
        ctx = preflight.PreflightContext(
            project_path=self.project,
            slug="bar",
            requested_ref=cfg.base_ref,
            cfg=cfg,
        )
        # Should NOT raise — the kilo-linked worktree is not counted.
        preflight.check_cap(ctx)

    def test_doctor_cap_section_reports_zero(self):
        cfg = DEFAULTS
        # Force doctor to use the default config for this project.
        from src.forktree.doctor import collect_report
        report = collect_report(
            self.project,
            environ={},
            cli_overrides={},
            strict=False,
        )
        cap_section = dict(report.sections).get("cap", [])
        joined = " ".join(cap_section)
        self.assertIn("current count = 0", joined)


def replace(cfg: Config, **kwargs) -> Config:
    """dataclasses.replace but usable as a free function (avoids import shadowing)."""
    from dataclasses import replace as _replace
    return _replace(cfg, **kwargs)
