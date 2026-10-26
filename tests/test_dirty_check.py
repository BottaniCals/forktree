"""Regression tests for the source-tree dirty pre-flight.

`forktree`'s own worktrees root (``<project>/<worktrees_dir>/``) lives inside
the repository the "clean" pre-flight inspects. Once it holds a checkout git
reports it as untracked, so the check used to refuse every `create` after the
first one with "source tree is dirty" — forktree poisoning its own pre-flight.

The pre-flight must ignore forktree's own artifact while still refusing on
genuine user dirt, and the worktrees root must be kept out of the user's
`git status` via the repository-local `.git/info/exclude` (never the tracked
`.gitignore`).

Every `create` below runs with `--skip-disk-check`: the disk pre-flight is
orthogonal to this behaviour and would otherwise make the suite depend on the
free space of the host.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.forktree import cli, preflight
from src.forktree.config import Config


DIRTY_MESSAGE = "forktree: create: source tree is dirty; pass --skip-dirty-check to override"
WARNING_MESSAGE = "forktree: warning: --skip-dirty-check set; source tree is dirty"


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True, text=True, check=True,
    )


def _make_repo(path: Path, *, files: dict | None = None) -> None:
    """Create a repo with one commit. `files` are committed as tracked files."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@e.com")
    _git(path, "config", "user.name", "T")
    names = ["README.md"]
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    for name, content in (files or {}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        names.append(name)
    _git(path, "add", *names)
    _git(path, "commit", "-q", "-m", "init")


@unittest.skipUnless(shutil.which("git"), "git not on PATH")
class _RepoCase(unittest.TestCase):
    """Shared fixture: an isolated repo plus an isolated global config."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        # The project lives in a subdirectory so that a worktrees_dir of
        # "../worktrees" resolves inside the temporary tree.
        self.project = self.root / "repo"
        self.xdg = self.root / "xdg"
        self.xdg.mkdir(parents=True, exist_ok=True)
        # Isolate from the developer's real ~/.config/forktree/config.toml and
        # from a stray FORKTREE_STRICT=1 in the environment.
        patcher = mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.xdg),
            "FORKTREE_STRICT": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- helpers --

    def run_cli(self, *argv):
        """Run the real CLI entry point. Returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def create(self, slug, *flags, project=None):
        return self.run_cli(
            "create", "--skip-disk-check", *flags,
            str(project if project is not None else self.project), slug,
        )

    def set_global_worktrees_dir(self, value: str) -> None:
        """Configure `paths.worktrees_dir` through the global config layer."""
        d = self.xdg / "forktree"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.toml").write_text(
            f'[paths]\nworktrees_dir = "{value}"\n', encoding="utf-8"
        )

    def exclude_file(self, project=None) -> Path:
        return (project if project is not None else self.project) / ".git" / "info" / "exclude"

    def drop_exclude_entry(self, pattern: str = "/.worktrees/") -> None:
        """Undo the ignore entry so the worktrees root is visible to git again."""
        exclude = self.exclude_file()
        kept = [
            ln for ln in exclude.read_text(encoding="utf-8").splitlines()
            if ln.strip() != pattern
        ]
        exclude.write_text("\n".join(kept) + "\n", encoding="utf-8")

    def assert_exit(self, code):
        """The exit-code set is closed: {0, 1, 2, 3}."""
        self.assertIn(code, (0, 1, 2, 3))

    def assert_stdout_path(self, out):
        """On success stdout is exactly one line holding an absolute path."""
        lines = out.splitlines()
        self.assertEqual(len(lines), 1, f"stdout must be one line, got {out!r}")
        path = Path(lines[0])
        self.assertTrue(path.is_absolute(), f"stdout path must be absolute: {lines[0]!r}")
        return path


class TestDirtyCheckScenarios(_RepoCase):
    """The user-visible behaviour of the dirty pre-flight."""

    # -- 1..3: repeated creates must all succeed --

    def test_01_clean_tree_first_create(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assert_stdout_path(out)

    def test_02_second_create_succeeds(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        # Undo the ignore entry: the worktrees root now holds a checkout and
        # git reports it as untracked — exactly the reported false positive.
        self.drop_exclude_entry()
        self.assertIn("?? .worktrees/", _git(self.project, "status", "--porcelain").stdout)
        code, out, err = self.create("second")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assert_stdout_path(out)
        self.assertNotIn("dirty", err)

    def test_03_third_create_succeeds(self):
        _make_repo(self.project)
        for slug in ("first", "second", "third"):
            code, out, err = self.create(slug)
            self.assert_exit(code)
            self.assertEqual(code, 0, err)
            self.assert_stdout_path(out)

    # -- 4..6: genuine dirt must still be refused --

    def test_04_modified_tracked_file_is_refused(self):
        _make_repo(self.project)
        (self.project / "README.md").write_text("changed\n", encoding="utf-8")
        code, out, err = self.create("x")
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    def test_05_unrelated_untracked_file_is_refused(self):
        _make_repo(self.project)
        (self.project / "other-untracked.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("x")
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    def test_06_worktrees_root_plus_unrelated_untracked_file_is_refused(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        (self.project / "other-untracked.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("second")
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    # -- 7: the tracked .gitignore is never touched --

    def test_07_tracked_gitignore_is_never_modified(self):
        _make_repo(self.project, files={".gitignore": ".worktrees/\n"})
        before = (self.project / ".gitignore").read_bytes()
        for slug in ("first", "second"):
            code, out, err = self.create(slug)
            self.assertEqual(code, 0, err)
        self.assertEqual((self.project / ".gitignore").read_bytes(), before)
        status = _git(self.project, "status", "--porcelain").stdout
        self.assertNotIn(".gitignore", status)

    # -- 8..11: configured worktrees_dir variants --

    def test_08_custom_relative_worktrees_dir(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir("wt")
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        code, out, err = self.create("second")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.assert_stdout_path(out), self.project / "wt" / "second")

    def test_09_absolute_worktrees_dir_under_project(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir(str(self.project / "abs-wt"))
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        code, out, err = self.create("second")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assertNotIn("fatal:", err)
        self.assertEqual(
            self.assert_stdout_path(out), self.project / "abs-wt" / "second",
        )

    def test_10_worktrees_dir_outside_repo_does_not_fatal(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir("../worktrees")
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        code, out, err = self.create("second")
        self.assert_exit(code)
        self.assertIn(code, (0, 1))
        self.assertNotIn("fatal:", err)
        self.assertNotIn("is outside repository", err)

    def test_11_worktrees_dir_outside_repo_creates_worktree_there(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir("../worktrees")
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        code, out, err = self.create("second")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            self.assert_stdout_path(out), self.root / "worktrees" / "second",
        )
        # The repository itself stays clean — nothing was created inside it.
        self.assertEqual(_git(self.project, "status", "--porcelain").stdout, "")

    # -- 12..13: the info/exclude entry is written once --

    def test_12_info_exclude_holds_exactly_one_pattern(self):
        _make_repo(self.project)
        for slug in ("first", "second", "third"):
            code, out, err = self.create(slug)
            self.assertEqual(code, 0, err)
        lines = [
            ln for ln in self.exclude_file().read_text(encoding="utf-8").splitlines()
            if ln.strip() == "/.worktrees/"
        ]
        self.assertEqual(len(lines), 1)

    def test_13_info_exclude_is_byte_identical_across_invocations(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        before = self.exclude_file().read_bytes()
        code, out, err = self.create("second")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.exclude_file().read_bytes(), before)

    # -- 14..15: the exit-code and stdout contracts --

    def test_14_exit_codes_stay_in_the_closed_set(self):
        _make_repo(self.project)
        for argv in (
            ("create", "--skip-disk-check", str(self.project), "ok"),
            ("list", str(self.project)),
            ("remove", str(self.project), "missing"),
            ("gc", "--dry-run", str(self.project)),
        ):
            code, out, err = self.run_cli(*argv)
            self.assert_exit(code)

    def test_15_stdout_is_empty_on_failure_and_one_path_on_success(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        self.assert_stdout_path(out)
        (self.project / "other-untracked.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("second")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")

    # -- 16..17: --skip-dirty-check --

    def test_16_skip_dirty_check_does_not_warn_on_the_false_positive(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        # Undo the ignore entry so the worktrees root is visible to git again.
        self.drop_exclude_entry()
        self.assertIn("?? .worktrees/", _git(self.project, "status", "--porcelain").stdout)
        code, out, err = self.create("second", "--skip-dirty-check")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assertNotIn("source tree is dirty", err)

    def test_17_skip_dirty_check_still_warns_on_genuine_dirt(self):
        _make_repo(self.project)
        (self.project / "other-untracked.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("second", "--skip-dirty-check")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assertIn(WARNING_MESSAGE, err.splitlines())

    # -- 18: nested worktrees root --

    def test_18_nested_worktrees_dir(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir("wt/nested")
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        code, out, err = self.create("second")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            self.assert_stdout_path(out), self.project / "wt" / "nested" / "second",
        )

    # -- 19: whole-repository scope is preserved --

    def test_19_dirt_outside_the_project_path_still_fails(self):
        _make_repo(self.project)
        sub = self.project / "sub"
        sub.mkdir()
        (self.project / "outside.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("x", project=sub)
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    # -- 20: the user's own git status stays clean --

    def test_20_user_git_status_does_not_list_the_worktrees_root(self):
        _make_repo(self.project)
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        status = _git(self.project, "status", "--porcelain").stdout
        self.assertNotIn(".worktrees", status)

    # -- 21..27: degenerate worktrees_dir (the root is the repo/project dir) --

    def test_21_degenerate_root_still_refuses_a_modified_tracked_file(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir(".")
        (self.project / "README.md").write_text("changed\n", encoding="utf-8")
        code, out, err = self.create("x")
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    def test_22_degenerate_root_still_refuses_an_untracked_file(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir(".")
        (self.project / "other-untracked.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("x")
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    def test_23_degenerate_root_above_the_project_refuses_repo_level_dirt(self):
        _make_repo(self.project)
        sub = self.project / "sub"
        sub.mkdir()
        self.set_global_worktrees_dir("..")
        (self.project / "outside.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("x", project=sub)
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    def test_24_degenerate_root_equal_to_the_project_refuses_in_project_dirt(self):
        _make_repo(self.project)
        sub = self.project / "sub"
        sub.mkdir()
        self.set_global_worktrees_dir(".")
        (sub / "in-project.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("x", project=sub)
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn(DIRTY_MESSAGE, err.splitlines())

    def test_25_degenerate_root_writes_no_ignore_pattern(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir(".")
        exclude = self.exclude_file()
        before = exclude.read_bytes() if exclude.exists() else b""
        code, out, err = self.create("first")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.assert_stdout_path(out), self.project / "first")
        self.assertEqual(exclude.read_bytes(), before)
        self.assertNotIn("/./", exclude.read_text(encoding="utf-8"))
        # The user's own untracked files stay visible in `git status`.
        (self.project / "user-file.txt").write_text("x\n", encoding="utf-8")
        status = _git(
            self.project, "status", "--porcelain", "--untracked-files=all",
        ).stdout
        self.assertIn("user-file.txt", status)

    def test_26_degenerate_root_equal_to_the_project_writes_no_ignore_pattern(self):
        _make_repo(self.project)
        sub = self.project / "sub"
        sub.mkdir()
        self.set_global_worktrees_dir(".")
        exclude = self.project / ".git" / "info" / "exclude"
        before = exclude.read_bytes() if exclude.exists() else b""
        code, out, err = self.create("first", project=sub)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.assert_stdout_path(out), sub / "first")
        self.assertEqual(exclude.read_bytes(), before)
        self.assertNotIn("/sub/", exclude.read_text(encoding="utf-8"))
        # The user's own untracked files inside the project stay visible.
        (sub / "user-file.txt").write_text("x\n", encoding="utf-8")
        status = _git(
            self.project, "status", "--porcelain", "--untracked-files=all",
        ).stdout
        self.assertIn("user-file.txt", status)

    def test_27_degenerate_root_skip_dirty_check_still_reports_genuine_dirt(self):
        _make_repo(self.project)
        self.set_global_worktrees_dir(".")
        (self.project / "other-untracked.txt").write_text("x\n", encoding="utf-8")
        code, out, err = self.create("x", "--skip-dirty-check")
        self.assert_exit(code)
        self.assertEqual(code, 0, err)
        self.assert_stdout_path(out)
        self.assertIn(WARNING_MESSAGE, err.splitlines())


class TestExcludePathspecs(_RepoCase):
    """Unit-level tests for the pure exclusion-pathspec builder."""

    def _ctx(self, worktrees_dir: str, project: Path | None = None):
        cfg = Config(worktrees_dir=worktrees_dir)
        return preflight.PreflightContext(
            project_path=(project if project is not None else self.project).resolve(),
            slug="x",
            requested_ref="HEAD",
            cfg=cfg,
        )

    def test_default_root_yields_the_exclude_pair(self):
        _make_repo(self.project)
        ctx = self._ctx(".worktrees")
        self.assertEqual(
            preflight._exclude_pathspecs(ctx),
            [":(exclude).worktrees", ":(exclude).worktrees/**"],
        )

    def test_nested_root_yields_the_exclude_pair(self):
        _make_repo(self.project)
        ctx = self._ctx("wt/nested")
        self.assertEqual(
            preflight._exclude_pathspecs(ctx),
            [":(exclude)wt/nested", ":(exclude)wt/nested/**"],
        )

    def test_outside_repo_root_yields_no_excludes(self):
        _make_repo(self.project)
        ctx = self._ctx("../worktrees")
        self.assertEqual(preflight._exclude_pathspecs(ctx), [])

    def test_degenerate_root_at_the_repo_top_level_yields_no_excludes(self):
        _make_repo(self.project)
        ctx = self._ctx(".")
        self.assertEqual(preflight._exclude_pathspecs(ctx), [])

    def test_degenerate_root_above_the_project_yields_no_excludes(self):
        _make_repo(self.project)
        sub = self.project / "sub"
        sub.mkdir()
        ctx = self._ctx("..", project=sub)
        self.assertEqual(preflight._exclude_pathspecs(ctx), [])

    def test_degenerate_root_equal_to_the_project_dir_yields_no_excludes(self):
        _make_repo(self.project)
        sub = self.project / "sub"
        sub.mkdir()
        ctx = self._ctx(".", project=sub)
        self.assertEqual(preflight._exclude_pathspecs(ctx), [])

    def test_sibling_named_with_two_dots_is_not_treated_as_degenerate(self):
        _make_repo(self.project)
        ctx = self._ctx("..sibling")
        self.assertEqual(
            preflight._exclude_pathspecs(ctx),
            [":(exclude)..sibling", ":(exclude)..sibling/**"],
        )

    def test_unresolvable_repo_root_yields_no_excludes(self):
        plain = self.root / "not-a-repo"
        plain.mkdir()
        ctx = self._ctx(".worktrees", project=plain)
        self.assertEqual(preflight._exclude_pathspecs(ctx), [])


class TestSharedSeamRegression(_RepoCase):
    """The exclusion must not leak into the per-worktree dirty checks."""

    def test_dirty_worktree_is_still_reported_and_still_refused(self):
        _make_repo(self.project)
        code, out, err = self.create("wt1")
        self.assertEqual(code, 0, err)
        worktree = Path(out.strip())
        (worktree / "README.md").write_text("dirty\n", encoding="utf-8")

        code, out, err = self.run_cli("list", str(self.project), "--json")
        self.assertEqual(code, 0, err)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["dirty"], "a dirty worktree must still be reported dirty")

        code, out, err = self.run_cli("remove", str(self.project), "wt1")
        self.assert_exit(code)
        self.assertEqual(code, 1)
        self.assertIn("forktree: remove: worktree is dirty: wt1", err.splitlines())
