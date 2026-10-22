import unittest

import drift
import render
from transform import TAP, apply_bottle

from tests.tap.fixtures import API, BOTTLE, TAP_BOTTLE, RenderTestCase

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

    def render_lz4_bottled(self) -> str:
        self.enable('[formula.lz4]\nkind = "generated"\n')
        self.run_render()
        bottled = apply_bottle(self.read("Formula/l/lz4.rb"), TAP_BOTTLE)
        self.write(self.tap / "Formula/l/lz4.rb", bottled)
        return bottled

    def test_render_keeps_bottle_for_same_version(self):
        bottled = self.render_lz4_bottled()
        self.assertEqual(self.run_render()[0], 0)
        self.assertEqual(self.read("Formula/l/lz4.rb"), bottled)

    def test_render_drops_bottle_on_version_bump(self):
        self.render_lz4_bottled()
        api = {**API, "lz4": {**API["lz4"], "versions": {"stable": "1.10.1"}}}
        code, _, _ = self.run_render(api=api)
        self.assertEqual(code, 0)
        rendered = self.read("Formula/l/lz4.rb")
        self.assertTrue(rendered.startswith(HEADER_PREFIX))
        self.assertNotIn("bottle do", rendered)

    def test_render_keeps_bottle_for_formula_missing_from_api(self):
        bottled = self.render_lz4_bottled()
        api = {name: value for name, value in API.items() if name != "lz4"}
        self.assertEqual(self.run_render(api=api)[0], 0)
        self.assertEqual(self.read("Formula/l/lz4.rb"), bottled)

    def test_render_drops_bottle_without_root_url(self):
        self.render_lz4_bottled()
        self.write(self.tap / "Formula/l/lz4.rb", apply_bottle(self.read("Formula/l/lz4.rb"), BOTTLE))
        self.assertEqual(self.run_render()[0], 0)
        self.assertNotIn("bottle do", self.read("Formula/l/lz4.rb"))

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

    def test_render_patched_without_patch_bootstraps(self):
        self.enable(f'[formula.lz4]\nkind = "patched"\nbase = "{self.first}"\n')
        code, _, stderr = self.run_render()
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "render: lz4: no patches/lz4.patch yet; rendered unpatched\n")
        unpatched = self.read("Formula/l/lz4.rb")
        self.assertTrue(unpatched.startswith(f"{HEADER_PREFIX}{self.first} "))
        self.assertFalse((self.tap / "patches/lz4.patch").exists())
        self.assertEqual(drift.check(self.tap, self.core), [])
        self.write(self.tap / "Formula/l/lz4.rb", unpatched.replace("  # filler 5\n", ""))
        self.assertEqual(self.run_render("--make-patch", "lz4")[0], 0)
        code, _, stderr = self.run_render()
        self.assertEqual((code, stderr), (0, ""))
        self.assertNotIn("# filler 5", self.read("Formula/l/lz4.rb"))
        self.assertEqual(drift.check(self.tap, self.core), [])

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
