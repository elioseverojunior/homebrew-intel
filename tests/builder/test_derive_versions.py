import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "derive-versions.sh"
TAP = "homebrew-intel/tap"


def info(name: str, version: str, revision: int = 0) -> str:
    formula = {"name": name, "full_name": f"{TAP}/{name}", "versions": {"stable": version}, "revision": revision}
    return json.dumps({"formulae": [formula], "casks": []})


class DeriveVersionsTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        self.root = self.directory()
        self.out, self.tap, self.brew = self.root / "out", self.root / "tap", self.root / "brew"
        self.renders = self.root / "renders"
        self.write(self.tap / "Formula/l/lz4.rb", "lz4 main\n")
        for relpath in ("Formula/z/z3.rb", "Formula/l/llvm.rb", "Formula/x/xz.rb"):
            self.write(self.out / relpath, f"{relpath} from the host\n")
            self.write(self.renders / relpath, f"{relpath} trusted render\n")
        built = [{"name": name, "version": "9.9", "relpath": f"Formula/{name[0]}/{name}.rb"} for name in ("z3", "llvm")]
        manifest = {"built": [entry | {"tarball": "t", "json": "j"} for entry in built]}
        manifest |= {"render_only": [{"name": "xz", "relpath": "Formula/x/xz.rb"}], "failed": [], "skipped": []}
        manifest |= {"core_commit": "c" * 40, "tap_sha": "d" * 40, "branch_date": "2026-10-22"}
        self.write(self.out / "manifest.json", json.dumps(manifest))
        self.fake.respond("brew", "--repository", stdout=f"{self.brew}\n")
        self.fake.respond("brew", "info", "--json=v2", f"{TAP}/z3", stdout=info("z3", "4.13.0"))
        self.fake.respond("brew", "info", "--json=v2", f"{TAP}/llvm", stdout=info("llvm", "19.1.0", 2))
        self.fake.respond("brew", "info", "--json=v2", f"{TAP}/xz", stdout=info("xz", "5.6.3"))
        self.versions = self.root / "versions.json"

    def directory(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name).resolve()

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_script(self, **extra: str) -> subprocess.CompletedProcess:
        env = {**self.fake.environment(), "TAP_DIR": str(self.tap), **extra}
        for secret in ("GH_TOKEN", "GITHUB_TOKEN", "PRIVATE_GH_TOKEN", "HOMEBREW_GITHUB_API_TOKEN"):
            env.setdefault(secret, "")
        argv = ["bash", str(SCRIPT), str(self.renders), str(self.out), str(self.versions)]
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=False)

    def test_reads_each_built_and_render_only_version_from_brew(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        versions = json.loads(self.versions.read_text(encoding="utf-8"))
        self.assertEqual(versions, {"z3": "4.13.0", "llvm": "19.1.0_2", "xz": "5.6.3"})

    def test_trusts_only_the_artifact_formulae_in_a_scratch_tap(self):
        self.assertEqual(self.run_script().returncode, 0)
        trusted = [argv for argv in self.fake.argvs() if argv[:2] == ["brew", "trust"]]
        self.assertEqual(trusted, [["brew", "trust", "--formula", f"{TAP}/z3", f"{TAP}/llvm", f"{TAP}/xz"]])
        link = self.brew / "Library/Taps/homebrew-intel/homebrew-tap"
        self.assertTrue(link.is_symlink())
        scratch = link.resolve()
        self.assertNotEqual(scratch, self.tap)
        self.assertEqual((scratch / "Formula/l/lz4.rb").read_text(encoding="utf-8"), "lz4 main\n")
        for relpath in ("Formula/x/xz.rb", "Formula/z/z3.rb"):
            self.assertEqual((scratch / relpath).read_text(encoding="utf-8"), f"{relpath} trusted render\n")
        self.assertFalse((self.tap / "Formula/z/z3.rb").exists())

    def test_empty_run_writes_an_empty_map_without_loading_formulae(self):
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        manifest |= {"built": [], "render_only": [], "failed": [{"name": "lz4", "version": "1.10.0", "log": "lz4.log"}]}
        self.write(self.out / "manifest.json", json.dumps(manifest))
        empty = self.root / "empty-renders"
        empty.mkdir()
        self.renders = empty
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.versions.read_text(encoding="utf-8")), {})
        self.assertEqual([argv for argv in self.fake.argvs() if argv[1] in ("info", "trust")], [])

    def test_wrong_formula_or_brew_failure_fails(self):
        self.fake.rules.clear()
        self.fake.respond("brew", "--repository", stdout=f"{self.brew}\n")
        self.fake.respond("brew", "info", "--json=v2", f"{TAP}/z3", stdout=info("zstd", "1.5.6"))
        self.assertNotEqual(self.run_script().returncode, 0)
        self.fake.rules.clear()
        self.fake.respond("brew", "--repository", stdout=f"{self.brew}\n")
        self.fake.respond("brew", "info", exit_code=1)
        self.assertNotEqual(self.run_script().returncode, 0)

    def test_refuses_any_token(self):
        for secret in ("GH_TOKEN", "HOMEBREW_GITHUB_API_TOKEN"):
            result = self.run_script(**{secret: "t"})
            self.assertEqual(result.returncode, 2, secret)
        self.assertEqual(self.fake.argvs(), [])

    def test_refuses_an_existing_tap_directory(self):
        (self.brew / "Library/Taps/homebrew-intel/homebrew-tap").mkdir(parents=True)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)


if __name__ == "__main__":
    unittest.main()
