import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin
from tests.builder.run_harness import git, make_repo

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "fetch-core.sh"
COMPARE = "repos/Homebrew/homebrew-core/compare"


class FetchCoreTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.commit = make_repo(self.root / "upstream", {"Formula/l/lz4.rb": "core lz4\n"})
        self.clone = self.root / "core"

    def status(self, commit: str, status: str) -> None:
        self.fake.respond("gh", "api", f"{COMPARE}/{commit}...HEAD", "--jq", ".status", stdout=f"{status}\n")

    def run_script(self, *commits: str) -> subprocess.CompletedProcess:
        env = {**self.fake.environment(), "CORE_URL": str(self.root / "upstream"), "GH_TOKEN": "t"}
        argv = ["bash", str(SCRIPT), str(self.clone), *commits]
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=False)

    def test_fetches_a_commit_on_core_head(self):
        for status in ("ahead", "identical"):
            with self.subTest(status=status):
                self.status(self.commit, status)
                result = self.run_script(self.commit)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(git("-C", str(self.clone), "show", f"{self.commit}:Formula/l/lz4.rb"), "core lz4")
                self.assertEqual(git("-C", str(self.clone), "config", "remote.origin.partialclonefilter"), "blob:none")

    def test_refuses_a_commit_core_head_does_not_contain(self):
        self.status(self.commit, "diverged")
        result = self.run_script(self.commit)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{self.commit} is not on homebrew-core HEAD (status: diverged)", result.stderr)

    def test_an_api_error_fails_closed(self):
        self.fake.respond("gh", "api", f"{COMPARE}/{self.commit}...HEAD", stderr="gh: HTTP 500\n", exit_code=1)
        result = self.run_script(self.commit)
        self.assertNotEqual(result.returncode, 0)

    def test_refuses_a_malformed_commit_before_fetching(self):
        result = self.run_script("--upload-pack=evil")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.fake.argvs(), [])

    def test_no_commits_is_a_no_op(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fake.argvs(), [])


if __name__ == "__main__":
    unittest.main()
