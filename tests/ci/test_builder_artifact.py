import hashlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import builder_artifact

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "builder_artifact.py"
DIGEST = "sha256:" + "a" * 64
ARTIFACT = {"id": 42, "name": "builder-out", "digest": DIGEST, "expired": False}


def zipped(members: dict[str, bytes], symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


class SelectTest(unittest.TestCase):
    def test_exactly_one_builder_out_is_selected(self):
        other = ARTIFACT | {"id": 7, "name": "logs"}
        self.assertEqual(builder_artifact.select([other, ARTIFACT]), (42, DIGEST))

    def test_none_or_two_builder_outs_are_refused(self):
        for artifacts in ([], [ARTIFACT, ARTIFACT | {"id": 43}]):
            with self.subTest(artifacts=artifacts), self.assertRaises(ValueError):
                builder_artifact.select(artifacts)

    def test_expired_or_malformed_artifact_is_refused(self):
        for broken in ({"expired": True}, {"digest": None}, {"digest": "md5:x"}, {"id": "42"}, {"id": 0}):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                builder_artifact.select([ARTIFACT | broken])

    def test_cli_prints_job_outputs_from_paginated_listing(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as listing:
            listing.write(json.dumps([ARTIFACT | {"id": 7, "name": "x"}]) + json.dumps([ARTIFACT]))
        self.addCleanup(Path(listing.name).unlink)
        argv = [sys.executable, str(SCRIPT), "select", listing.name]
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, f"id=42\ndigest={DIGEST}\n"), result.stderr)


class UnpackTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.download, self.out = self.root / "download", self.root / "out"
        self.download.mkdir()

    def place(self, data: bytes, name: str = "builder-out.zip") -> str:
        (self.download / name).write_bytes(data)
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def unpack(self, digest: str) -> None:
        builder_artifact.unpack(self.download, digest, self.out)

    def test_matching_digest_is_extracted(self):
        digest = self.place(zipped({"manifest.json": b"{}", "bottles/a.tar.gz": b"tar"}))
        self.unpack(digest)
        self.assertEqual((self.out / "bottles/a.tar.gz").read_bytes(), b"tar")
        self.assertEqual((self.out / "manifest.json").read_bytes(), b"{}")

    def test_other_digest_is_refused_and_nothing_extracted(self):
        self.place(zipped({"manifest.json": b"{}"}))
        with self.assertRaises(ValueError):
            self.unpack(DIGEST)
        self.assertFalse(self.out.exists())

    def test_download_must_be_one_regular_file(self):
        digest = self.place(zipped({"manifest.json": b"{}"}))
        self.place(b"x", "second.zip")
        with self.assertRaises(ValueError):
            self.unpack(digest)
        (self.download / "second.zip").unlink()
        (self.download / "builder-out.zip").rename(self.root / "real.zip")
        (self.download / "builder-out.zip").symlink_to(self.root / "real.zip")
        with self.assertRaises(ValueError):
            self.unpack(digest)

    def test_unsafe_members_are_refused(self):
        for members, symlink in (({"../evil": b"x"}, None), ({"/abs": b"x"}, None), ({"a": b"x"}, "link")):
            with self.subTest(members=members, symlink=symlink):
                digest = self.place(zipped(members, symlink))
                with self.assertRaises(ValueError):
                    self.unpack(digest)
                self.assertFalse(self.out.exists())

    def test_existing_output_is_refused(self):
        digest = self.place(zipped({"manifest.json": b"{}"}))
        self.out.mkdir()
        (self.out / "stale").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.unpack(digest)


if __name__ == "__main__":
    unittest.main()
