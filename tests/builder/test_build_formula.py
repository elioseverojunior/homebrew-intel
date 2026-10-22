import json
import os
import signal
import subprocess
import tempfile
import time
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
UNINSTALL = ["brew", "uninstall", "--ignore-dependencies", "lz4"]
RESTORE_CORE = ["brew", "install", "lz4"]
RESTORE_TAP = ["brew", "install", f"{TAP}/lz4"]
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
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.cache = Path(cache.name)
        self.marker = self.cache / "pending-restore"

    def installed(self, tap: str) -> None:
        self.fake.respond(*INFO, stdout=installed_from(tap))

    def argv(self, name: str = "lz4", version: str = "1.10.0") -> list[str]:
        return ["bash", str(SCRIPT), name, version, str(self.out)]

    def environment(self) -> dict[str, str]:
        return {**self.fake.environment(), "BUILDER_CACHE": str(self.cache)}

    def run_script(self, name: str = "lz4", version: str = "1.10.0") -> subprocess.CompletedProcess:
        env = self.environment()
        return subprocess.run(self.argv(name, version), env=env, capture_output=True, text=True, check=False)

    def wait_for_call(self, argv: list[str]) -> None:
        deadline = time.monotonic() + 10
        while argv not in self.fake.argvs():
            if time.monotonic() > deadline:
                self.fail(f"{argv} was never called")
            time.sleep(0.05)

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
        self.assertEqual(result.returncode, 1)
        argvs = self.fake.argvs()
        self.assertEqual(argvs[-2:], [UNINSTALL, RESTORE_CORE])
        self.assertNotIn(["brew", "test", f"{TAP}/lz4"], argvs)

    def test_upload_failure_restores_tap_keg(self):
        self.installed(TAP)
        self.fake.fail("gh", "release", "upload")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.fake.argvs()[-2:], [UNINSTALL, RESTORE_TAP])

    def test_failed_tap_restore_falls_back_to_core(self):
        self.installed(TAP)
        self.fake.fail(*BUILD)
        self.fake.fail(*RESTORE_TAP)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.fake.argvs()[-3:], [UNINSTALL, RESTORE_TAP, RESTORE_CORE])
        self.assertIn("falling back", result.stderr)

    def test_not_installed_removes_half_built_keg_without_restore(self):
        self.fake.respond(*INFO, stdout="Error: No such keg: /usr/local/Cellar/lz4\n", exit_code=1)
        self.fake.fail("brew", "test")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.fake.argvs(), [INFO, BUILD, ["brew", "test", f"{TAP}/lz4"], UNINSTALL])

    def test_signals_cannot_interrupt_the_restore(self):
        self.installed("homebrew/core")
        self.fake.respond(*BUILD, sleep=1)
        self.fake.respond(*RESTORE_CORE, sleep=1)
        # Like a cancelled Actions job: SIGINT, then SIGTERM, to the whole group.
        env = self.environment()
        process = subprocess.Popen(self.argv(), env=env, stderr=subprocess.DEVNULL, start_new_session=True)
        self.wait_for_call(BUILD)
        os.killpg(process.pid, signal.SIGINT)
        self.wait_for_call(RESTORE_CORE)
        os.killpg(process.pid, signal.SIGTERM)
        self.assertNotEqual(process.wait(timeout=20), 0)
        self.assertEqual(self.fake.argvs()[-2:], [UNINSTALL, RESTORE_CORE])
        self.assertEqual(self.fake.finished()[-1], RESTORE_CORE)

    def test_versioned_name_asset_is_url_decoded(self):
        result = self.run_script("python@3.12", "3.12.7")
        self.assertEqual(result.returncode, 0, result.stderr)
        upload = next(argv for argv in self.fake.argvs() if argv[:3] == ["gh", "release", "upload"])
        self.assertEqual(upload[4], str(self.out / "python@3.12-3.12.7.sequoia.bottle.tar.gz"))
        self.assertTrue((self.out / "python@3.12-3.12.7.sequoia.bottle.tar.gz").is_file())

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
        result = subprocess.run(argv, env=self.environment(), capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.fake.argvs(), [])

    def test_pending_restore_marker_lives_while_the_keg_is_missing(self):
        self.installed(TAP)
        self.fake.respond(*BUILD, sleep=1)
        process = subprocess.Popen(self.argv(), env=self.environment(), stderr=subprocess.DEVNULL)
        self.wait_for_call(BUILD)
        self.assertEqual(self.marker.read_text(encoding="utf-8"), f"{TAP}/lz4\n")
        self.assertEqual(process.wait(timeout=20), 0)
        self.assertFalse(self.marker.exists())

    def test_pending_restore_marker_removed_after_restore(self):
        self.installed("homebrew/core")
        self.fake.fail(*BUILD)
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(self.fake.argvs()[-1], RESTORE_CORE)
        self.assertFalse(self.marker.exists())

    def test_pending_restore_marker_kept_when_restore_fails(self):
        self.installed(TAP)
        self.fake.fail(*BUILD)
        self.fake.fail(*RESTORE_TAP)
        self.fake.fail(*RESTORE_CORE)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.marker.read_text(encoding="utf-8"), f"{TAP}/lz4\n")
        self.assertIn("reinstall it by hand", result.stderr)

    def test_no_marker_when_nothing_was_installed(self):
        self.fake.respond(*INFO, stdout=json.dumps({"formulae": [], "casks": []}))
        self.fake.fail(*BUILD)
        self.assertEqual(self.run_script().returncode, 1)
        self.assertFalse(self.marker.exists())

    def test_refuses_while_another_restore_is_pending(self):
        self.installed("homebrew/core")
        self.marker.write_text("zstd\n", encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("zstd is still uninstalled", result.stderr)
        self.assertEqual(self.marker.read_text(encoding="utf-8"), "zstd\n")
        self.assertNotIn(UNINSTALL, self.fake.argvs())
