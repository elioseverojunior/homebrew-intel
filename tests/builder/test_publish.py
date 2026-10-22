import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "builder"
REPO = "elioseverojunior/homebrew-intel"
BRANCH = "bottle/2026-10-22-7"
API = f"repos/{REPO}/"
UNAUTHORIZED = {
    "stdout": '{"message":"Bad credentials","documentation_url":"https://docs.github.com/rest","status":"401"}',
    "stderr": "gh: Bad credentials (HTTP 401)\n",
    "exit_code": 1,
}
HEADLINE = "lz4: add 1.10.0 sequoia bottle"
PR_URL = f"https://github.com/{REPO}/pull/9"
AUTO_MERGE = ["gh", "pr", "merge", PR_URL, "--auto", "--squash", "-R", REPO]
EXPECTED = "e" * 40
FOREIGN = "f" * 40
CHECK_RUN = ["gh", "api", f"{API}check-runs", "-f", "name=bottle-builder", "-f", f"head_sha={EXPECTED}"]
CHECK_RUN += ["-f", f"external_id={EXPECTED}"]
CHECK_RUN += ["-f", "status=completed", "-f", "conclusion=success"]
CHECK_RUN += ["-f", "output[title]=Intel bottle builder"]
CHECK_RUN += ["-f", "output[summary]=Bottles built and committed by the private Intel builder."]


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tap = Path(directory.name).resolve()
        for relpath, text in (("Formula/l/lz4.rb", "class Lz4 < Formula\nend\n"), ("Formula/z/zstd.rb", "zstd\n")):
            (self.tap / relpath).parent.mkdir(parents=True)
            (self.tap / relpath).write_text(text, encoding="utf-8")

    def run_script(self, script: str, *args: str, **extra: str) -> subprocess.CompletedProcess:
        env = {**self.fake.environment(), "TAP_DIR": str(self.tap), "GH_TOKEN": "t", **extra}
        argv = ["bash", str(SCRIPTS / script), *args]
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=False)

    def commit(self, name: str = "lz4", headline: str = HEADLINE) -> subprocess.CompletedProcess:
        return self.run_script("commit-formula.sh", BRANCH, name, headline)

    def mutations(self) -> list[dict]:
        calls = [call for call in self.fake.calls() if call["argv"][:3] == ["gh", "api", "graphql"]]
        return [json.loads(call["stdin"]) for call in calls]


class CommitFormulaTest(PublishTest):
    def test_creates_branch_once(self):
        self.fake.serve_git("abc123")
        for name in ("lz4", "zstd"):
            self.assertEqual(self.commit(name).returncode, 0)
        creates = [argv for argv in self.fake.argvs() if argv[:3] == ["gh", "api", f"{API}git/refs"]]
        expected = ["gh", "api", f"{API}git/refs", "-f", f"ref=refs/heads/{BRANCH}", "-f", "sha=abc123"]
        self.assertEqual(creates, [expected])

    def test_commit_payload(self):
        self.fake.serve_git("abc123")
        result = self.commit()
        self.assertEqual(result.returncode, 0, result.stderr)
        (request,) = self.mutations()
        self.assertIn("createCommitOnBranch", request["query"])
        change = request["variables"]["input"]
        self.assertEqual(change["branch"], {"repositoryNameWithOwner": REPO, "branchName": BRANCH})
        self.assertEqual(change["expectedHeadOid"], "abc123")
        self.assertEqual(change["message"], {"headline": HEADLINE})
        (addition,) = change["fileChanges"]["additions"]
        self.assertEqual(addition["path"], "Formula/l/lz4.rb")
        self.assertEqual(base64.b64decode(addition["contents"]), (self.tap / "Formula/l/lz4.rb").read_bytes())

    def test_prints_the_created_commit_oid(self):
        self.fake.serve_git("abc123")
        first, second = self.commit("lz4"), self.commit("zstd", "zstd: add 1.5 sequoia bottle")
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertEqual((first.stdout, second.stdout), ("commit1\n", "commit2\n"))

    def test_second_commit_uses_new_head(self):
        self.fake.serve_git("abc123")
        self.assertEqual(self.commit("lz4").returncode, 0)
        self.assertEqual(self.commit("zstd", "zstd: add 1.5 sequoia bottle").returncode, 0)
        first, second = (request["variables"]["input"] for request in self.mutations())
        self.assertEqual(first["expectedHeadOid"], "abc123")
        self.assertEqual(second["expectedHeadOid"], "commit1")
        self.assertEqual(second["fileChanges"]["additions"][0]["path"], "Formula/z/zstd.rb")

    def test_graphql_failure_fails_the_script(self):
        self.fake.serve_git("abc123", {BRANCH: 0})
        self.fake.fail("gh", "api", "graphql")
        self.assertNotEqual(self.commit().returncode, 0)

    def test_non_404_ref_failure_aborts(self):
        self.fake.serve_git("abc123")
        self.fake.respond("gh", "api", f"{API}git/ref/heads/{BRANCH}", **UNAUTHORIZED)
        result = self.commit()
        self.assertNotEqual(result.returncode, 0)
        called = [argv[2] for argv in self.fake.argvs()]
        self.assertNotIn(f"{API}git/refs", called)
        self.assertNotIn("graphql", called)

    def test_rejects_bad_arguments(self):
        bad = (("main", "lz4", HEADLINE), (BRANCH, "../lz4", HEADLINE), (BRANCH, "lz4", ""), (BRANCH, "nope", HEADLINE))
        for args in bad:
            result = self.run_script("commit-formula.sh", *args)
            self.assertNotEqual(result.returncode, 0, args)
        self.assertEqual(self.fake.argvs(), [])


class OpenPullRequestTest(PublishTest):
    def setUp(self):
        super().setUp()
        self.summary = self.tap / "summary.md"
        self.summary.write_text("Bottled lz4\n", encoding="utf-8")

    def serve_branch(self, head: str = EXPECTED) -> None:
        """The branch exists two commits ahead of main, its remote head at `head`."""
        self.fake.serve_git(branches={BRANCH: 2})
        state_file = self.fake.root / "git-state.json"
        state = self.fake.git_state()
        state["heads"][BRANCH] = head
        state_file.write_text(json.dumps(state), encoding="utf-8")

    def pr_already_open(self) -> None:
        list_prs = ["gh", "pr", "list", "-R", REPO, "--head", BRANCH, "--state", "open", "--json", "number"]
        self.fake.respond(*list_prs, "--jq", "length", stdout="1\n")

    def open_pr(self, expected: str = EXPECTED) -> subprocess.CompletedProcess:
        return self.run_script("open-pr.sh", BRANCH, expected, str(self.summary))

    def created(self) -> list[list[str]]:
        return [argv for argv in self.fake.argvs() if argv[:3] == ["gh", "pr", "create"]]

    def called(self, prefix: list[str]) -> bool:
        return any(argv[: len(prefix)] == prefix for argv in self.fake.argvs())

    def test_matching_head_is_attested_then_opened_with_auto_merge(self):
        self.serve_branch()
        self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
        result = self.open_pr()
        self.assertEqual(result.returncode, 0, result.stderr)
        create = ["gh", "pr", "create", "-R", REPO, "--base", "main", "--head", BRANCH]
        create += ["--title", "bottles: 2026-10-22 run 7", "--body-file", str(self.summary)]
        argvs = self.fake.argvs()
        self.assertLess(argvs.index(CHECK_RUN), argvs.index(create))
        self.assertEqual(argvs[-2:], [create, AUTO_MERGE])
        self.assertEqual(result.stdout, f"{PR_URL}\n")

    def test_foreign_head_gets_no_check_run_nor_auto_merge(self):
        self.serve_branch(FOREIGN)
        self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
        result = self.open_pr()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"warning: {BRANCH} head {FOREIGN} is not the builder's {EXPECTED}", result.stderr)
        self.assertEqual(len(self.created()), 1)
        self.assertFalse(self.called(CHECK_RUN[:3]))
        self.assertFalse(self.called(["gh", "pr", "merge"]))

    def test_existing_pr_with_matching_head_is_attested_and_auto_merged(self):
        self.serve_branch()
        self.pr_already_open()
        result = self.open_pr()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already open", result.stderr)
        self.assertEqual(self.created(), [])
        self.assertIn(CHECK_RUN, self.fake.argvs())
        self.assertEqual(self.fake.argvs()[-1], ["gh", "pr", "merge", BRANCH, "--auto", "--squash", "-R", REPO])

    def test_existing_pr_with_foreign_head_is_left_alone(self):
        self.serve_branch(FOREIGN)
        self.pr_already_open()
        result = self.open_pr()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.created(), [])
        self.assertFalse(self.called(CHECK_RUN[:3]))
        self.assertFalse(self.called(["gh", "pr", "merge"]))

    def test_check_run_failure_warns_and_still_opens_the_pr(self):
        self.serve_branch()
        self.fake.respond(*CHECK_RUN[:3], stderr="gh: Resource not accessible by integration (HTTP 403)\n", exit_code=1)
        result = self.open_pr()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning: could not create the bottle-builder check run", result.stderr)
        self.assertEqual(len(self.created()), 1)

    def test_auto_merge_failure_only_warns(self):
        self.serve_branch()
        self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
        self.fake.respond(*AUTO_MERGE, stderr="auto-merge is not allowed for this repository\n", exit_code=1)
        result = self.open_pr()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fake.argvs()[-1], AUTO_MERGE)
        self.assertIn(f"warning: could not enable auto-merge on {PR_URL}", result.stderr)

    def test_failed_create_does_not_auto_merge(self):
        self.serve_branch()
        self.fake.fail("gh", "pr", "create")
        self.assertNotEqual(self.open_pr().returncode, 0)
        self.assertFalse(self.called(["gh", "pr", "merge"]))

    def test_open_pr_noop_without_commits(self):
        for branches in ({}, {BRANCH: 0}):
            with self.subTest(branches=branches):
                self.fake.serve_git(branches=branches)
                result = self.open_pr()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("nothing to open", result.stderr)
                self.assertEqual(self.created(), [])
                self.assertFalse(self.called(["gh", "pr", "merge"]))
                self.assertFalse(self.called(CHECK_RUN[:3]))

    def test_non_404_compare_failure_aborts(self):
        self.serve_branch()
        self.fake.respond("gh", "api", f"{API}compare/main...{BRANCH}", **UNAUTHORIZED)
        self.assertNotEqual(self.open_pr().returncode, 0)
        self.assertEqual(self.created(), [])

    def test_rejects_bad_arguments(self):
        for args in (("main", EXPECTED), (BRANCH, "commit2"), (BRANCH, EXPECTED.upper())):
            result = self.run_script("open-pr.sh", *args, str(self.summary))
            self.assertEqual(result.returncode, 2, args)
        self.assertEqual(self.run_script("open-pr.sh", BRANCH, str(self.summary)).returncode, 2)
        self.assertEqual(self.fake.argvs(), [])


if __name__ == "__main__":
    unittest.main()
