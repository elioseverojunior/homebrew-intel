import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import verify_bot_pr

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "verify_bot_pr.py"
REPO = "elioseverojunior/homebrew-intel"
# Trimmed from the live bot pull request #1 (gh api repos/.../pulls/1, /commits, /files).
PULL_REQUEST = {
    "number": 1,
    "user": {"login": "elios-automator[bot]", "type": "Bot"},
    "head": {"ref": "bottle/2026-10-22-2", "repo": {"full_name": REPO}},
    "base": {"ref": "main", "repo": {"full_name": REPO}},
}
COMMIT = {
    "sha": "5646363e5d4fc69def7c6ccad23a44a34e9e12a7",
    "author": {"login": "elios-automator[bot]", "type": "Bot"},
    "committer": {"login": "web-flow", "type": "User"},
    "commit": {
        "message": "lz4: add 1.10.0 sequoia bottle",
        "verification": {"verified": True, "reason": "valid"},
    },
}
FILE = {"filename": "Formula/l/lz4.rb", "status": "modified"}


class ProblemsTest(unittest.TestCase):
    def setUp(self):
        self.pull_request = copy.deepcopy(PULL_REQUEST)
        self.commits = [copy.deepcopy(COMMIT)]
        self.files = [copy.deepcopy(FILE)]

    def problems(self) -> list[str]:
        return verify_bot_pr.problems(self.pull_request, self.commits, self.files)

    def test_live_bot_pull_request_passes(self):
        self.assertEqual(self.problems(), [])

    def test_human_pull_request_is_not_a_bot_pr(self):
        self.pull_request["user"] = {"login": "elioseverojunior", "type": "User"}
        self.assertFalse(verify_bot_pr.is_bot_pr(self.pull_request))
        self.assertTrue(verify_bot_pr.is_bot_pr(PULL_REQUEST))

    def test_bot_login_without_bot_type_fails(self):
        self.pull_request["user"]["type"] = "User"
        self.assertIn("author type is 'User', not Bot", self.problems())

    def test_fork_fails(self):
        self.pull_request["head"]["repo"] = {"full_name": "someone/homebrew-intel"}
        self.assertIn(f"head repository 'someone/homebrew-intel' is not {REPO}", self.problems())

    def test_deleted_head_repository_fails(self):
        self.pull_request["head"]["repo"] = None
        self.assertIn(f"head repository 'None' is not {REPO}", self.problems())

    def test_head_ref_must_be_a_bottle_branch(self):
        for ref in ("main", "bottle/2026-10-22", "bottle/2026-10-22-2x", "xbottle/2026-10-22-2"):
            with self.subTest(ref=ref):
                self.pull_request["head"]["ref"] = ref
                self.assertIn(f"head ref '{ref}' is not bottle/<YYYY-MM-DD>-<run>", self.problems())

    def test_unverified_commit_fails(self):
        self.commits[0]["commit"]["verification"] = {"verified": False, "reason": "unsigned"}
        self.assertIn("commit 5646363e5d4f is not verified (unsigned)", self.problems())

    def test_commit_by_another_author_fails(self):
        self.commits.append(copy.deepcopy(COMMIT) | {"sha": "a" * 40, "author": {"login": "elioseverojunior"}})
        expected = "commit aaaaaaaaaaaa author is 'elioseverojunior', not elios-automator[bot]"
        self.assertEqual(self.problems(), [expected])

    def test_commit_without_linked_users_fails(self):
        self.commits[0]["author"] = None
        self.commits[0]["committer"] = None
        problems = self.problems()
        self.assertIn("commit 5646363e5d4f author is 'None', not elios-automator[bot]", problems)
        self.assertIn("commit 5646363e5d4f committer is 'None', not web-flow", problems)

    def test_commit_with_another_committer_fails(self):
        self.commits[0]["committer"] = {"login": "elios-automator[bot]"}
        self.assertIn("commit 5646363e5d4f committer is 'elios-automator[bot]', not web-flow", self.problems())

    def test_no_commits_fails(self):
        self.commits = []
        self.assertIn("pull request has no commits", self.problems())

    def test_file_outside_formula_fails(self):
        self.files.append({"filename": ".github/workflows/tests.yml", "status": "modified"})
        self.assertEqual(self.problems(), ["file '.github/workflows/tests.yml' is outside Formula/"])

    def test_rename_from_outside_formula_fails(self):
        self.files = [{"filename": "Formula/l/lz4.rb", "status": "renamed", "previous_filename": "scripts/x.sh"}]
        self.assertEqual(self.problems(), ["file 'scripts/x.sh' is outside Formula/"])

    def test_no_files_fails(self):
        self.files = []
        self.assertIn("pull request changes no files", self.problems())


class LoadPagesTest(unittest.TestCase):
    def test_concatenated_pages_are_flattened(self):
        text = json.dumps([{"a": 1}]) + json.dumps([{"b": 2}, {"c": 3}]) + "\n"
        self.assertEqual(verify_bot_pr.load_pages(text), [{"a": 1}, {"b": 2}, {"c": 3}])

    def test_empty_output_is_empty(self):
        self.assertEqual(verify_bot_pr.load_pages(""), [])


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def run_cli(self, pull_request: dict, commits: list, files: list) -> subprocess.CompletedProcess:
        paths = {}
        for name, document in (("event", {"pull_request": pull_request}), ("commits", commits), ("files", files)):
            paths[name] = self.root / f"{name}.json"
            paths[name].write_text(json.dumps(document), encoding="utf-8")
        argv = [sys.executable, str(SCRIPT), "--event", str(paths["event"])]
        argv += ["--commits", str(paths["commits"]), "--files", str(paths["files"])]
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    def test_verified_bot_pull_request_exits_zero(self):
        result = self.run_cli(PULL_REQUEST, [COMMIT], [FILE])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pull request #1 is a verified bot bottle PR (1 commits, 1 files)", result.stdout)

    def test_human_pull_request_is_skipped(self):
        human = PULL_REQUEST | {"user": {"login": "elioseverojunior", "type": "User"}}
        result = self.run_cli(human, [], [{"filename": "README.md"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not a bot PR — skipped", result.stdout)

    def test_failing_bot_pull_request_lists_every_problem(self):
        result = self.run_cli(PULL_REQUEST, [], [{"filename": "README.md"}])
        self.assertEqual(result.returncode, 1)
        self.assertIn("pull request has no commits", result.stderr)
        self.assertIn("file 'README.md' is outside Formula/", result.stderr)


if __name__ == "__main__":
    unittest.main()
