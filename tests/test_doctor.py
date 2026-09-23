"""Integration test for forktree doctor."""
import shutil
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
class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_doctor_exit_zero(self):
        code = cli.main(["doctor", str(self.project)])
        self.assertEqual(code, 0)

    def test_doctor_on_non_repo_path(self):
        with tempfile.TemporaryDirectory() as t:
            code = cli.main(["doctor", t])
            self.assertEqual(code, 0)  # doctor always exits 0
