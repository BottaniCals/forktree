"""Integration test for forktree init."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.forktree import cli, config
from src.forktree.errors import PreflightError


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
class TestInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_writes_file(self):
        code = cli.main(["init", str(self.project)])
        self.assertEqual(code, 0)
        target = self.project / ".forktree.toml"
        self.assertTrue(target.exists())
        text = target.read_text()
        self.assertIn("[worktree]", text)
        self.assertIn("[paths]", text)
        self.assertIn("[gc]", text)

    def test_init_refuses_overwrite_without_force(self):
        (self.project / ".forktree.toml").write_text("existing\n")
        code = cli.main(["init", str(self.project)])
        self.assertEqual(code, 1)  # PreflightError -> 1

    def test_init_force_overwrites(self):
        (self.project / ".forktree.toml").write_text("existing\n")
        code = cli.main(["init", str(self.project), "--force"])
        self.assertEqual(code, 0)
