import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin, fake_oid

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

    def commit(self, name: str = "lz4", headline: str = HEADLINE, *parent: str) -> subprocess.CompletedProcess:
        return self.run_script("commit-formula.sh", BRANCH, name, headline, *parent)

    def push_foreign_commit(self, head: str) -> None:
        state = self.fake.git_state()
        state["heads"][BRANCH] = head
        (self.fake.root / "git-state.json").write_text(json.dumps(state), encoding="utf-8")

    def mutations(self) -> list[dict]:
        calls = [call for call in self.fake.calls() if call["argv"][:3] == ["gh", "api", "graphql"]]
        return [json.loads(call["stdin"]) for call in calls]


class CommitFormulaTest(PublishTest):
    def test_creates_branch_once(self):
        self.fake.serve_git("abc123")
        self.assertEqual(self.commit("lz4").returncode, 0)
        self.assertEqual(self.commit("zstd", "zstd: 1.5", fake_oid(1)).returncode, 0)
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
        first = self.commit("lz4")
        second = self.commit("zstd", "zstd: add 1.5 sequoia bottle", first.stdout.strip())
        self.assertEqual((first.returncode, second.returncode), (0, 0), first.stderr + second.stderr)
        self.assertEqual((first.stdout, second.stdout), (f"{fake_oid(1)}\n", f"{fake_oid(2)}\n"))

    def test_second_commit_chains_on_the_expected_parent(self):
        self.fake.serve_git("abc123")
        self.assertEqual(self.commit("lz4").returncode, 0)
        self.assertEqual(self.commit("zstd", "zstd: add 1.5 sequoia bottle", fake_oid(1)).returncode, 0)
        first, second = (request["variables"]["input"] for request in self.mutations())
        self.assertEqual(first["expectedHeadOid"], "abc123")
        self.assertEqual(second["expectedHeadOid"], fake_oid(1))
        self.assertEqual(second["fileChanges"]["additions"][0]["path"], "Formula/z/zstd.rb")

    def test_foreign_head_refuses_the_commit(self):
        self.fake.serve_git("abc123")
        self.assertEqual(self.commit("lz4").returncode, 0)
        self.push_foreign_commit(FOREIGN)
        result = self.commit("zstd", "zstd: add 1.5 sequoia bottle", fake_oid(1))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"refusing: {BRANCH} head {FOREIGN} is not the expected parent {fake_oid(1)}", result.stderr)
        self.assertEqual(len(self.mutations()), 1)
        self.assertEqual(result.stdout, "")

    def test_existing_branch_without_a_parent_is_refused(self):
        self.fake.serve_git("abc123", {BRANCH: 1})
        result = self.commit()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"refusing: {BRANCH} already exists at {fake_oid(1)}", result.stderr)
        self.assertEqual(self.mutations(), [])
        self.assertNotIn(f"{API}git/refs", [argv[2] for argv in self.fake.argvs()])

    def test_missing_branch_with_a_parent_is_refused(self):
        self.fake.serve_git("abc123")
        result = self.commit("lz4", HEADLINE, fake_oid(1))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"refusing: {BRANCH} head  is not the expected parent", result.stderr)
        self.assertEqual(self.mutations(), [])

    def test_foreign_push_between_builder_commits_blocks_the_pr(self):
        self.fake.serve_git("abc123")
        first = self.commit("lz4")
        self.push_foreign_commit(FOREIGN)
        self.assertEqual(self.commit("zstd", "zstd: 1.5", first.stdout.strip()).returncode, 1)
        summary = self.tap / "summary.md"
        summary.write_text("Bottled lz4\n", encoding="utf-8")
        result = self.run_script("open-pr.sh", BRANCH, first.stdout.strip(), str(summary))
        self.assertEqual(result.returncode, 1)
        called = [argv[:3] for argv in self.fake.argvs()]
        self.assertNotIn(["gh", "api", f"{API}check-runs"], called)
        self.assertNotIn(["gh", "pr", "merge"], called)

    def test_graphql_failure_fails_the_script(self):
        self.fake.serve_git("abc123")
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
        bad += ((BRANCH, "lz4", HEADLINE, "commit1"), (BRANCH, "lz4", HEADLINE, EXPECTED, "extra"))
        for args in bad:
            result = self.run_script("commit-formula.sh", *args)
            self.assertNotEqual(result.returncode, 0, args)
        self.assertEqual(self.fake.argvs(), [])


if __name__ == "__main__":
    unittest.main()
