"""Integration test for setup hook (REQ-15, REQ-26 AC4)."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import cli


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
class TestSetupHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_script_warns_but_creates(self):
        # Configure setup_script that doesn't exist
        (self.project / ".forktree.toml").write_text('[worktree]\nsetup_script = "missing.sh"\n')
        code = cli.main(["create", str(self.project), "abc"])
        # create still succeeds despite missing script
        self.assertEqual(code, 0)

    def test_non_executable_script_fails(self):
        script = self.project / "hook.sh"
        script.write_text("#!/bin/sh\necho ok\n")
        # Don't chmod — script is not executable
        (self.project / ".forktree.toml").write_text('[worktree]\nsetup_script = "hook.sh"\n')
        code = cli.main(["create", str(self.project), "abc"])
        self.assertEqual(code, 2)  # GitError -> 2

    def test_passing_script_succeeds(self):
        script = self.project / "hook.sh"
        script.write_text("#!/bin/sh\necho ok\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        (self.project / ".forktree.toml").write_text('[worktree]\nsetup_script = "hook.sh"\n')
        code = cli.main(["create", str(self.project), "abc"])
        self.assertEqual(code, 0)
