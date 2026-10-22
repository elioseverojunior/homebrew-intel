import os
import signal
import subprocess
import time
import unittest

from tests.builder.run_harness import SCRIPT, RunTest, git, make_repo


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

    def test_symlink_restored_after_a_failed_build(self):
        self.configure(plan="lz4 1.10.0\n", fail=("lz4",))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.section("failed"), ["lz4"])
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
        argv = ["bash", str(SCRIPT), "--build-only"]
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
    def test_happy_path_writes_the_manifest(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_argvs("fetch-api.sh"), [[]])
        self.assertEqual(self.stub_argvs("plan.py"), [["commit"], ["builds"]])
        self.assertEqual(self.stub_argvs("render.py"), [["--core-commit", self.core_commit]])
        bottles = self.tap / ".builder" / "bottles"
        builds = [["z3", "4.13.0", str(bottles / "z3")], ["llvm", "19.1.0", str(bottles / "llvm")]]
        self.assertEqual(self.stub_argvs("build-formula.sh"), builds)
        manifest = self.manifest()
        self.assertEqual(manifest["core_commit"], self.core_commit)
        self.assertEqual(manifest["tap_sha"], git("-C", str(self.tap), "rev-parse", "HEAD"))
        self.assertRegex(manifest["branch_date"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
        (z3, llvm) = manifest["built"]
        self.assertEqual((z3["name"], llvm["name"], llvm["version"]), ("z3", "llvm", "19.1.0"))
        self.assertEqual(llvm["tarball"], "llvm-19.1.0.sequoia.bottle.tar.gz")
        self.assertTrue((self.out / "bottles" / llvm["tarball"]).is_file())
        self.assertEqual((self.out / "Formula/l/llvm.rb").read_text(encoding="utf-8"), "bottled llvm\n")
        self.assertIn("building llvm", (self.out / "logs" / "llvm.log").read_text(encoding="utf-8"))
        self.assertIn("## Built\n\n- z3 4.13.0\n- llvm 19.1.0\n", result.stdout)

    def test_no_github_call_and_no_secret(self):
        self.configure(plan="lz4 1.10.0\n")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual([argv for argv in self.fake.argvs() if argv[0] == "gh"], [])
        self.assertFalse(any(call["env"].get("GH_TOKEN") for call in self.fake.calls()))

    def test_environment_of_steps(self):
        self.configure(plan="lz4 1.10.0\n")
        self.assertEqual(self.run_script().returncode, 0)
        clone = self.root / "cache" / "homebrew-core"
        (fetch,) = self.stub_calls("fetch-api.sh")
        self.assertEqual(fetch["env"]["HOMEBREW_INTEL_DATA"], str(self.tap / ".builder" / "api"))
        (render,) = self.stub_calls("render.py")
        self.assertEqual(render["env"]["HOMEBREW_CORE_REPO"], str(clone))
        self.assertEqual(self.stub_calls("build-formula.sh")[0]["env"]["TAP_DIR"], str(self.tap))
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

    def test_stale_output_is_cleared(self):
        stale = self.out / "bottles" / "old.tar.gz"
        stale.parent.mkdir(parents=True)
        stale.write_text("old", encoding="utf-8")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertFalse(stale.exists())

    def test_dependent_of_failed_formula_is_skipped(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n", fail=("z3",))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.built(), ["z3"])
        manifest = self.manifest()
        self.assertEqual(manifest["failed"], [{"name": "z3", "version": "4.13.0", "log": "z3.log"}])
        self.assertEqual(manifest["skipped"], [{"name": "llvm", "reason": "dependency z3 did not build"}])
        self.assertEqual(manifest["built"], [])
        log = self.out / "logs" / "z3.log"
        self.assertIn("error: z3 does not compile", log.read_text(encoding="utf-8"))

    def test_skip_cascades_through_skipped_dependencies(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\nrust 1.90.0 llvm\n", fail=("z3",))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.built(), ["z3"])
        self.assertEqual(self.section("skipped"), ["llvm", "rust"])

    def test_unrelated_formula_still_builds(self):
        self.configure(plan="z3 4.13.0\nlz4 1.10.0\nllvm 19.1.0 z3\n", fail=("z3",))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.built(), ["z3", "lz4"])
        self.assertEqual(self.section("built"), ["lz4"])

    def test_build_without_a_bottle_is_a_failure(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n", no_bottle=["z3"])
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.section("failed"), ["z3"])
        self.assertEqual(self.section("skipped"), ["llvm"])
        self.assertIn("expected one *.bottle.json", (self.out / "logs" / "z3.log").read_text(encoding="utf-8"))

    def test_formula_missing_from_api_is_skipped(self):
        self.configure(plan="gone -\nlz4 1.10.0 gone\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.built(), [])
        self.assertEqual(self.manifest()["skipped"][0], {"name": "gone", "reason": "no API entry"})

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
        self.assertNotIn("../keep", json_names(self.manifest()))


def json_names(manifest: dict) -> list[str]:
    return [entry["name"] for section in ("built", "failed", "skipped", "render_only") for entry in manifest[section]]


class ArgumentsTest(RunTest):
    def test_dry_run_changes_nothing(self):
        self.configure(plan="z3 4.13.0\nllvm 19.1.0 z3\n", render={"Formula/z/z3.rb": "z3 v2\n"})
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_link_restored()
        self.assertEqual({entry["script"] for entry in self.stub_calls()}, {"fetch-api.sh", "plan.py"})
        self.assertEqual(self.fake.argvs(), [])
        self.assertFalse((self.root / "cache").exists())
        self.assertFalse(self.out.exists())
        self.assertEqual(git("-C", str(self.tap), "status", "--porcelain", "--", "Formula"), "")
        self.assertIn("llvm 19.1.0 z3", result.stdout)
        self.assertIn("before render", result.stdout)

    def test_requires_build_only(self):
        self.assertEqual(self.run_bare().returncode, 2)
        self.assertEqual(self.run_bare("--dry-run").returncode, 2)
        self.assertEqual(self.stub_calls(), [])

    def test_refuses_any_github_token(self):
        for secret in ("GH_TOKEN", "GITHUB_TOKEN", "PRIVATE_GH_TOKEN"):
            result = self.run_script(**{secret: "token"})
            self.assertEqual(result.returncode, 2, secret)
            self.assertIn(f"{secret} is set", result.stderr)
        self.assertEqual(self.stub_calls(), [])
        self.assert_link_restored()
        self.assertFalse(self.saved_target.exists())

    def test_rejects_bad_arguments(self):
        for args in (("--bogus",), ("--force",), ("--force", "../x")):
            self.assertEqual(self.run_script(*args).returncode, 2, args)
        self.assertEqual(self.stub_calls(), [])


if __name__ == "__main__":
    unittest.main()
