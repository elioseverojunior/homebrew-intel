import unittest

from tests.builder.run_harness import RunTest, git


class PinnedCoreCommitTest(RunTest):
    """--core-commit pins the run to the homebrew-core commit the prepare job resolved."""

    def pin_newer_core_commit(self) -> str:
        core = str(self.root / "core")
        (self.root / "core" / "Formula/l/lz4.rb").write_text("core lz4 v2\n", encoding="utf-8")
        git("-C", core, "commit", "-q", "-am", "bump")
        return git("-C", core, "rev-parse", "HEAD")

    def test_pinned_commit_replaces_the_api_commit(self):
        pinned = self.pin_newer_core_commit()
        self.configure(plan="lz4 1.10.0\n")
        result = self.run_script("--core-commit", pinned)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stub_argvs("render.py"), [["--core-commit", pinned]])
        self.assertEqual(self.manifest()["core_commit"], pinned)
        clone = str(self.root / "cache" / "homebrew-core")
        self.assertEqual(git("-C", clone, "show", f"{pinned}:Formula/l/lz4.rb"), "core lz4 v2")
        self.assertIn(f"API snapshot is at core {self.core_commit}; rendering at the pinned {pinned}", result.stderr)

    def test_matching_api_commit_logs_no_difference(self):
        result = self.run_script("--core-commit", self.core_commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["core_commit"], self.core_commit)
        self.assertNotIn("API snapshot is at core", result.stderr)

    def test_dry_run_prints_the_pinned_commit(self):
        pinned = "a" * 40
        result = self.run_script("--dry-run", "--core-commit", pinned)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"dry run: core commit {pinned}", result.stdout)
        self.assertIn("a planned formula keeps its render, pinned header included", result.stdout)
        self.assertIn("header-only changes are reverted and other changes recorded render-only", result.stdout)

    def test_invalid_core_commit_is_refused(self):
        for args in (("--core-commit",), ("--core-commit", "abc"), ("--core-commit", "A" * 40)):
            self.assertEqual(self.run_script(*args).returncode, 2, args)
        self.assertEqual(self.stub_calls(), [])


if __name__ == "__main__":
    unittest.main()
