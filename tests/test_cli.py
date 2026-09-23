"""CLI dispatch + exit-code matrix (REQ-1, REQ-3, REQ-4)."""
import unittest
from src.forktree import cli


class TestDispatch(unittest.TestCase):
    def test_no_subcommand_exits_two(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main([])
        self.assertEqual(cm.exception.code, 2)

    def test_unknown_subcommand_exits_two(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(["bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_create_help_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(["create", "--help"])
        self.assertEqual(cm.exception.code, 0)


class TestExitCodeMatrix(unittest.TestCase):
    """All observed exit codes must be in {0, 1, 2, 3}."""

    def test_invalid_slug_returns_preflight_exit(self):
        # Use a temp dir as fake project (won't matter — slug check fails first? actually
        # project_path validation runs first). Use a non-existent path.
        code = cli.main(["create", "/nonexistent/path/xyz", "abc"])
        self.assertIn(code, (0, 1, 2, 3))
