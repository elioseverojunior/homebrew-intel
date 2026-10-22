import json
import os
import signal
import subprocess
import time
import unittest
from pathlib import Path

from tests.builder.run_harness import RunTest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "pour.sh"
TAP_LZ4 = "elioseverojunior/intel/lz4"


class PourTest(RunTest):
    def setUp(self):
        super().setUp()
        self.artifact = self.root / "artifact"
        manifest = {"core_commit": "c" * 40, "tap_sha": "d" * 40, "branch_date": "2026-10-22"}
        manifest |= {"failed": [], "skipped": [], "render_only": [{"name": "xz", "relpath": "Formula/x/xz.rb"}]}
        manifest["built"] = [self.built_entry("z3"), self.built_entry("lz4")]
        for relpath in ("Formula/x/xz.rb", "Formula/z/z3.rb", "Formula/l/lz4.rb"):
            (self.artifact / relpath).parent.mkdir(parents=True, exist_ok=True)
            (self.artifact / relpath).write_text(f"verified {relpath}\n", encoding="utf-8")
        (self.artifact / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    @staticmethod
    def built_entry(name: str) -> dict:
        entry = {"name": name, "version": "1.0", "relpath": f"Formula/{name[0]}/{name}.rb"}
        return entry | {"tarball": f"{name}-1.0.sequoia.bottle.tar.gz", "json": f"{name}--1.0.sequoia.bottle.json"}

    def pour(self, **extra: str) -> subprocess.CompletedProcess:
        argv = ["bash", str(SCRIPT), str(self.artifact)]
        return subprocess.run(argv, env=self.environment(**extra), capture_output=True, text=True, check=False)

    def poured(self) -> list[str]:
        return [argv[0] for argv in self.stub_argvs("pour-formula.sh")]

    def test_pours_each_built_formula_with_the_link_swapped(self):
        result = self.pour()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.poured(), ["z3", "lz4"])
        self.assertEqual({entry["link"] for entry in self.stub_calls("pour-formula.sh")}, {str(self.tap)})
        self.assert_link_restored()
        self.assertFalse(self.saved_target.exists())
        for relpath in ("Formula/x/xz.rb", "Formula/z/z3.rb", "Formula/l/lz4.rb"):
            self.assertEqual((self.tap / relpath).read_text(encoding="utf-8"), f"verified {relpath}\n")

    def test_a_failed_pour_does_not_stop_the_others(self):
        self.configure(plan="", fail=("z3",))
        result = self.pour()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.poured(), ["z3", "lz4"])
        self.assertIn("could not pour z3", result.stderr)
        self.assert_link_restored()

    def test_link_restored_when_cancelled(self):
        self.configure(plan="", sleep={"z3": 2})
        process = subprocess.Popen(
            ["bash", str(SCRIPT), str(self.artifact)],
            env=self.environment(),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while not self.stub_calls("pour-formula.sh"):
            self.assertLess(time.monotonic(), deadline, "pour-formula.sh was never called")
            time.sleep(0.05)
        os.killpg(process.pid, signal.SIGINT)
        os.killpg(process.pid, signal.SIGTERM)
        self.assertNotEqual(process.wait(timeout=20), 0)
        self.assert_link_restored()

    def test_refuses_tokens_and_a_real_directory(self):
        for secret in ("GH_TOKEN", "PRIVATE_GH_TOKEN"):
            self.assertEqual(self.pour(**{secret: "t"}).returncode, 2, secret)
        self.link.unlink()
        self.link.mkdir()
        result = self.pour()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a symlink", result.stderr)
        self.assertEqual(self.stub_calls(), [])

    def test_reinstalls_a_pending_keg_first(self):
        marker = self.root / "cache" / "pending-restore"
        marker.parent.mkdir(parents=True)
        marker.write_text(f"{TAP_LZ4}\n", encoding="utf-8")
        self.assertEqual(self.pour().returncode, 0)
        self.assertEqual(self.fake.argvs()[0], ["brew", "install", TAP_LZ4])
        self.assertFalse(marker.exists())

    def test_requires_a_manifest(self):
        (self.artifact / "manifest.json").unlink()
        self.assertEqual(self.pour().returncode, 2)
        self.assertEqual(self.stub_calls(), [])


if __name__ == "__main__":
    unittest.main()
