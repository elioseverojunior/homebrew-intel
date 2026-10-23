import contextlib
import io
import unittest
from unittest import mock

import plan
from core_source import formula_relpath

from tests.tap.fixtures import API, BOTTLE, TapTestCase, formula

SHA = "a" * 40
FORMULAE = {
    **API,
    "z3": {**API["z3"], "versions": {"stable": "4.15.4"}, "tap_git_head": SHA},
    "llvm": {**API["llvm"], "versions": {"stable": "23.1.4"}, "build_dependencies": ["cmake"]},
}
ORDER = ["z3", "llvm"]


class PlanTestCase(TapTestCase):
    def put(self, name: str, *, bottled: bool) -> None:
        text = formula(name.capitalize())
        self.write(self.tap / formula_relpath(name), text if bottled else text.replace(BOTTLE, ""))

    def run_plan(self, *argv: str, formulae: dict | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(plan, "TAP_ROOT", self.tap),
            mock.patch.object(plan, "load_formulae", return_value=FORMULAE if formulae is None else formulae),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = plan.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def needs(self, forced: frozenset[str] = frozenset()) -> list[str]:
        return plan.needs_build(ORDER, self.tap, FORMULAE, forced)


class NeedsBuildTest(PlanTestCase):
    def test_unbottled_formula_is_built(self):
        self.put("z3", bottled=False)
        self.put("llvm", bottled=True)
        self.assertEqual(self.needs(), ["z3", "llvm"])

    def test_bottled_formula_is_skipped(self):
        self.put("z3", bottled=True)
        self.put("llvm", bottled=True)
        self.assertEqual(self.needs(), [])

    def test_dependent_of_built_formula_is_built(self):
        self.put("z3", bottled=False)
        self.put("llvm", bottled=True)
        self.assertEqual(self.needs(), ["z3", "llvm"])

    def test_forced_formula_is_built(self):
        self.put("z3", bottled=True)
        self.put("llvm", bottled=True)
        self.assertEqual(self.needs(frozenset({"z3"})), ["z3", "llvm"])

    def test_missing_file_is_built(self):
        self.put("z3", bottled=True)
        self.assertEqual(self.needs(), ["llvm"])

    def test_tap_dependencies_are_restricted_to_order(self):
        self.assertEqual(plan.tap_dependencies("llvm", ORDER, FORMULAE), ["z3"])
        self.assertEqual(plan.tap_dependencies("z3", ORDER, FORMULAE), [])

    def test_tap_dependencies_include_build_and_test_dependencies(self):
        formulae = {**FORMULAE, "llvm": {**FORMULAE["llvm"], "dependencies": [], "test_dependencies": ["z3"]}}
        self.assertEqual(plan.tap_dependencies("llvm", ["cmake", *ORDER], formulae), ["cmake", "z3"])

    def test_tap_dependencies_use_the_intel_variation(self):
        intel = {"dependencies": [], "build_dependencies": [], "test_dependencies": ["z3"]}
        llvm = {**FORMULAE["llvm"], "variations": {"sequoia": intel, "arm64_sequoia": {"dependencies": []}}}
        formulae = {**FORMULAE, "llvm": llvm}
        self.assertEqual(plan.tap_dependencies("llvm", ["cmake", *ORDER], formulae), ["z3"])


class PlanCliTest(PlanTestCase):
    def test_builds_cli_prints_deps(self):
        self.put("z3", bottled=False)
        self.put("llvm", bottled=True)
        self.enable('[formula.llvm]\nkind = "generated"\n')
        self.assertEqual(self.run_plan("builds"), (0, "z3 4.15.4\nllvm 23.1.4 z3\n", ""))

    def test_builds_cli_prints_dash_for_formula_absent_from_api(self):
        self.put("lz4", bottled=False)
        self.enable('[formula.lz4]\nkind = "generated"\n')
        code, out, _ = self.run_plan("builds", formulae={})
        self.assertEqual((code, out), (0, "lz4 -\n"))

    def test_unknown_force_name_fails(self):
        self.enable('[formula.llvm]\nkind = "generated"\n')
        code, out, err = self.run_plan("builds", "--force", "nope")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("nope", err)

    def test_dependency_cycle_fails_with_one_line(self):
        self.enable('[formula.llvm]\nkind = "generated"\n')
        formulae = {**FORMULAE, "z3": {**FORMULAE["z3"], "test_dependencies": ["llvm"]}}
        code, out, err = self.run_plan("builds", formulae=formulae)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.count("\n"), 1, err)
        self.assertTrue(err.startswith("plan: dependency cycle llvm -> z3 -> llvm"), err)

    def test_commit_cli_prints_sha(self):
        self.assertEqual(self.run_plan("commit"), (0, f"{SHA}\n", ""))


if __name__ == "__main__":
    unittest.main()
