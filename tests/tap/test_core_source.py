import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core_source import CoreSourceError, core_repo, formula_relpath, head_commit, read_formula


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


class CoreSourceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "commit.gpgsign", "false")
        self.write("Formula/l/lz4.rb", "v1\n")
        self.write("Formula/lib/libfoo.rb", "foo\n")
        self.first = self.commit("first")

    def write(self, relpath: str, content: str) -> None:
        path = self.repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def test_relpath_shards(self):
        self.assertEqual(formula_relpath("lz4"), "Formula/l/lz4.rb")
        self.assertEqual(formula_relpath("libgit2"), "Formula/lib/libgit2.rb")
        self.assertEqual(formula_relpath("python@3.15"), "Formula/p/python@3.15.rb")

    def test_reads_formula_at_commit(self):
        self.write("Formula/l/lz4.rb", "v2\n")
        self.commit("second")
        self.assertEqual(read_formula(self.repo, "lz4", self.first), "v1\n")

    def test_head_commit_is_40_hex(self):
        self.assertRegex(head_commit(self.repo), re.compile(r"^[0-9a-f]{40}$"))

    def test_missing_commit_hints_fetch(self):
        with self.assertRaises(CoreSourceError) as context:
            read_formula(self.repo, "lz4", "f" * 40)
        self.assertIn("git -C", str(context.exception))
        self.assertIn("fetch", str(context.exception))

    def test_missing_formula_names_it(self):
        with self.assertRaises(CoreSourceError) as context:
            read_formula(self.repo, "nope", self.first)
        self.assertIn("nope", str(context.exception))
        self.assertIn(self.first, str(context.exception))

    def test_env_overrides_repo(self):
        with mock.patch.dict(os.environ, {"HOMEBREW_CORE_REPO": str(self.repo)}):
            self.assertEqual(core_repo(), self.repo)


if __name__ == "__main__":
    unittest.main()
