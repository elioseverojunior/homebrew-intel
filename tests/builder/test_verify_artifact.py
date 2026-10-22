import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import verify_artifact
from patching import make_patch
from transform import apply_bottle, render_body

from tests.builder.artifact_fixture import ArtifactTestCase
from tests.tap.fixtures import TAP_BOTTLE, git

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "verify_artifact.py"


class VerifyArtifactTest(ArtifactTestCase):
    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {"HOMEBREW_CORE_REPO": str(self.core)})
        environment.start()
        self.addCleanup(environment.stop)

    def problems(self, versions: dict[str, str] | None = None) -> list[str]:
        self.save()
        derived = versions if versions is not None else {"z3": "1.10.0", "llvm": "1.10.0"}
        return verify_artifact.problems(self.out, self.tap, self.core, derived)

    def assert_refused(self, fragment: str) -> None:
        found = self.problems()
        self.assertTrue(any(fragment in problem for problem in found), found)

    def test_good_artifact_passes(self):
        self.assertEqual(self.problems(), [])

    def test_main_exits_zero_or_one(self):
        versions = self.out.parent / "versions.json"
        versions.write_text(json.dumps({"z3": "1.10.0", "llvm": "1.10.0"}), encoding="utf-8")
        argv = ["--artifact", str(self.out), "--tap", str(self.tap), "--versions", str(versions)]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(verify_artifact.main(argv), 0, stderr.getvalue())
            self.edit("Formula/z/z3.rb", "  def install\n", '  def install\n    system "curl", "evil"\n')
            self.assertEqual(verify_artifact.main(argv), 1)
        self.assertIn("verify-artifact: Formula/z/z3.rb", stderr.getvalue())

    def test_manifest_version_must_equal_the_derived_one(self):
        self.assert_refused_with({"z3": "1.9.0", "llvm": "1.10.0"}, "z3: manifest version 1.10.0 is not 1.9.0")
        self.assert_refused_with({"llvm": "1.10.0"}, "z3: no derived version")

    def test_versions_with_slash_or_space_are_refused(self):
        for version in ("1.0/../x", "1.0 x"):
            self.entry("built", "z3")["version"] = version
            self.assert_refused(f"invalid version '{version}'")

    def test_two_formulae_may_not_share_a_release_tag(self):
        self.entry("built", "z3")["version"] = "1-1"
        clash = dict(self.entry("built", "z3"), name="z3-1", version="1", relpath="Formula/z/z3-1.rb")
        self.manifest["built"].append(clash)
        found = self.problems({"z3": "1-1", "z3-1": "1", "llvm": "1.10.0"})
        self.assertIn("release tag z3-1-1 is claimed more than once", found)

    def test_formulae_only_mode_skips_bottle_contents_and_versions(self):
        (self.out / "bottles" / self.entry("built", "z3")["tarball"]).write_bytes(b"other")
        self.save()
        self.assertEqual(verify_artifact.problems(self.out, self.tap, self.core, None), [])
        self.edit("Formula/z/z3.rb", "  def install\n", '  def install\n    system "curl", "evil"\n')
        self.assertNotEqual(verify_artifact.problems(self.out, self.tap, self.core, None), [])

    def formulae_only(self) -> list[str]:
        self.save()
        return verify_artifact.problems(self.out, self.tap, self.core, None)

    def test_hidden_code_in_a_bottle_block_fails_before_any_evaluation(self):
        self.edit("Formula/z/z3.rb", "    sha256 cellar: :any,", '    system "curl", "evil"\n    sha256 cellar: :any,')
        self.assertIn("Formula/z/z3.rb: bottle block has a line brew does not write", " ".join(self.formulae_only()))

    def test_two_blocks_or_a_misplaced_block_fail_in_formulae_only_mode(self):
        relpath = self.out / "Formula/z/z3.rb"
        text = relpath.read_text(encoding="utf-8")
        start = text.index("  bottle do")
        block = text[start : text.index("  end\n", start) + 6]
        relpath.write_text(text.replace("  def install\n", block + "  def install\n"), encoding="utf-8")
        self.assertIn("Formula/z/z3.rb: expected one bottle block, found 2", " ".join(self.formulae_only()))
        relpath.write_text(text.replace(block, "").replace("  def install\n", block + "  def install\n"), "utf-8")
        self.assertIn("Formula/z/z3.rb: bottle block is not next to the bottle marker", " ".join(self.formulae_only()))

    def test_render_only_block_must_be_mains_in_formulae_only_mode(self):
        self.edit("Formula/l/lz4.rb", '"bbb"', '"ccc"')
        self.assertIn("render-only bottle block differs from main's", " ".join(self.formulae_only()))

    def test_write_renders_writes_the_trusted_render_only(self):
        renders = self.directory()
        self.save()
        self.assertEqual(verify_artifact.write_renders(self.out, self.tap, self.core, renders), [])
        names = {"lz4", "z3", "llvm"}
        self.assertEqual((renders / "Formula/l/llvm.rb").read_text(encoding="utf-8"), self.render("llvm", names))
        self.assertEqual((renders / "Formula/l/lz4.rb").read_text(encoding="utf-8"), self.render("lz4", names))
        self.edit("Formula/z/z3.rb", "    sha256 cellar: :any,", '    system "x"\n    sha256 cellar: :any,')
        again = self.directory()
        self.assertNotEqual(verify_artifact.write_renders(self.out, self.tap, self.core, again), [])
        self.assertEqual(list(again.iterdir()), [])

    def assert_refused_with(self, versions: dict[str, str], fragment: str) -> None:
        found = self.problems(versions)
        self.assertTrue(any(fragment in problem for problem in found), found)

    def test_hand_made_formula_code_is_refused(self):
        self.edit("Formula/l/llvm.rb", "  def install\n", '  def install\n    system "curl", "evil"\n')
        self.assert_refused("Formula/l/llvm.rb: differs from core@")

    def test_render_from_another_core_commit_is_refused(self):
        self.manifest["core_commit"] = "0" * 40
        self.assert_refused("not in")

    def test_invalid_name_and_relpath_are_refused(self):
        self.entry("built", "z3")["name"] = "../z3"
        self.assert_refused("invalid name '../z3'")
        self.entry("built", "../z3")["name"] = "z3"
        self.entry("render_only", "lz4")["relpath"] = "Formula/x/lz4.rb"
        self.assert_refused("relpath Formula/x/lz4.rb is not Formula/l/lz4.rb")

    def test_manifest_shape_is_checked(self):
        for broken in ({"extra": 1}, {"tap_sha": "f" * 40}, {"branch_date": "today"}, {"failed": [{"name": "x"}]}):
            with self.subTest(broken=broken):
                saved = dict(self.manifest)
                self.manifest |= broken
                self.assertNotEqual(self.problems(), [])
                self.manifest = saved
        self.entry("built", "z3")["tarball"] = "../evil.tar.gz"
        self.assertNotEqual(self.problems(), [])

    def test_duplicate_names_are_refused(self):
        self.manifest["render_only"].append({"name": "z3", "relpath": "Formula/z/z3.rb"})
        self.assert_refused("z3 is listed more than once")

    def test_bad_bottle_block_is_refused(self):
        self.edit("Formula/z/z3.rb", "    sha256 cellar: :any,", '    sha256 sonoma: "x"\n    sha256 cellar: :any,')
        self.assert_refused("Formula/z/z3.rb: bottle block has a line brew does not write")

    def test_tarball_must_match_the_block(self):
        (self.out / "bottles" / self.entry("built", "z3")["tarball"]).write_bytes(b"other")
        self.assert_refused("does not match the tarball")

    def test_built_formula_needs_one_bottle_block(self):
        relpath = "Formula/z/z3.rb"
        text = (self.out / relpath).read_text(encoding="utf-8")
        (self.out / relpath).write_text(text.replace("  bottle do", "  # gone").replace("    root_url", "  #"), "utf-8")
        self.assertNotEqual(self.problems(), [])
        block = text[text.index("  bottle do") : text.index("  end\n", text.index("  bottle do")) + 6]
        (self.out / relpath).write_text(text + block, encoding="utf-8")
        self.assert_refused("expected one bottle block, found 2")

    def test_symlinked_files_are_refused(self):
        tarball = self.out / "bottles" / self.entry("built", "z3")["tarball"]
        target = tarball.with_name("real")
        tarball.rename(target)
        tarball.symlink_to(target)
        self.assert_refused("is not a regular file")

    def test_render_only_may_keep_mains_block_only(self):
        self.edit("Formula/l/lz4.rb", '"bbb"', '"ccc"')
        self.assert_refused("Formula/l/lz4.rb: render-only bottle block differs from main's")

    def test_render_only_without_a_block_passes(self):
        names = {"lz4", "z3", "llvm"}
        self.write(self.out / "Formula/l/lz4.rb", self.render("lz4", names))
        self.assertEqual(self.problems(), [])

    def test_new_render_only_formula_may_not_bring_a_block(self):
        git(self.tap, "rm", "-q", "Formula/l/lz4.rb")
        git(self.tap, "commit", "-q", "-m", "drop lz4")
        self.manifest["tap_sha"] = git(self.tap, "rev-parse", "HEAD")
        self.assert_refused("render-only bottle block differs from main's")

    def test_unlisted_formula_file_is_refused(self):
        self.write(self.out / "Formula/x/xz.rb", "class Xz < Formula\nend\n")
        self.assert_refused("Formula/x/xz.rb is not listed in the manifest")

    def test_patched_formula_renders_from_its_base_with_the_patch(self):
        base, names = self.commit, {"lz4", "z3", "llvm"}
        self.write(self.core / "Formula/l/lz4.rb", 'class Lz4 < Formula\n  url "new"\nend\n')
        git(self.core, "commit", "-q", "-am", "bump")
        self.commit = self.manifest["core_commit"] = git(self.core, "rev-parse", "HEAD")
        self.manifest["built"] = []
        for name in ("z3", "llvm"):
            self.add_built(name, self.render(name, names))
        source = git(self.core, "show", f"{base}:Formula/l/lz4.rb") + "\n"
        original = render_body(source, name="lz4", commit=base, tap_names=names)
        edited = original.replace("  def install\n", "  def install\n    ENV.deparallelize\n")
        self.write(self.tap / "patches/lz4.patch", make_patch(original, edited, "Formula/l/lz4.rb"))
        self.write(self.tap / "enabled.toml", f'[formula.lz4]\nkind = "patched"\nbase = "{base}"\n')
        self.write(self.out / "Formula/l/lz4.rb", apply_bottle(edited, TAP_BOTTLE))
        self.assertEqual(self.problems(), [])
        self.save()
        self.assertEqual(verify_artifact.needed_commits(self.out, self.tap), [self.commit, base])

    def test_list_commits_prints_the_core_commit(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--artifact", str(self.out), "--tap", str(self.tap), "--list-commits"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout), (0, f"{self.commit}\n"), result.stderr)


if __name__ == "__main__":
    unittest.main()
