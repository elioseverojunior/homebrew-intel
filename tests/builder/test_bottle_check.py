import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import bottle_check

ROOT_URL = "https://github.com/elioseverojunior/homebrew-intel/releases/download/lz4-1.10.0"
CONTENT = b"bottle bytes"
SHA = hashlib.sha256(CONTENT).hexdigest()
TARBALL = "lz4-1.10.0.sequoia.bottle.tar.gz"
JSON_NAME = "lz4--1.10.0.sequoia.bottle.json"


def block(*middle: str) -> str:
    return "  bottle do\n" + "".join(f"    {line}\n" for line in middle) + "  end\n"


GOOD_BLOCK = block(f'root_url "{ROOT_URL}"', f'sha256 cellar: :any, sequoia: "{SHA}"')
DOCUMENT = {
    "elioseverojunior/intel/lz4": {
        "formula": {"name": "lz4", "pkg_version": "1.10.0"},
        "bottle": {
            "root_url": ROOT_URL,
            "rebuild": 0,
            "tags": {
                "sequoia": {"filename": TARBALL, "local_filename": "lz4--1.10.0.sequoia.bottle.tar.gz", "sha256": SHA}
            },
        },
    },
}


class BottleCheckTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tarball = Path(directory.name) / TARBALL
        self.tarball.write_bytes(CONTENT)
        self.document = copy.deepcopy(DOCUMENT)
        self.bottle = bottle_check.Bottle("lz4", "1.10.0", self.tarball, JSON_NAME)

    def problems(self, text: str = GOOD_BLOCK) -> list[str]:
        return bottle_check.problems(text, self.document, self.bottle)

    def tag(self) -> dict:
        return self.document["elioseverojunior/intel/lz4"]["bottle"]["tags"]["sequoia"]

    def test_good_bottle_passes(self):
        self.assertEqual(self.problems(), [])

    def test_cellar_forms_brew_writes_pass(self):
        for cellar in ("cellar: :any_skip_relocation, ", 'cellar: "/usr/local/Cellar", ', ""):
            text = block(f'root_url "{ROOT_URL}"', f'sha256 {cellar}sequoia: "{SHA}"')
            self.assertEqual(self.problems(text), [], cellar)

    def test_rebuild_must_match_the_tarball_and_json(self):
        rebuilt = self.tarball.with_name("lz4-1.10.0.sequoia.bottle.1.tar.gz")
        self.tarball.rename(rebuilt)
        self.bottle = self.bottle._replace(tarball=rebuilt)
        self.tag()["filename"] = rebuilt.name
        self.document["elioseverojunior/intel/lz4"]["bottle"]["rebuild"] = 1
        text = block(f'root_url "{ROOT_URL}"', "rebuild 1", f'sha256 cellar: :any, sequoia: "{SHA}"')
        self.assertEqual(self.problems(text), [])
        self.assertTrue(any("rebuild" in problem or "tarball" in problem for problem in self.problems()))

    def test_extra_lines_or_tags_fail(self):
        extra_tag = block(f'root_url "{ROOT_URL}"', f'sha256 cellar: :any, sequoia: "{SHA}"', f'sha256 sonoma: "{SHA}"')
        interpolated = block(f'root_url "{ROOT_URL}"', f'sha256 cellar: "#{{system "id"}}", sequoia: "{SHA}"')
        other_tag = block(f'root_url "{ROOT_URL}"', f'sha256 cellar: :any, arm64_sequoia: "{SHA}"')
        code = block(f'root_url "{ROOT_URL}"', 'system "curl evil"', f'sha256 cellar: :any, sequoia: "{SHA}"')
        for text in (extra_tag, interpolated, other_tag, code, GOOD_BLOCK.replace("  end\n", "  end \n")):
            self.assertNotEqual(self.problems(text), [], text)

    def test_wrong_root_url_fails(self):
        text = GOOD_BLOCK.replace("lz4-1.10.0", "zstd-1.5.6")
        self.assertIn(f"root_url is not {ROOT_URL}", " ".join(self.problems(text)))

    def test_sha_must_match_the_tarball_and_the_json(self):
        self.tarball.write_bytes(b"other bytes")
        self.assertIn("does not match the tarball", " ".join(self.problems()))
        self.tarball.write_bytes(CONTENT)
        self.tag()["sha256"] = "0" * 64
        self.assertIn("bottle JSON sha256", " ".join(self.problems()))

    def test_json_filename_must_decode_to_the_tarball(self):
        self.tag()["filename"] = "zstd-1.5.6.sequoia.bottle.tar.gz"
        self.assertNotEqual(self.problems(), [])
        self.tag()["filename"] = TARBALL.replace("-", "%2D")
        self.assertEqual(self.problems(), [])

    def test_json_shape_is_checked(self):
        self.document["elioseverojunior/intel/lz4"]["bottle"]["tags"]["sonoma"] = self.tag()
        self.assertNotEqual(self.problems(), [])
        self.document = {"elioseverojunior/intel/zstd": DOCUMENT["elioseverojunior/intel/lz4"]}
        self.assertNotEqual(self.problems(), [])
        self.document = {"elioseverojunior/intel/lz4": {"bottle": None}}
        self.assertIn("malformed bottle JSON", " ".join(self.problems()))

    def test_file_names_follow_brew(self):
        self.bottle = self.bottle._replace(json_name="evil.json")
        self.assertIn("bottle JSON evil.json is not", " ".join(self.problems()))


if __name__ == "__main__":
    unittest.main()
