import json
import subprocess
import unittest

from tests.builder.test_publish import (
    API,
    BRANCH,
    CHECK_RUN,
    EXPECTED,
    FOREIGN,
    PR_URL,
    REPO,
    UNAUTHORIZED,
    PublishTest,
)

AUTO_MERGE = ["gh", "pr", "merge", PR_URL, "--auto", "--squash", "--match-head-commit", EXPECTED, "-R", REPO]
RULES = ["gh", "api", f"{API}rules/branches/main"]
LIST_PRS = ["gh", "pr", "list", "-R", REPO, "--head", BRANCH, "--state", "open"]
LIST_PRS += ["--json", "number,headRepositoryOwner,author"]
GATE = {"context": "verify-bot-pr", "integration_id": 15368}


def gate_rule(*checks: dict) -> dict:
    return {"type": "required_status_checks", "parameters": {"required_status_checks": list(checks)}}


GATE_RULE = gate_rule(GATE)


def pull(number: int, owner: str = "elioseverojunior", author: str = "app/elios-automator") -> dict:
    return {"number": number, "headRepositoryOwner": {"login": owner}, "author": {"login": author, "is_bot": True}}


class OpenPullRequestTest(PublishTest):
    def setUp(self):
        super().setUp()
        self.summary = self.tap / "summary.md"
        self.summary.write_text("Bottled lz4\n", encoding="utf-8")

    def serve_branch(self, head: str = EXPECTED, rules: list | None = None) -> None:
        """The branch exists two commits ahead of main, its remote head at `head`; main has `rules`."""
        self.fake.respond(*RULES, stdout=json.dumps([GATE_RULE] if rules is None else rules))
        self.fake.serve_git(branches={BRANCH: 2})
        state_file = self.fake.root / "git-state.json"
        state = self.fake.git_state()
        state["heads"][BRANCH] = head
        state_file.write_text(json.dumps(state), encoding="utf-8")

    def open_prs(self, *pulls: dict) -> None:
        self.fake.respond(*LIST_PRS, stdout=json.dumps(list(pulls)))

    def pr_already_open(self) -> None:
        self.open_prs(pull(12))

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
        self.assertEqual(argvs[-1], AUTO_MERGE)
        self.assertLess(argvs.index(create), argvs.index(RULES))
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
        merge = ["gh", "pr", "merge", "12", "--auto", "--squash", "--match-head-commit", EXPECTED, "-R", REPO]
        self.assertEqual(self.fake.argvs()[-1], merge)

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

    def test_auto_merge_is_bound_to_the_attested_head(self):
        self.serve_branch()
        self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
        self.assertEqual(self.open_pr().returncode, 0)
        merge = next(argv for argv in self.fake.argvs() if argv[:3] == ["gh", "pr", "merge"])
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], EXPECTED)

    def test_no_auto_merge_without_the_verify_bot_pr_rule(self):
        other = gate_rule({"context": "drift", "integration_id": 15368})
        any_source = gate_rule({"context": "verify-bot-pr"})
        other_app = gate_rule({"context": "verify-bot-pr", "integration_id": 4348245})
        for rules in ([], [other], [{"type": "pull_request"}], [any_source], [other_app]):
            with self.subTest(rules=rules):
                self.fake.rules.clear()
                self.serve_branch(rules=rules)
                self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
                result = self.open_pr()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.called(["gh", "pr", "merge"]))
                self.assertIn("does not require verify-bot-pr; auto-merge not enabled", result.stderr)

    def test_failed_ruleset_lookup_skips_auto_merge(self):
        self.fake.respond(*RULES, stderr="gh: Not Found (HTTP 404)\n", exit_code=1)
        self.serve_branch()
        self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
        self.assertEqual(self.open_pr().returncode, 0)
        self.assertFalse(self.called(["gh", "pr", "merge"]))

    def test_fork_or_human_pr_on_the_same_branch_is_not_ours(self):
        self.serve_branch()
        self.open_prs(pull(3, owner="forker"), pull(4, author="someone"))
        self.fake.respond("gh", "pr", "create", stdout=f"{PR_URL}\n")
        result = self.open_pr()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.created()), 1)
        self.assertEqual(self.fake.argvs()[-1], AUTO_MERGE)

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
