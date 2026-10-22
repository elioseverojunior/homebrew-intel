import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests.builder.fakes import FakeBin

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "run.sh"
PRIVATE_REPO = "elioseverojunior/homebrew-intel-private"
STUBBED = ("scripts/audit/fetch-api.sh", "scripts/tap/plan.py", "scripts/tap/render.py")
STUBBED += tuple(f"scripts/builder/{name}.sh" for name in ("build-formula", "commit-formula", "open-pr"))

# One stub stands in for every script run.sh calls. Each call is logged with
# where the Taps symlink pointed at that moment; stubs.json decides the plan,
# the files render.py rewrites, and which builds fail or stall.
STUB = """#!{python}
import json, os, sys, time
from pathlib import Path

root = Path({root!r})
config = json.loads((root / "stubs.json").read_text(encoding="utf-8"))
script, args = os.path.basename(sys.argv[0]), sys.argv[1:]
link = root / "Taps" / "homebrew-intel"
names = ("TAP_DIR", "HOMEBREW_INTEL_DATA", "HOMEBREW_CORE_REPO")
entry = {{
    "script": script,
    "argv": args,
    "link": os.readlink(link) if link.is_symlink() else None,
    "saved": (root / "cache" / "taps-link-target").is_file(),
    "env": {{name: os.environ.get(name) for name in names}},
}}
with open(root / "stubs.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps(entry) + "\\n")
if script == "plan.py":
    print(config["commit"] if args[0] == "commit" else config["plan"], end="")
elif script == "render.py":
    for relpath, text in config["render"].items():
        path = Path(os.environ["TAP_DIR"]) / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
elif script == "build-formula.sh":
    print(f"building {{args[0]}}", flush=True)
    if args[0] in config.get("drain", []):
        sys.stdin.read()
    time.sleep(config["sleep"].get(args[0], 0))
    if args[0] in config["fail"]:
        print(f"error: {{args[0]}} does not compile")
        sys.exit(1)
elif script == "commit-formula.sh" and args[1] in config.get("commit_fail", []):
    print(f"error: cannot commit {{args[1]}}", file=sys.stderr)
    sys.exit(1)
elif script == "open-pr.sh" and config.get("open_pr_fail"):
    sys.exit(1)
"""


def git(*args: str) -> str:
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    result = subprocess.run(["git", *identity, *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def make_repo(path: Path, files: dict[str, str]) -> str:
    for relpath, text in files.items():
        (path / relpath).parent.mkdir(parents=True, exist_ok=True)
        (path / relpath).write_text(text, encoding="utf-8")
    git("init", "-q", "-b", "main", str(path))
    git("-C", str(path), "add", ".")
    git("-C", str(path), "commit", "-q", "-m", "init")
    return git("-C", str(path), "rev-parse", "HEAD")


class RunTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.tap = self.root / "tap"
        make_repo(self.tap, {"Formula/l/lz4.rb": "lz4\n", "Formula/z/z3.rb": "z3\n"})
        self.write_stubs()
        self.core_commit = make_repo(self.root / "core", {"Formula/l/lz4.rb": "core lz4\n"})
        self.original = self.root / "original"
        self.original.mkdir()
        (self.root / "Taps").mkdir()
        self.link = self.root / "Taps" / "homebrew-intel"
        self.link.symlink_to(self.original)
        self.branch = f"bottle/{datetime.now(UTC).strftime('%Y-%m-%d')}-42"
        self.configure(plan="")

    def write_stubs(self) -> None:
        stub = STUB.format(python=sys.executable, root=str(self.root))
        for relpath in STUBBED:
            path = self.tap / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(stub, encoding="utf-8")
            path.chmod(0o755)

    def configure(self, plan: str, fail: tuple[str, ...] = (), **extra: object) -> None:
        config = {"commit": self.core_commit, "plan": plan, "fail": list(fail), "render": {}, "sleep": {}}
        (self.root / "stubs.json").write_text(json.dumps({**config, **extra}), encoding="utf-8")

    def environment(self, **extra: str) -> dict[str, str]:
        env = {
            **self.fake.environment(),
            "TAP_DIR": str(self.tap),
            "TAPS_LINK": str(self.link),
            "BUILDER_CACHE": str(self.root / "cache"),
            "BUILDER_CORE_URL": str(self.root / "core"),
            "GITHUB_RUN_NUMBER": "42",
            "GH_TOKEN": "app-token",
            "PRIVATE_GH_TOKEN": "private-token",
        }
        return {**env, **extra}

    def run_script(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        argv = ["bash", str(SCRIPT), *args]
        return subprocess.run(argv, env=self.environment(**extra), capture_output=True, text=True, check=False)

    def stub_calls(self, script: str | None = None) -> list[dict]:
        log = self.root / "stubs.jsonl"
        entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        return [entry for entry in entries if script in (None, entry["script"])]

    def stub_argvs(self, script: str) -> list[list[str]]:
        return [entry["argv"] for entry in self.stub_calls(script)]

    def built(self) -> list[str]:
        return [argv[0] for argv in self.stub_argvs("build-formula.sh")]

    def issues(self) -> list[list[str]]:
        return [argv for argv in self.fake.argvs() if argv[:3] == ["gh", "issue", "create"]]

    @property
    def saved_target(self) -> Path:
        return self.root / "cache" / "taps-link-target"

    def assert_link_restored(self) -> None:
        self.assertEqual(self.link.readlink(), self.original)

    def summary(self) -> str:
        return (self.tap / ".builder" / "summary.md").read_text(encoding="utf-8")


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
        commits += [[self.branch, "llvm", "llvm: add 19.1.0 sequoia bottle"]]
        self.assertEqual(self.stub_argvs("commit-formula.sh"), commits)
        summary = str(self.tap / ".builder" / "summary.md")
        self.assertEqual(self.stub_argvs("open-pr.sh"), [[self.branch, summary]])
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
        self.assertEqual(len(self.stub_argvs("open-pr.sh")), 1)

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


class RenderCommitTest(RunTest):
    def test_render_changes_are_committed_before_builds(self):
        short = self.core_commit[:7]
        render = {"Formula/l/lz4.rb": "lz4 v2\n", "Formula/x/xz.rb": "xz\n", "README.md": "x\n"}
        self.configure(plan="lz4 1.10.1\n", render=render)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        commits = self.stub_argvs("commit-formula.sh")
        self.assertEqual(
            commits,
            [
                [self.branch, "lz4", f"lz4: update from core {short}"],
                [self.branch, "xz", f"xz: update from core {short}"],
                [self.branch, "lz4", "lz4: add 1.10.1 sequoia bottle"],
            ],
        )

    def test_render_commit_happens_when_nothing_builds(self):
        self.configure(plan="", render={"Formula/z/z3.rb": "z3 v2\n"})
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual([argv[1] for argv in self.stub_argvs("commit-formula.sh")], ["z3"])
        self.assertEqual(len(self.stub_argvs("open-pr.sh")), 1)


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
