"""verify_artifact against the hosted pins: the enabled closure and main's bottle tags."""

import os
import unittest
from unittest import mock

import verify_artifact

from tests.builder.artifact_fixture import ArtifactTestCase

DERIVED = {"z3": "1.10.0", "llvm": "1.10.0", "lz4": "1.10.0"}


class VerifyPinsTest(ArtifactTestCase):
    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {"HOMEBREW_CORE_REPO": str(self.core)})
        environment.start()
        self.addCleanup(environment.stop)

    def problems(self, versions: dict[str, str] | None = DERIVED) -> list[str]:
        self.save()
        return verify_artifact.problems(self.out, self.tap, self.core, self.pins(), versions)

    def assert_refused(self, fragment: str, versions: dict[str, str] | None = DERIVED) -> None:
        found = self.problems(versions)
        self.assertTrue(any(fragment in problem for problem in found), found)

    def test_formula_outside_the_enabled_closure_is_refused(self):
        self.closure = {"lz4", "llvm"}
        for versions in (None, DERIVED):
            with self.subTest(versions=versions):
                self.assert_refused("z3 is not in the enabled closure", versions)

    def test_tap_names_are_the_closure_never_the_artifacts(self):
        # The host bottles z3 to turn llvm's core dependency into a tap one.
        self.closure = {"lz4", "llvm"}
        self.manifest["built"] = [entry for entry in self.manifest["built"] if entry["name"] != "z3"]
        (self.out / "Formula/z/z3.rb").unlink()
        self.assert_refused("Formula/l/llvm.rb: differs from core@")
        self.write(self.out / "Formula/l/lz4.rb", self.render("lz4", self.closure))
        found = self.problems(None)
        self.assertTrue(any("llvm.rb: differs from core@" in problem for problem in found), found)

    def test_render_only_block_must_carry_the_derived_release_tag(self):
        self.assertEqual(self.problems(), [])
        self.assert_refused(
            "Formula/l/lz4.rb: render-only bottle block is for lz4-1.10.0, not lz4-1.11.0", DERIVED | {"lz4": "1.11.0"}
        )
        self.assert_refused(
            "Formula/l/lz4.rb: render-only bottle block needs a derived version", {"z3": "1.10.0", "llvm": "1.10.0"}
        )

    def test_render_only_without_a_block_needs_no_derived_version(self):
        self.write(self.out / "Formula/l/lz4.rb", self.render("lz4", self.closure))
        self.assertEqual(self.problems({"z3": "1.10.0", "llvm": "1.10.0"}), [])

    def test_formulae_only_mode_keeps_mains_block_without_versions(self):
        self.assertEqual(self.problems(None), [])

    def test_two_formulae_may_not_share_an_asset_name(self):
        self.entry("built", "llvm")["tarball"] = self.entry("built", "z3")["tarball"]
        self.assert_refused("asset z3-1.10.0.sequoia.bottle.tar.gz is claimed more than once", None)

    def test_closure_file_must_hold_formula_names(self):
        path = self.out.parent / "closure.txt"
        for text in ("", "lz4\n../z3\n"):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_artifact.load_closure(path)
        path.write_text("lz4\nz3 llvm\n", encoding="utf-8")
        self.assertEqual(verify_artifact.load_closure(path), frozenset({"lz4", "z3", "llvm"}))


if __name__ == "__main__":
    unittest.main()
