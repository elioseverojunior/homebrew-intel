import unittest

from tests.builder.run_harness import RunTest, commit_oid, git


class RenderCommitTest(RunTest):
    def test_unplanned_render_changes_are_committed_before_builds(self):
        short = self.core_commit[:7]
        render = {"Formula/l/lz4.rb": "lz4 v2\n", "Formula/x/xz.rb": "xz\n", "README.md": "x\n"}
        self.configure(plan="lz4 1.10.1\n", render=render)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        commits = [[self.branch, "xz", f"xz: update from core {short}"]]
        commits += [[self.branch, "lz4", "lz4: add 1.10.1 sequoia bottle", commit_oid("xz")]]
        self.assertEqual(self.stub_argvs("commit-formula.sh"), commits)

    def test_render_commit_happens_when_nothing_builds(self):
        self.configure(plan="", render={"Formula/z/z3.rb": "z3 v2\n"})
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual([argv[1] for argv in self.stub_argvs("commit-formula.sh")], ["z3"])
        summary = str(self.tap / ".builder" / "summary.md")
        self.assertEqual(self.stub_argvs("open-pr.sh"), [[self.branch, commit_oid("z3"), summary]])

    def test_plan_is_computed_after_render(self):
        self.configure(plan="", render={"Formula/z/z3.rb": "z3 v2\n"})
        self.assertEqual(self.run_script().returncode, 0)
        order = [entry["script"] for entry in self.stub_calls() if entry["script"] in ("render.py", "plan.py")]
        self.assertEqual(order, ["plan.py", "render.py", "plan.py"])

    def test_failed_planned_formula_commits_nothing(self):
        self.configure(plan="lz4 1.10.1\n", fail=("lz4",), render={"Formula/l/lz4.rb": "lz4 v2\n"})
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(self.stub_argvs("commit-formula.sh"), [])

    def test_header_only_change_is_restored(self):
        self.configure(plan="", render={"Formula/z/z3.rb": "# header b\nz3\n"})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_argvs("commit-formula.sh"), [])
        self.assertEqual(git("-C", str(self.tap), "status", "--porcelain", "--", "Formula"), "")

    def test_body_change_after_header_is_committed(self):
        self.configure(plan="", render={"Formula/z/z3.rb": "# header b\nz3 v2\n"})
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual([argv[1] for argv in self.stub_argvs("commit-formula.sh")], ["z3"])


if __name__ == "__main__":
    unittest.main()
