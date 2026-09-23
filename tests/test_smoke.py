"""End-to-end smoke: full create/list/remove/gc cycle (REQ-26 AC6)."""
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
class TestSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        _make_repo(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_cycle(self):
        # init
        self.assertEqual(cli.main(["init", str(self.project)]), 0)
        # create
        self.assertEqual(cli.main(["create", str(self.project), "smoke"]), 0)
        # list
        self.assertEqual(cli.main(["list", str(self.project)]), 0)
        # remove
        self.assertEqual(cli.main(["remove", str(self.project), "smoke", "--force-if-lossless"]), 0)
        # gc --dry-run
        self.assertEqual(cli.main(["gc", str(self.project), "--dry-run"]), 0)
        # doctor
        self.assertEqual(cli.main(["doctor", str(self.project)]), 0)
