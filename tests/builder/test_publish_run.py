import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin, fake_oid

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "publish.sh"
REPO = "elioseverojunior/homebrew-intel"
PRIVATE_REPO = "elioseverojunior/homebrew-intel-private"
BRANCH = "bottle/2026-10-22-42"
CORE = "c" * 40
TARBALL = "lz4-1.10.0.sequoia.bottle.tar.gz"
TAP_SHA = "d" * 40
NO_ASSETS = json.dumps({"assets": []})


class PublishRunCase(unittest.TestCase):
    """An artifact with two bottles and one render-only formula, and a fake GitHub."""

    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        self.fake.serve_git("mainsha")
        self.out, self.tap = self.directory(), self.directory()
        self.manifest = {"core_commit": CORE, "tap_sha": TAP_SHA, "branch_date": "2026-10-22"}
        self.manifest |= {"built": [], "failed": [], "skipped": [], "render_only": []}
        self.add_built("lz4", "1.10.0")
        self.add_built("zstd", "1.5.6")
        self.write(self.out / "Formula/x/xz.rb", "xz render\n")
        self.manifest["render_only"].append({"name": "xz", "relpath": "Formula/x/xz.rb"})
        self.save()

    def directory(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name).resolve()

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def add_built(self, name: str, version: str) -> None:
        tarball = f"{name}-{version}.sequoia.bottle.tar.gz"
        self.write(self.out / "bottles" / tarball, "tar")
        self.write(self.out / f"Formula/{name[0]}/{name}.rb", f"{name} bottled\n")
        entry = {"name": name, "version": version, "relpath": f"Formula/{name[0]}/{name}.rb", "tarball": tarball}
        self.manifest["built"].append(entry | {"json": f"{name}--{version}.sequoia.bottle.json"})

    def fail_build(self, name: str, version: str) -> None:
        self.write(self.out / "logs" / f"{name}.log", f"error: {name} does not compile\n")
        self.manifest["failed"].append({"name": name, "version": version, "log": f"{name}.log"})

    def save(self) -> None:
        self.write(self.out / "manifest.json", json.dumps(self.manifest))

    def run_script(self, **extra: str) -> subprocess.CompletedProcess:
        env = {**self.fake.environment(), "TAP_DIR": str(self.tap), "GITHUB_RUN_NUMBER": "42"}
        env |= {"GH_TOKEN": "app-token", "PRIVATE_GH_TOKEN": "private-token", **extra}
        argv = ["bash", str(SCRIPT), str(self.out)]
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=False)

    def commits(self) -> list[dict]:
        calls = [call for call in self.fake.calls() if call["argv"][:3] == ["gh", "api", "graphql"]]
        return [json.loads(call["stdin"])["variables"]["input"] for call in calls]

    def calls(self, *prefix: str) -> list[dict]:
        return [call for call in self.fake.calls() if call["argv"][: len(prefix)] == list(prefix)]


class PublishRunTest(PublishRunCase):
    def test_publishes_render_only_first_then_bottles_and_opens_the_pr(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        commits = self.commits()
        headlines = [commit["message"]["headline"] for commit in commits]
        expected = ["xz: update from core ccccccc", "lz4: add 1.10.0 sequoia bottle", "zstd: add 1.5.6 sequoia bottle"]
        self.assertEqual(headlines, expected)
        self.assertEqual([c["expectedHeadOid"] for c in commits], [TAP_SHA, fake_oid(1), fake_oid(2)])
        self.assertEqual(self.fake.git_state()["heads"]["main"], "mainsha", "main moved on; the branch did not")
        self.assertTrue(all(c["branch"]["branchName"] == BRANCH for c in commits))
        added = base64.b64decode(commits[1]["fileChanges"]["additions"][0]["contents"])
        self.assertEqual(added, b"lz4 bottled\n")
        (create,) = self.calls("gh", "pr", "create")
        self.assertIn(BRANCH, create["argv"])
        summary = Path(create["argv"][create["argv"].index("--body-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("## Built\n\n- lz4 1.10.0\n- zstd 1.5.6\n", summary)
        self.assertIn(f"head_sha={fake_oid(3)}", self.calls("gh", "api", f"repos/{REPO}/check-runs")[0]["argv"])

    def test_uploads_each_bottle_before_its_commit(self):
        self.fake.respond("gh", "release", "view", "lz4-1.10.0", stdout=NO_ASSETS)
        self.fake.fail("gh", "release", "view", "zstd-1.5.6")
        self.assertEqual(self.run_script().returncode, 0)
        upload = ["gh", "release", "upload", "lz4-1.10.0", str(self.out / "bottles" / TARBALL), "-R", REPO]
        create = ["gh", "release", "create", "zstd-1.5.6", str(self.out / "bottles/zstd-1.5.6.sequoia.bottle.tar.gz")]
        create += ["--title", "zstd-1.5.6", "--notes", "zstd 1.5.6 Intel bottles", "-R", REPO]
        argvs = self.fake.argvs()
        self.assertIn(upload, argvs)
        self.assertIn(create, argvs)
        graphql = [index for index, argv in enumerate(argvs) if argv[:3] == ["gh", "api", "graphql"]]
        self.assertLess(argvs.index(upload), graphql[1])
        self.assertEqual({call["env"]["GH_TOKEN"] for call in self.calls("gh", "release")}, {"app-token"})

    def test_failed_upload_skips_that_commit_and_fails_the_run(self):
        self.fake.respond("gh", "release", "view", "lz4-1.10.0", stdout=NO_ASSETS)
        self.fake.fail("gh", "release", "upload", "lz4-1.10.0")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        headlines = [commit["message"]["headline"] for commit in self.commits()]
        self.assertEqual(headlines, ["xz: update from core ccccccc", "zstd: add 1.5.6 sequoia bottle"])
        (create,) = self.calls("gh", "pr", "create")
        summary = Path(create["argv"][create["argv"].index("--body-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("## Not published\n\n- lz4 1.10.0: release upload failed\n", summary)

    def test_failed_builds_open_issues_with_the_private_token(self):
        self.fail_build("z3", "4.13.0")
        self.save()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        (issue,) = self.calls("gh", "issue", "create")
        self.assertEqual(issue["argv"][3:7], ["-R", PRIVATE_REPO, "--title", "build failed: z3 4.13.0"])
        self.assertEqual(issue["env"]["GH_TOKEN"], "private-token")
        body = Path(issue["argv"][issue["argv"].index("--body-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("error: z3 does not compile", body)
        self.assertIn("```\n", body)
        self.assertEqual(len(self.calls("gh", "pr", "create")), 1)

    def test_issue_skipped_without_private_token(self):
        self.fail_build("z3", "4.13.0")
        self.save()
        result = self.run_script(PRIVATE_GH_TOKEN="")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls("gh", "issue", "create"), [])
        self.assertIn("PRIVATE_GH_TOKEN", result.stderr)

    def test_nothing_to_commit_opens_no_pr(self):
        self.manifest["built"], self.manifest["render_only"] = [], []
        self.save()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commits(), [])
        self.assertEqual(self.calls("gh", "pr"), [])
        self.assertIn("no commits in this run", result.stderr)

    def test_all_failed_opens_issues_only(self):
        self.manifest["built"], self.manifest["render_only"] = [], []
        self.fail_build("lz4", "1.10.0")
        self.save()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        (issue,) = self.calls("gh", "issue", "create")
        self.assertIn("build failed: lz4 1.10.0", issue["argv"])
        self.assertEqual(self.commits(), [])
        self.assertEqual(self.calls("gh", "pr"), [])
        self.assertEqual(self.calls("gh", "release"), [])
        self.assertEqual(self.calls("gh", "api", f"repos/{REPO}/check-runs"), [])
        self.assertEqual(self.calls("gh", "api", f"repos/{REPO}/git/refs"), [])

    def test_refused_commit_keeps_the_chain_on_the_last_own_commit(self):
        self.fake.fail("gh", "release", "view", "lz4-1.10.0")
        self.fake.fail("gh", "release", "create", "lz4-1.10.0")
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual([c["expectedHeadOid"] for c in self.commits()], [TAP_SHA, fake_oid(1)])

    def test_open_pr_failure_fails_the_run(self):
        self.fake.fail("gh", "pr", "create")
        self.assertEqual(self.run_script().returncode, 1)

    def test_requires_token_run_number_and_manifest(self):
        for extra in ({"GH_TOKEN": ""}, {"GITHUB_RUN_NUMBER": "4x2"}):
            self.assertEqual(self.run_script(**extra).returncode, 2, extra)
        (self.out / "manifest.json").unlink()
        self.assertEqual(self.run_script().returncode, 2)
        self.assertEqual(self.fake.argvs(), [])


if __name__ == "__main__":
    unittest.main()
