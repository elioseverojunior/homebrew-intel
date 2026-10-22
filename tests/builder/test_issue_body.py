import tempfile
import unittest
from pathlib import Path

import issue_body


class IssueBodyTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.logs = self.root / "logs"
        self.logs.mkdir()

    def body(self, log_name: str = "z3.log", name: str = "z3") -> str:
        return issue_body.issue_body(self.logs, log_name, name, "4.13.0")

    def test_fences_the_last_lines_of_the_log(self):
        (self.logs / "z3.log").write_text("".join(f"line {n}\n" for n in range(300)), encoding="utf-8")
        body = self.body()
        self.assertTrue(body.startswith("Last 200 lines of the z3 4.13.0 build log:\n\n```\nline 100\n"), body[:80])
        self.assertTrue(body.endswith("line 299\n```\n"))

    def test_mentions_are_neutralised_everywhere(self):
        (self.logs / "python@3.12.log").write_text("cc @elioseverojunior @org/team\n", encoding="utf-8")
        body = self.body("python@3.12.log", "python@3.12")
        self.assertNotIn("@", body)
        self.assertIn("python\uff203.12 4.13.0", body)
        self.assertIn("cc \uff20elioseverojunior \uff20org/team\n", body)

    def test_fence_outlasts_any_backtick_run_in_the_log(self):
        (self.logs / "z3.log").write_text("```\n`````\nend\n", encoding="utf-8")
        body = self.body()
        self.assertIn("\n``````\n```\n`````\nend\n``````\n", body)

    def test_size_is_capped(self):
        (self.logs / "z3.log").write_text("x" * (issue_body.MAX_LOG_BYTES * 3) + "\n", encoding="utf-8")
        self.assertLess(len(self.body()), issue_body.MAX_LOG_BYTES + 200)

    def test_only_regular_files_in_the_logs_directory(self):
        secret = self.root / "secret.log"
        secret.write_text("token\n", encoding="utf-8")
        (self.logs / "link.log").symlink_to(secret)
        (self.logs / "dir.log").mkdir()
        for log_name in ("link.log", "dir.log", "../secret.log", "missing.log", "z3"):
            with self.subTest(log_name=log_name):
                body = self.body(log_name)
                self.assertNotIn("token", body)
                self.assertIn("(no log)", body)

    def test_symlinked_logs_directory_is_not_read(self):
        real = self.root / "real"
        real.mkdir()
        (real / "z3.log").write_text("token\n", encoding="utf-8")
        self.logs.rmdir()
        self.logs.symlink_to(real)
        self.assertIn("(no log)", self.body())


if __name__ == "__main__":
    unittest.main()
