import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import manifest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "manifest.py"
CORE = "c" * 40
TAP_SHA = "d" * 40


class ManifestTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.out, self.tap, self.bottles = root / "out", root / "tap", root / "bottle-dir"
        self.write(self.tap / "Formula/l/lz4.rb", "class Lz4 < Formula\nend\n")
        self.write(self.tap / "Formula/lib/libpng.rb", "class Libpng < Formula\nend\n")
        self.cli("init", str(self.out), "--core-commit", CORE, "--tap-sha", TAP_SHA, "--branch-date", "2026-10-22")

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def cli(self, *args: str) -> str:
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def document(self) -> dict:
        return json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))

    def bottle(self, name: str = "lz4", version: str = "1.10.0") -> None:
        self.write(self.bottles / f"{name}--{version}.sequoia.bottle.json", "{}")
        self.write(self.bottles / f"{name}-{version}.sequoia.bottle.tar.gz", "tar")

    def test_init_writes_empty_sections(self):
        expected = {"core_commit": CORE, "tap_sha": TAP_SHA, "branch_date": "2026-10-22"}
        expected |= {"built": [], "failed": [], "skipped": [], "render_only": []}
        self.assertEqual(self.document(), expected)

    def test_built_moves_the_bottle_and_copies_the_formula(self):
        self.bottle()
        self.cli("built", str(self.out), str(self.tap), "lz4", "1.10.0", str(self.bottles))
        entry = {"name": "lz4", "version": "1.10.0", "relpath": "Formula/l/lz4.rb"}
        entry |= {"tarball": "lz4-1.10.0.sequoia.bottle.tar.gz", "json": "lz4--1.10.0.sequoia.bottle.json"}
        self.assertEqual(self.document()["built"], [entry])
        self.assertEqual((self.out / "bottles" / entry["tarball"]).read_text(encoding="utf-8"), "tar")
        self.assertTrue((self.out / "bottles" / entry["json"]).is_file())
        self.assertEqual(list(self.bottles.iterdir()), [])
        self.assertEqual((self.out / "Formula/l/lz4.rb").read_text(encoding="utf-8"), "class Lz4 < Formula\nend\n")

    def test_built_needs_exactly_one_bottle(self):
        self.bottles.mkdir()
        with self.assertRaises(manifest.ManifestError):
            manifest.add_built(self.out, self.tap, "lz4", "1.10.0", self.bottles)
        self.bottle()
        self.bottle(version="1.9.0")
        with self.assertRaises(manifest.ManifestError):
            manifest.add_built(self.out, self.tap, "lz4", "1.10.0", self.bottles)
        self.assertEqual(self.document()["built"], [])

    def test_render_only_failed_and_skipped(self):
        self.cli("render-only", str(self.out), str(self.tap), "libpng")
        self.cli("failed", str(self.out), "z3", "4.13.0")
        self.cli("skipped", str(self.out), "llvm", "dependency z3 did not build")
        document = self.document()
        self.assertEqual(document["render_only"], [{"name": "libpng", "relpath": "Formula/lib/libpng.rb"}])
        self.assertEqual(document["failed"], [{"name": "z3", "version": "4.13.0", "log": "z3.log"}])
        self.assertEqual(document["skipped"], [{"name": "llvm", "reason": "dependency z3 did not build"}])
        self.assertTrue((self.out / "Formula/lib/libpng.rb").is_file())

    def test_rows_print_tab_separated_fields_in_order(self):
        self.bottle()
        self.cli("built", str(self.out), str(self.tap), "lz4", "1.10.0", str(self.bottles))
        self.cli("render-only", str(self.out), str(self.tap), "libpng")
        built = "lz4\t1.10.0\tFormula/l/lz4.rb\tlz4-1.10.0.sequoia.bottle.tar.gz\tlz4--1.10.0.sequoia.bottle.json\n"
        self.assertEqual(self.cli("rows", str(self.out), "built"), built)
        self.assertEqual(self.cli("rows", str(self.out), "render_only"), "libpng\tFormula/lib/libpng.rb\n")
        self.assertEqual(self.cli("rows", str(self.out), "failed"), "")
        self.assertEqual(self.cli("field", str(self.out), "branch_date"), "2026-10-22\n")

    def test_summary_lists_every_section(self):
        self.cli("render-only", str(self.out), str(self.tap), "libpng")
        self.cli("failed", str(self.out), "z3", "4.13.0")
        summary = self.cli("summary", str(self.out))
        self.assertTrue(summary.startswith(f"Intel (Sequoia) bottles built from homebrew-core {CORE}.\n"))
        self.assertIn("## Built\n\n- none\n", summary)
        self.assertIn("## Failed\n\n- z3 4.13.0: build failed\n", summary)
        self.assertIn("## Skipped\n\n- none\n", summary)
        self.assertIn("## Updated from core\n\n- libpng\n", summary)

    def test_errors_exit_non_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "built", str(self.out), str(self.tap), "lz4", "1.10.0", str(self.bottles)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("manifest:", result.stderr)


if __name__ == "__main__":
    unittest.main()
