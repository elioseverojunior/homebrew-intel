import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "build-formula.sh"
TAP = "elioseverojunior/intel"
REPO = "elioseverojunior/homebrew-intel"
TAG = "lz4-1.10.0"
ROOT_URL = f"https://github.com/{REPO}/releases/download/{TAG}"
ASSET = "lz4-1.10.0.sequoia.bottle.tar.gz"
BOTTLE_JSON = "lz4--1.10.0.sequoia.bottle.json"
INFO = ["brew", "info", "--json=v2", "--installed", "lz4"]
BUILD = ["brew", "install", "--build-bottle", f"{TAP}/lz4"]
SAFEGUARDS = {
    "HOMEBREW_NO_AUTO_UPDATE": "1",
    "HOMEBREW_NO_INSTALL_CLEANUP": "1",
    "HOMEBREW_NO_INSTALL_UPGRADE": "1",
    "HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK": "1",
}


def installed_from(tap: str) -> str:
    formula = {"name": "lz4", "tap": tap, "installed": [{"version": "1.10.0"}]}
    return json.dumps({"formulae": [formula], "casks": []})


class BuildFormulaTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        out = tempfile.TemporaryDirectory()
        self.addCleanup(out.cleanup)
        self.out = Path(out.name).resolve()

    def installed(self, tap: str) -> None:
        self.fake.respond(*INFO, stdout=installed_from(tap))

    def run_script(self) -> subprocess.CompletedProcess:
        argv = ["bash", str(SCRIPT), "lz4", "1.10.0", str(self.out)]
        return subprocess.run(argv, env=self.fake.environment(), capture_output=True, text=True, check=False)

    def test_happy_path_call_order(self):
        self.installed("homebrew/core")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        merge = ["brew", "bottle", "--merge", "--write", "--no-commit", str(self.out / BOTTLE_JSON)]
        self.assertEqual(
            self.fake.argvs(),
            [
                INFO,
                ["brew", "uninstall", "--ignore-dependencies", "lz4"],
                BUILD,
                ["brew", "test", f"{TAP}/lz4"],
                ["brew", "bottle", "--json", f"--root-url={ROOT_URL}", f"{TAP}/lz4"],
                ["gh", "release", "view", TAG, "-R", REPO],
                ["gh", "release", "upload", TAG, str(self.out / ASSET), "--clobber", "-R", REPO],
                merge,
            ],
        )
        self.assertEqual(self.fake.calls()[4]["cwd"], str(self.out))
        self.assertTrue((self.out / ASSET).is_file())
        self.assertFalse((self.out / "lz4--1.10.0.sequoia.bottle.tar.gz").exists())

    def test_existing_release_uses_clobber(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        gh_calls = [argv for argv in self.fake.argvs() if argv[0] == "gh"]
        self.assertEqual(gh_calls[1], ["gh", "release", "upload", TAG, str(self.out / ASSET), "--clobber", "-R", REPO])

    def test_missing_release_is_created(self):
        self.fake.fail("gh", "release", "view")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        create = ["gh", "release", "create", TAG, str(self.out / ASSET), "--title", TAG]
        create += ["--notes", "lz4 1.10.0 Intel bottles", "-R", REPO]
        self.assertEqual([argv for argv in self.fake.argvs() if argv[0] == "gh"][1], create)

    def test_build_failure_restores_previous_keg(self):
        self.installed("homebrew/core")
        self.fake.fail(*BUILD)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        argvs = self.fake.argvs()
        self.assertEqual(argvs[argvs.index(BUILD) + 1 :][-1], ["brew", "install", "lz4"])
        self.assertNotIn(["brew", "test", f"{TAP}/lz4"], argvs)

    def test_upload_failure_restores_tap_keg(self):
        self.installed(TAP)
        self.fake.fail("gh", "release", "upload")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        argvs = self.fake.argvs()
        self.assertEqual(argvs[-2], ["brew", "uninstall", "--ignore-dependencies", "lz4"])
        self.assertEqual(argvs[-1], ["brew", "install", f"{TAP}/lz4"])

    def test_not_installed_skips_uninstall_and_restore(self):
        self.fake.respond(*INFO, stdout="Error: No such keg: /usr/local/Cellar/lz4\n", exit_code=1)
        self.fake.fail(*BUILD)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.fake.argvs(), [INFO, BUILD])

    def test_empty_installed_list_skips_uninstall(self):
        self.fake.respond(*INFO, stdout=json.dumps({"formulae": [], "casks": []}))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fake.argvs()[1], BUILD)

    def test_safeguard_env_is_set(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.fake.calls():
            if call["argv"][0] == "brew":
                self.assertEqual({key: call["env"].get(key) for key in SAFEGUARDS}, SAFEGUARDS)

    def test_rejects_bad_arguments(self):
        argv = ["bash", str(SCRIPT), "../lz4", "1.10.0", str(self.out)]
        result = subprocess.run(argv, env=self.fake.environment(), capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.fake.argvs(), [])
