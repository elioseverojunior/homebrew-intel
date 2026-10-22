import contextlib
import io
import unittest
from unittest import mock

import drift
from transform import apply_bottle

from tests.tap.fixtures import TAP_BOTTLE, RenderTestCase, git


class DriftTest(RenderTestCase):
    def setUp(self):
        super().setUp()
        self.enable('[formula.llvm]\nkind = "generated"\n')
        self.run_render()

    def test_drift_clean_after_render(self):
        self.assertEqual(drift.check(self.tap, self.core), [])

    def test_drift_flags_hand_edit(self):
        path = self.tap / "Formula/z/z3.rb"
        self.write(path, self.read("Formula/z/z3.rb").replace("  # filler 3\n", "  # edited\n"))
        problems = drift.check(self.tap, self.core)
        self.assertEqual(len(problems), 1)
        self.assertIn("Formula/z/z3.rb", problems[0])
        self.assertIn("+  # edited", problems[0])

    def test_drift_ignores_bottle_block_changes(self):
        path = self.tap / "Formula/l/llvm.rb"
        self.write(path, apply_bottle(self.read("Formula/l/llvm.rb"), TAP_BOTTLE))
        self.assertEqual(drift.check(self.tap, self.core), [])

    def test_drift_flags_misplaced_file(self):
        (self.tap / "Formula/l/llvm.rb").rename(self.tap / "Formula/llvm.rb")
        problems = drift.check(self.tap, self.core)
        misplaced = [problem for problem in problems if "Formula/l/llvm.rb" in problem]
        self.assertEqual(len(misplaced), 1)
        self.assertIn("Formula/llvm.rb", misplaced[0])

    def test_drift_flags_orphan_patch(self):
        self.write(self.tap / "patches/ghost.patch", "")
        problems = drift.check(self.tap, self.core)
        self.assertEqual(len(problems), 1)
        self.assertIn("patches/ghost.patch", problems[0])

    def test_drift_flags_enabled_without_file(self):
        self.enable('[formula.llvm]\nkind = "generated"\n[formula.lz4]\nkind = "generated"\n')
        problems = drift.check(self.tap, self.core)
        self.assertEqual(len(problems), 1)
        self.assertIn("lz4", problems[0])

    def test_drift_flags_base_mismatch(self):
        self.write(self.core / "README", "x\n")
        git(self.core, "add", "-A")
        git(self.core, "commit", "-q", "-m", "second")
        second = git(self.core, "rev-parse", "HEAD")
        self.enable(f'[formula.llvm]\nkind = "patched"\nbase = "{second}"\n')
        self.write(self.tap / "patches/llvm.patch", "")
        problems = drift.check(self.tap, self.core)
        self.assertEqual(len(problems), 1)
        self.assertIn(second, problems[0])
        self.assertIn(self.first, problems[0])

    def test_main_lists_commits(self):
        stdout = io.StringIO()
        with mock.patch.object(drift, "TAP_ROOT", self.tap), contextlib.redirect_stdout(stdout):
            code = drift.main(["--list-commits"])
        self.assertEqual((code, stdout.getvalue()), (0, f"{self.first}\n"))

    def test_main_exits_one_on_problems(self):
        self.write(self.tap / "patches/ghost.patch", "")
        stdout = io.StringIO()
        with mock.patch.object(drift, "TAP_ROOT", self.tap), contextlib.redirect_stdout(stdout):
            code = drift.main([])
        self.assertEqual(code, 1)
        self.assertIn("ghost", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
