import os
import signal
import subprocess
import time
import unittest
from pathlib import Path

from tests.builder.run_harness import PRIVATE_REPO, SCRIPT, RunTest, commit_oid, git, make_repo


class SymlinkTest(RunTest):
    def test_refuses_without_symlink(self):
        self.link.unlink()
        self.link.mkdir()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a symlink", result.stderr)
        self.assertEqual(self.stub_calls(), [])
        self.assertTrue(self.link.is_dir())

    def test_points_link_at_checkout_while_running(self):
        self.configure(plan="lz4 1.10.0\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({entry["link"] for entry in self.stub_calls()}, {str(self.tap)})
        self.assert_link_restored()

    def test_symlink_restored_on_failure(self):
        self.configure(plan="lz4 1.10.0\n", fail=("lz4",))
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assert_link_restored()

    def test_symlink_restored_when_a_step_aborts(self):
        self.configure(plan="lz4 1.10.0\n")
        (self.tap / "scripts/tap/render.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.built(), [])
        self.assert_link_restored()

    def test_symlink_restored_when_cancelled(self):
        self.configure(plan="lz4 1.10.0\n", sleep={"lz4": 2})
        argv = ["bash", str(SCRIPT)]
        quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        process = subprocess.Popen(argv, env=self.environment(), start_new_session=True, **quiet)
        deadline = time.monotonic() + 20
        while not self.stub_calls("build-formula.sh"):
            self.assertLess(time.monotonic(), deadline, "build-formula.sh was never called")
            time.sleep(0.05)
        os.killpg(process.pid, signal.SIGINT)
        os.killpg(process.pid, signal.SIGTERM)
        self.assertNotEqual(process.wait(timeout=20), 0)
        self.assert_link_restored()

    def test_original_target_is_saved_and_cleared(self):
        self.configure(plan="lz4 1.10.0\n")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual({entry["saved"] for entry in self.stub_calls()}, {True})
        self.assertFalse(self.saved_target.exists())

    def test_recovers_target_saved_by_interrupted_run(self):
        self.saved_target.parent.mkdir(parents=True)
        self.saved_target.write_text(f"{self.original}\n", encoding="utf-8")
        self.link.unlink()
        self.link.symlink_to(self.tap)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("recovering Taps link from a previous interrupted run", result.stderr)
        self.assert_link_restored()
        self.assertFalse(self.saved_target.exists())

    def test_refuses_when_link_already_points_at_checkout(self):
        self.link.unlink()
        self.link.symlink_to(self.tap)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("already points at", result.stderr)
        self.assertEqual(self.link.readlink(), self.tap)
        self.assertEqual(self.stub_calls(), [])


class BuildLoopTest(RunTest):
    def test_happy_path(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_argvs("fetch-api.sh"), [[]])
        self.assertEqual(self.stub_argvs("plan.py"), [["commit"], ["builds"]])
        self.assertEqual(self.stub_argvs("render.py"), [["--core-commit", self.core_commit]])
        bottles = self.tap / ".builder" / "bottles"
        builds = [["z3", "4.13.0", str(bottles / "z3")], ["llvm", "19.1.0", str(bottles / "llvm")]]
        self.assertEqual(self.stub_argvs("build-formula.sh"), builds)
        commits = [[self.branch, "z3", "z3: add 4.13.0 sequoia bottle"]]
        commits += [[self.branch, "llvm", "llvm: add 19.1.0 sequoia bottle", commit_oid("z3")]]
        self.assertEqual(self.stub_argvs("commit-formula.sh"), commits)
        summary = str(self.tap / ".builder" / "summary.md")
        self.assertEqual(self.stub_argvs("open-pr.sh"), [[self.branch, commit_oid("llvm"), summary]])
        log = (self.tap / ".builder" / "logs" / "llvm.log").read_text(encoding="utf-8")
        self.assertIn("committed llvm", log)
        self.assertIn("- llvm 19.1.0", self.summary())
        self.assertEqual(self.issues(), [])

    def test_environment_of_steps(self):
        self.configure(plan="lz4 1.10.0\n")
        self.assertEqual(self.run_script().returncode, 0)
        clone = self.root / "cache" / "homebrew-core"
        (fetch,) = self.stub_calls("fetch-api.sh")
        self.assertEqual(fetch["env"]["HOMEBREW_INTEL_DATA"], str(self.tap / ".builder" / "api"))
        (render,) = self.stub_calls("render.py")
        self.assertEqual(render["env"]["HOMEBREW_CORE_REPO"], str(clone))
        self.assertEqual(self.stub_calls("commit-formula.sh")[0]["env"]["TAP_DIR"], str(self.tap))
        self.assertEqual(git("-C", str(clone), "cat-file", "-t", self.core_commit), "commit")

    def test_core_clone_is_a_shallow_partial_fetch(self):
        self.assertEqual(self.run_script().returncode, 0)
        clone = str(self.root / "cache" / "homebrew-core")
        self.assertEqual(git("-C", clone, "rev-parse", "--is-shallow-repository"), "true")
        self.assertEqual(git("-C", clone, "config", "remote.origin.url"), str(self.root / "core"))
        self.assertEqual(git("-C", clone, "config", "remote.origin.partialclonefilter"), "blob:none")
        self.assertEqual(git("-C", clone, "show", f"{self.core_commit}:Formula/l/lz4.rb"), "core lz4")

    def test_core_clone_is_reused(self):
        clone = self.root / "cache" / "homebrew-core"
        self.assertEqual(self.run_script().returncode, 0)
        newer = make_repo(self.root / "core2", {"x": "y"})
        git("-C", str(self.root / "core"), "fetch", "-q", str(self.root / "core2"), "main:other")
        self.configure(plan="", commit=newer)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git("-C", str(clone), "cat-file", "-t", newer), "commit")

    def test_dependent_of_failed_formula_is_skipped(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n", fail=("z3",))
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.built(), ["z3"])
        self.assertEqual(self.stub_argvs("commit-formula.sh"), [])
        (issue,) = self.issues()
        self.assertEqual(issue[3:7], ["-R", PRIVATE_REPO, "--title", "build failed: z3 4.13.0"])
        body = Path(issue[issue.index("--body-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("error: z3 does not compile", body)
        self.assertIn("```", body)
        log = self.tap / ".builder" / "logs" / "z3.log"
        self.assertIn("error: z3 does not compile", log.read_text(encoding="utf-8"))
        self.assertIn("- z3 4.13.0", self.summary())
        self.assertIn("- llvm: dependency z3 did not build", self.summary())
        # Nothing was committed, so there is no branch and no pull request.
        self.assertEqual(self.stub_argvs("open-pr.sh"), [])
        self.assertIn("no commits in this run", result.stderr)

    def test_skip_cascades_through_skipped_dependencies(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\nrust 1.90.0 llvm\n", fail=("z3",))
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(self.built(), ["z3"])
        self.assertIn("- rust: dependency llvm did not build", self.summary())

    def test_unrelated_formula_still_builds(self):
        self.configure(plan="z3 4.13.0\nlz4 1.10.0\nllvm 19.1.0 z3\n", fail=("z3",))
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.built(), ["z3", "lz4"])
        self.assertEqual(self.stub_argvs("commit-formula.sh"), [[self.branch, "lz4", "lz4: add 1.10.0 sequoia bottle"]])

    def test_formula_missing_from_api_is_skipped(self):
        self.configure(plan="gone -\nlz4 1.10.0 gone\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.built(), [])
        self.assertIn("- gone: no API entry", self.summary())

    def test_issue_skipped_without_private_token(self):
        self.configure(plan="z3 4.13.0\n", fail=("z3",))
        result = self.run_script(PRIVATE_GH_TOKEN="")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.issues(), [])
        self.assertIn("PRIVATE_GH_TOKEN", result.stderr)

    def test_issue_uses_private_token(self):
        self.configure(plan="z3 4.13.0\n", fail=("z3",))
        self.assertEqual(self.run_script().returncode, 1)
        (call,) = [call for call in self.fake.calls() if call["argv"][:3] == ["gh", "issue", "create"]]
        self.assertEqual(call["env"]["GH_TOKEN"], "private-token")

    def test_force_names_are_passed_to_plan(self):
        result = self.run_script("--force", "z3", "--force", "lz4")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_argvs("plan.py")[1], ["builds", "--force", "z3", "--force", "lz4"])

    def test_child_reading_stdin_does_not_eat_the_plan(self):
        self.configure(plan="z3 4.13.0\nlz4 1.10.0\n", drain=["z3"])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.built(), ["z3", "lz4"])

    def test_invalid_plan_name_fails_without_removing_anything(self):
        victim = self.tap / ".builder" / "keep"
        victim.mkdir(parents=True)
        self.configure(plan="../keep 1.0\nlz4 1.10.0\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(victim.is_dir())
        self.assertEqual(self.built(), ["lz4"])
        self.assertIn("invalid formula name", result.stderr)

    def test_refused_commit_keeps_the_chain_on_the_last_own_commit(self):
        # commit-formula.sh refuses lz4 (say, after a foreign push); xz still chains on z3.
        self.configure(plan="z3 4.13.0\nlz4 1.10.0\nxz 5.6.3\n", commit_fail=["lz4"])
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        parents = [argv[3:] for argv in self.stub_argvs("commit-formula.sh")]
        self.assertEqual(parents, [[], [commit_oid("z3")], [commit_oid("z3")]])
        self.assertIn("- lz4 1.10.0: bottled, but the commit failed", self.summary())
        summary = str(self.tap / ".builder" / "summary.md")
        self.assertEqual(self.stub_argvs("open-pr.sh"), [[self.branch, commit_oid("xz"), summary]])

    def test_open_pr_failure_fails_the_run(self):
        # open-pr.sh exits 1 when the branch head is not the run's last commit.
        self.configure(plan="lz4 1.10.0\n", open_pr_fail=True)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        summary = str(self.tap / ".builder" / "summary.md")
        self.assertEqual(self.stub_argvs("open-pr.sh"), [[self.branch, commit_oid("lz4"), summary]])

    def test_commit_failure_after_build_is_a_failure(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n", commit_fail=["z3"], open_pr_fail=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.built(), ["z3"])
        self.assertIn("z3 4.13.0: bottled, but the commit failed", result.stderr)
        self.assertIn("llvm: dependency z3 did not build", result.stderr)
        self.assertIn("Failed:\n- z3 4.13.0: bottled, but the commit failed", result.stdout)
        log = (self.tap / ".builder" / "logs" / "z3.log").read_text(encoding="utf-8")
        self.assertIn("error: cannot commit z3", log)


class ArgumentsTest(RunTest):
    def test_dry_run_changes_nothing(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n", render={"Formula/z/z3.rb": "z3 v2\n"})
        result = self.run_script("--dry-run", GITHUB_RUN_NUMBER="", GH_TOKEN="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_link_restored()
        self.assertEqual({entry["script"] for entry in self.stub_calls()}, {"fetch-api.sh", "plan.py"})
        self.assertEqual(self.fake.argvs(), [])
        self.assertFalse((self.root / "cache").exists())
        self.assertEqual(git("-C", str(self.tap), "status", "--porcelain", "--", "Formula"), "")
        self.assertIn("llvm 19.1.0 z3", result.stdout)
        self.assertIn("before render", result.stdout)

    def test_requires_run_number(self):
        for value in ("", "4x2"):
            result = self.run_script(GITHUB_RUN_NUMBER=value)
            self.assertNotEqual(result.returncode, 0, value)
        self.assertEqual(self.stub_calls(), [])
        self.assert_link_restored()

    def test_rejects_bad_arguments(self):
        for args in (("--bogus",), ("--force",), ("--force", "../x")):
            self.assertEqual(self.run_script(*args).returncode, 2, args)
        self.assertEqual(self.stub_calls(), [])


if __name__ == "__main__":
    unittest.main()
