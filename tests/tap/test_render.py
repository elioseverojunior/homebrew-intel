import unittest

import render
from transform import TAP, apply_bottle

from tests.tap.fixtures import TAP_BOTTLE, RenderTestCase

HEADER_PREFIX = "# Generated from Homebrew/homebrew-core@"


class RenderTest(RenderTestCase):
    def test_render_writes_qualified_tree(self):
        self.enable('[formula.llvm]\nkind = "generated"\n')
        code, _, stderr = self.run_render()
        self.assertEqual((code, stderr), (0, ""))
        llvm, z3 = self.read("Formula/l/llvm.rb"), self.read("Formula/z/z3.rb")
        self.assertIn(f'depends_on "{TAP}/z3"', llvm)
        self.assertTrue(llvm.startswith(f"{HEADER_PREFIX}{self.first} "))
        self.assertTrue(z3.startswith(f"{HEADER_PREFIX}{self.first} "))
        self.assertNotIn("bottle do", llvm)

    def test_render_keeps_existing_bottle_block(self):
        self.enable('[formula.lz4]\nkind = "generated"\n')
        self.run_render()
        bottled = apply_bottle(self.read("Formula/l/lz4.rb"), TAP_BOTTLE)
        self.write(self.tap / "Formula/l/lz4.rb", bottled)
        code, _, _ = self.run_render()
        self.assertEqual(code, 0)
        self.assertEqual(self.read("Formula/l/lz4.rb"), bottled)

    def test_render_patch_conflict_writes_nothing(self):
        self.enable(f'[formula.llvm]\nkind = "patched"\nbase = "{self.first}"\n')
        bad_patch = "--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-not in the file\n+replacement\n"
        self.write(self.tap / "patches/llvm.patch", bad_patch)
        self.write(self.tap / "Formula/l/llvm.rb", "old\n")
        before = self.tree()
        code, _, stderr = self.run_render()
        self.assertNotEqual(code, 0)
        self.assertIn("llvm", stderr)
        self.assertEqual(self.tree(), before)

    def test_missing_patch_file_writes_nothing(self):
        self.enable(f'[formula.llvm]\nkind = "patched"\nbase = "{self.first}"\n')
        code, _, stderr = self.run_render()
        self.assertEqual(code, 1)
        self.assertIn("patches/llvm.patch", stderr)
        self.assertFalse((self.tap / "Formula").exists())

    def test_print_order(self):
        self.enable('[formula.llvm]\nkind = "generated"\n')
        code, stdout, _ = self.run_render("--print-order")
        self.assertEqual((code, stdout), (0, "z3\nllvm\n"))
        self.assertFalse((self.tap / "Formula").exists())

    def test_warns_about_files_outside_set(self):
        self.enable('[formula.lz4]\nkind = "generated"\n')
        self.write(self.tap / "Formula/s/stale.rb", "old\n")
        code, _, stderr = self.run_render()
        self.assertEqual(code, 0)
        self.assertIn("Formula/s/stale.rb", stderr)

    def test_make_patch_round_trips(self):
        self.enable(f'[formula.lz4]\nkind = "patched"\nbase = "{self.first}"\n')
        edited = render.render_formula(
            (self.core / "Formula/l/lz4.rb").read_text(encoding="utf-8"),
            name="lz4",
            commit=self.first,
            tap_names={"lz4"},
            patch=None,
            bottle_block=None,
        ).replace("  # filler 5\n", "")
        self.write(self.tap / "Formula/l/lz4.rb", apply_bottle(edited, TAP_BOTTLE))
        self.assertEqual(self.run_render("--make-patch", "lz4")[0], 0)
        self.assertIn("-  # filler 5", self.read("patches/lz4.patch"))
        self.assertEqual(self.run_render()[0], 0)
        self.assertEqual(self.read("Formula/l/lz4.rb"), apply_bottle(edited, TAP_BOTTLE))


if __name__ == "__main__":
    unittest.main()
