import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "pour-formula.sh"
TAP = "homebrew-intel/tap"
INFO = ["brew", "info", "--json=v2", "--installed", "lz4"]
UNINSTALL = ["brew", "uninstall", "--ignore-dependencies", "lz4"]
POUR = ["brew", "install", "--force-bottle", f"{TAP}/lz4"]
RESTORE_TAP = ["brew", "install", f"{TAP}/lz4"]
RESTORE_CORE = ["brew", "install", "lz4"]


class PourFormulaTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache = Path(cache.name)
        self.marker = self.cache / "pending-restore"
        formula = {"name": "lz4", "tap": TAP, "installed": [{"version": "1.10.0"}]}
        self.fake.respond(*INFO, stdout=json.dumps({"formulae": [formula], "casks": []}))

    def run_script(self, name: str = "lz4") -> subprocess.CompletedProcess:
        env = {**self.fake.environment(), "BUILDER_CACHE": str(self.cache)}
        return subprocess.run(["bash", str(SCRIPT), name], env=env, capture_output=True, text=True, check=False)

    def test_swaps_the_build_bottle_keg_for_a_pour(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fake.argvs(), [INFO, UNINSTALL, POUR])
        self.assertFalse(self.marker.exists())

    def test_not_installed_just_pours(self):
        self.fake.rules.clear()
        self.fake.respond(*INFO, stdout=json.dumps({"formulae": [], "casks": []}))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.fake.argvs(), [INFO, POUR])

    def test_pour_failure_restores_the_previous_keg(self):
        self.fake.fail(*POUR)
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(self.fake.argvs(), [INFO, UNINSTALL, POUR, UNINSTALL, RESTORE_TAP])
        self.assertFalse(self.marker.exists())

    def test_failed_tap_restore_falls_back_to_core(self):
        self.fake.fail(*POUR)
        self.fake.fail(*RESTORE_TAP)
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(self.fake.argvs()[-2:], [RESTORE_TAP, RESTORE_CORE])
        self.assertFalse(self.marker.exists())

    def test_marker_kept_when_nothing_could_be_restored(self):
        for argv in (POUR, RESTORE_TAP, RESTORE_CORE):
            self.fake.fail(*argv)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.marker.read_text(encoding="utf-8"), f"{TAP}/lz4\n")
        self.assertIn("reinstall it by hand", result.stderr)

    def test_rejects_a_bad_name_and_a_pending_restore(self):
        self.assertEqual(self.run_script("../lz4").returncode, 2)
        self.marker.write_text("zstd\n", encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("zstd is still uninstalled", result.stderr)
        self.assertNotIn(UNINSTALL, self.fake.argvs())


if __name__ == "__main__":
    unittest.main()
