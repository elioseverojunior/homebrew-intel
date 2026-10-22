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
HEAD_SHA = "5646363e5d4fc69def7c6ccad23a44a34e9e12a7"
# Trimmed from the live bot pull request #1 (gh api repos/.../pulls/1, /commits, /files).
PULL_REQUEST = {
    "number": 1,
    "user": {"login": "elios-automator[bot]", "type": "Bot"},
    "head": {"ref": "bottle/2026-10-22-2", "sha": HEAD_SHA, "repo": {"full_name": REPO}},
    "base": {"ref": "main", "repo": {"full_name": REPO}},
    "commits": 1,
    "changed_files": 1,
}
COMMIT = {
    "sha": HEAD_SHA,
    "author": {"login": "elios-automator[bot]", "type": "Bot"},
    "committer": {"login": "web-flow", "type": "User"},
    "commit": {
        "message": "lz4: add 1.10.0 sequoia bottle",
        "verification": {"verified": True, "reason": "valid"},
    },
}
FILE = {"filename": "Formula/l/lz4.rb", "status": "modified"}
# Shape of GET repos/{repo}/commits/{sha}/check-runs .check_runs[], trimmed.
CHECK_RUN = {
    "name": "bottle-builder",
    "head_sha": HEAD_SHA,
    "external_id": HEAD_SHA,
    "status": "completed",
    "conclusion": "success",
    "app": {"id": 4348245, "slug": "elios-automator"},
}
NO_CHECK = "head 5646363e5d4f has no successful bottle-builder check run from elios-automator"


class ProblemsTest(unittest.TestCase):
    def setUp(self):
        self.pull_request = copy.deepcopy(PULL_REQUEST)
        self.commits = [copy.deepcopy(COMMIT)]
        self.files = [copy.deepcopy(FILE)]
        self.check_runs = [copy.deepcopy(CHECK_RUN)]

    def problems(self) -> list[str]:
        evidence = verify_bot_pr.Evidence(self.commits, self.files, self.check_runs)
        return verify_bot_pr.problems(self.pull_request, evidence)

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
        self.pull_request["commits"] = 2
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

    def test_forged_commit_without_the_check_run_fails(self):
        # Verified, bot-authored, committed by web-flow: forgeable through the REST git API.
        self.check_runs = []
        self.assertEqual(self.problems(), [NO_CHECK])

    def test_check_run_from_another_app_fails(self):
        self.check_runs[0]["app"] = {"slug": "github-actions"}
        self.assertEqual(self.problems(), [NO_CHECK])

    def test_check_run_from_an_app_reusing_the_slug_fails(self):
        self.check_runs[0]["app"] = {"id": 1, "slug": "elios-automator"}
        self.assertEqual(self.problems(), [NO_CHECK])

    def test_check_run_needs_the_slug_too(self):
        self.check_runs[0]["app"] = {"id": 4348245, "slug": "renamed"}
        self.assertEqual(self.problems(), [NO_CHECK])

    def test_check_run_on_another_commit_fails(self):
        self.check_runs[0]["head_sha"] = "b" * 40
        self.assertEqual(self.problems(), [NO_CHECK])

    def test_check_run_with_another_external_id_fails(self):
        self.check_runs[0]["external_id"] = "c" * 40
        self.assertEqual(self.problems(), [NO_CHECK])

    def test_check_run_on_an_older_commit_fails(self):
        # The builder attested an earlier head; the pull request has moved on since.
        self.pull_request["head"]["sha"] = "d" * 40
        self.assertEqual(
            self.problems(), ["head dddddddddddd has no successful bottle-builder check run from elios-automator"]
        )

    def test_base_other_than_main_fails(self):
        self.pull_request["base"]["ref"] = "release"
        self.assertEqual(self.problems(), ["base ref 'release' is not main"])

    def test_unsuccessful_or_misnamed_check_run_fails(self):
        for change in ({"conclusion": "failure"}, {"name": "bottle-builder-2"}, {"app": None}):
            with self.subTest(change=change):
                self.check_runs = [CHECK_RUN | change]
                self.assertEqual(self.problems(), [NO_CHECK])

    def test_one_matching_check_run_among_others_passes(self):
        self.check_runs.insert(0, CHECK_RUN | {"app": {"slug": "github-actions"}})
        self.assertEqual(self.problems(), [])

    def test_commit_count_mismatch_fails(self):
        self.pull_request["commits"] = 2
        self.assertEqual(self.problems(), ["fetched 1 commits, but the pull request has 2"])

    def test_file_count_mismatch_fails(self):
        self.pull_request["changed_files"] = 3
        self.assertEqual(self.problems(), ["fetched 1 files, but the pull request has 3"])

    def test_counts_at_the_api_limits_fail(self):
        self.pull_request |= {"commits": 250, "changed_files": 3000}
        self.commits *= 250
        self.files *= 3000
        problems = self.problems()
        self.assertIn("250 commits reach the API listing limit of 250", problems)
        self.assertIn("3000 files reach the API listing limit of 3000", problems)

    def test_no_commits_fails(self):
        self.commits = []
        self.pull_request["commits"] = 0
        self.assertIn("pull request has no commits", self.problems())

    def test_file_outside_formula_fails(self):
        self.files.append({"filename": ".github/workflows/tests.yml", "status": "modified"})
        self.pull_request["changed_files"] = 2
        self.assertEqual(self.problems(), ["file '.github/workflows/tests.yml' is outside Formula/"])

    def test_rename_from_outside_formula_fails(self):
        self.files = [{"filename": "Formula/l/lz4.rb", "status": "renamed", "previous_filename": "scripts/x.sh"}]
        self.assertEqual(self.problems(), ["file 'scripts/x.sh' is outside Formula/"])

    def test_no_files_fails(self):
        self.files = []
        self.pull_request["changed_files"] = 0
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

    def run_cli(self, pull_request: dict, *pages: list) -> subprocess.CompletedProcess:
        argv = [sys.executable, str(SCRIPT)]
        documents = zip(
            ("event", "commits", "files", "check-runs"), ({"pull_request": pull_request}, *pages), strict=True
        )
        for name, document in documents:
            path = self.root / f"{name}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            argv += [f"--{name}", str(path)]
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    def test_verified_bot_pull_request_exits_zero(self):
        result = self.run_cli(PULL_REQUEST, [COMMIT], [FILE], [CHECK_RUN])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pull request #1 is a verified bot bottle PR (1 commits, 1 files)", result.stdout)

    def test_human_pull_request_is_skipped(self):
        human = PULL_REQUEST | {"user": {"login": "elioseverojunior", "type": "User"}}
        result = self.run_cli(human, [], [{"filename": "README.md"}], [])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not a bot PR — skipped", result.stdout)

    def test_failing_bot_pull_request_lists_every_problem(self):
        result = self.run_cli(PULL_REQUEST, [], [{"filename": "README.md"}], [])
        self.assertEqual(result.returncode, 1)
        self.assertIn(NO_CHECK, result.stderr)
        self.assertIn("pull request has no commits", result.stderr)
        self.assertIn("file 'README.md' is outside Formula/", result.stderr)


if __name__ == "__main__":
    unittest.main()
