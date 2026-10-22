"""publish.sh never overwrites a release asset, and failure issues mention no one."""

import hashlib
import json
import unittest
from pathlib import Path

from tests.builder.test_publish_run import REPO, TARBALL, PublishRunCase

LZ4_TAG = "lz4-1.10.0"


def assets(*pairs: tuple[str, str | None]) -> str:
    return json.dumps({"assets": [{"name": name, "digest": digest} for name, digest in pairs]})


class PublishReleaseTest(PublishRunCase):
    def headlines(self) -> list[str]:
        return [commit["message"]["headline"] for commit in self.commits()]

    def lz4_digest(self) -> str:
        return "sha256:" + hashlib.sha256((self.out / "bottles" / TARBALL).read_bytes()).hexdigest()

    def test_never_clobbers(self):
        self.fake.respond("gh", "release", "view", LZ4_TAG, stdout=assets(("other.tar.gz", "sha256:" + "0" * 64)))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertFalse(any("--clobber" in argv for argv in self.fake.argvs()))
        (view,) = [argv for argv in self.fake.argvs() if argv[:4] == ["gh", "release", "view", LZ4_TAG]]
        self.assertEqual(view, ["gh", "release", "view", LZ4_TAG, "-R", REPO, "--json", "assets"])

    def test_identical_existing_asset_is_kept_and_committed(self):
        self.fake.respond("gh", "release", "view", LZ4_TAG, stdout=assets((TARBALL, self.lz4_digest())))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("gh", "release", "upload"), [])
        self.assertEqual(self.calls("gh", "release", "create", LZ4_TAG), [])
        self.assertIn("lz4: add 1.10.0 sequoia bottle", self.headlines())

    def test_existing_asset_with_another_digest_is_refused(self):
        for digest in ("sha256:" + "0" * 64, None):
            with self.subTest(digest=digest):
                self.fake.log.write_text("", encoding="utf-8")
                self.fake.rules.clear()
                self.fake.serve_git("mainsha")
                self.fake.respond("gh", "release", "view", LZ4_TAG, stdout=assets((TARBALL, digest)))
                result = self.run_script()
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.calls("gh", "release", "upload", LZ4_TAG), [])
                self.assertNotIn("lz4: add 1.10.0 sequoia bottle", self.headlines())
                self.assertIn(f"{LZ4_TAG} already has {TARBALL} with another digest", result.stderr)

    def test_asset_name_collision_refuses_every_claimant(self):
        clash = dict(self.entry("zstd"), tarball=TARBALL)
        self.manifest["built"] = [self.entry("lz4"), clash]
        self.save()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls("gh", "release"), [])
        self.assertEqual(self.headlines(), ["xz: update from core ccccccc"])
        self.assertIn(f"zstd 1.5.6: asset {TARBALL} is claimed by another formula", result.stderr)

    def test_issue_body_neutralises_mentions(self):
        self.fail_build("z3", "4.13.0")
        (self.out / "logs" / "z3.log").write_text("ping @elioseverojunior\n```\nbreakout\n", encoding="utf-8")
        self.save()
        self.assertEqual(self.run_script().returncode, 1)
        (issue,) = self.calls("gh", "issue", "create")
        body = Path(issue["argv"][issue["argv"].index("--body-file") + 1]).read_text(encoding="utf-8")
        self.assertNotIn("@", body)
        self.assertIn("ping \uff20elioseverojunior", body)
        self.assertIn("````\n", body)

    def entry(self, name: str) -> dict:
        return next(entry for entry in self.manifest["built"] if entry["name"] == name)


if __name__ == "__main__":
    unittest.main()
