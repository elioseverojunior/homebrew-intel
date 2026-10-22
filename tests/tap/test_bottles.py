import contextlib
import io
import unittest

import bottles

SHA_A = "a" * 40
SHA_B = "b" * 40
LZ4_BLOCK = (
    "  bottle do\n"
    '    root_url "https://github.com/elioseverojunior/homebrew-intel/releases/download/lz4-1.10.0"\n'
    '    sha256 cellar: :any, sequoia: "abc"\n'
    "  end\n"
)


class BottlesTest(unittest.TestCase):
    def test_pkg_version_plain(self):
        self.assertEqual(bottles.pkg_version({"versions": {"stable": "1.10.0"}, "revision": 0}), "1.10.0")

    def test_pkg_version_revision(self):
        self.assertEqual(bottles.pkg_version({"versions": {"stable": "1.10.0"}, "revision": 2}), "1.10.0_2")

    def test_root_url_and_tag(self):
        self.assertEqual(bottles.release_tag("lz4", "1.10.0"), "lz4-1.10.0")
        self.assertEqual(
            bottles.root_url("lz4", "1.10.0"),
            "https://github.com/elioseverojunior/homebrew-intel/releases/download/lz4-1.10.0",
        )

    def test_bottle_release_tag(self):
        self.assertEqual(bottles.bottle_release_tag(LZ4_BLOCK), "lz4-1.10.0")
        self.assertIsNone(bottles.bottle_release_tag("  bottle do\n  end\n"))

    def test_api_core_commit_most_common(self):
        formulae = [{"tap_git_head": SHA_A}, {"tap_git_head": SHA_B}, {"tap_git_head": SHA_A}]
        self.assertEqual(bottles.api_core_commit(formulae), SHA_A)

    def test_api_core_commit_rejects_non_sha(self):
        with self.assertRaises(ValueError):
            bottles.api_core_commit([{"tap_git_head": "abc"}])

    def test_cli_root_url(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = bottles.main(["root-url", "lz4", "1.10.0"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), bottles.root_url("lz4", "1.10.0") + "\n")
