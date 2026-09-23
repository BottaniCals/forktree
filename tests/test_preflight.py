"""Unit tests for forktree.preflight (slug, base-ref, allowlist)."""
import unittest
from src.forktree import preflight


class TestSlug(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(preflight.is_valid_slug("fix-bug-12"))
        self.assertTrue(preflight.is_valid_slug("a"))
        self.assertTrue(preflight.is_valid_slug("a" + "b" * 63))

    def test_invalid_uppercase(self):
        self.assertFalse(preflight.is_valid_slug("Fix-Bug"))

    def test_invalid_leading_dash(self):
        self.assertFalse(preflight.is_valid_slug("-foo"))

    def test_too_long(self):
        self.assertFalse(preflight.is_valid_slug("a" + "b" * 64))


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(preflight.slugify("Fix Bug #12!"), "fix-bug-12")

    def test_trim_separators(self):
        self.assertEqual(preflight.slugify("---foo bar---"), "foo-bar")

    def test_unicode_to_separators(self):
        self.assertEqual(preflight.slugify("héllo wörld"), "h-llo-w-rld")

    def test_empty(self):
        self.assertEqual(preflight.slugify("!!!"), "")


class TestRequiredFreeBytes(unittest.TestCase):
    def test_floor_wins_over_pct(self):
        # pct=10 of 1000 = 100; floor=4 GiB = 4*1024^3; floor wins
        total = 1000
        out = preflight.required_free_bytes(total, 0, pct=10, floor_gib=4)
        self.assertEqual(out, 4 * (1024 ** 3))

    def test_pct_wins_over_floor(self):
        # pct=10 of 1 TiB = 100 GiB; floor=4 GiB; pct wins
        total = 1024 ** 4
        out = preflight.required_free_bytes(total, 0, pct=10, floor_gib=4)
        self.assertEqual(out, (10 * total) // 100)

    def test_adds_two_checkouts(self):
        out = preflight.required_free_bytes(0, 500, pct=10, floor_gib=4)
        # floor=4 GiB + 2*500 = 4 GiB + 1000
        self.assertEqual(out, 4 * (1024 ** 3) + 1000)


class TestAllowlist(unittest.TestCase):
    def test_empty_noop(self):
        preflight.enforce_allowlist.__wrapped__ if False else None
        # Just verify no exception
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as t:
            preflight.enforce_allowlist(Path(t), "")  # no raise
