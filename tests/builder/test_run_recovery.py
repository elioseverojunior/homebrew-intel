import unittest

from tests.builder.run_harness import RunTest, git

TAP_LZ4 = "elioseverojunior/intel/lz4"


class PendingRestoreTest(RunTest):
    def setUp(self):
        super().setUp()
        self.marker = self.root / "cache" / "pending-restore"
        self.marker.parent.mkdir(parents=True)
        self.marker.write_text(f"{TAP_LZ4}\n", encoding="utf-8")

    def brew_installs(self) -> list[list[str]]:
        return [argv for argv in self.fake.argvs() if argv[:2] == ["brew", "install"]]

    def test_reinstalls_pending_keg_before_the_run(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.brew_installs(), [["brew", "install", TAP_LZ4]])
        self.assertIn("interrupted build", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(len(self.stub_calls("fetch-api.sh")), 1)

    def test_failed_tap_reinstall_falls_back_to_core(self):
        self.fake.fail("brew", "install", TAP_LZ4)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.brew_installs(), [["brew", "install", TAP_LZ4], ["brew", "install", "lz4"]])
        self.assertFalse(self.marker.exists())

    def test_failed_reinstall_aborts_without_touching_the_link(self):
        self.fake.fail("brew", "install")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("reinstall it by hand", result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.stub_calls(), [])
        self.assert_link_restored()
        self.assertFalse(self.saved_target.exists())

    def test_invalid_marker_aborts_without_installing(self):
        self.marker.write_text("../../evil\n", encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.brew_installs(), [])
        self.assertEqual(self.stub_calls(), [])

    def test_dry_run_leaves_the_marker_alone(self):
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fake.argvs(), [])
        self.assertTrue(self.marker.exists())


class OriginHeadTest(RunTest):
    def test_origin_head_points_at_main_after_the_run(self):
        self.configure(plan="lz4 1.10.0\n")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        head = git("-C", str(self.tap), "symbolic-ref", "refs/remotes/origin/HEAD")
        self.assertEqual(head, "refs/remotes/origin/main")

    def test_existing_origin_head_is_kept(self):
        git("-C", str(self.tap), "update-ref", "refs/remotes/origin/other", "HEAD")
        git("-C", str(self.tap), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/other")
        self.assertEqual(self.run_script().returncode, 0)
        head = git("-C", str(self.tap), "symbolic-ref", "refs/remotes/origin/HEAD")
        self.assertEqual(head, "refs/remotes/origin/other")


class DryRunLinkTest(RunTest):
    def test_dry_run_reports_that_a_real_run_would_refuse(self):
        self.link.unlink()
        self.link.symlink_to(self.tap)
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("a real run would refuse", result.stdout)
        self.assertEqual(self.link.readlink(), self.tap)

    def test_dry_run_with_saved_target_does_not_warn(self):
        self.saved_target.parent.mkdir(parents=True)
        self.saved_target.write_text(f"{self.original}\n", encoding="utf-8")
        self.link.unlink()
        self.link.symlink_to(self.tap)
        result = self.run_script("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("would refuse", result.stdout)


if __name__ == "__main__":
    unittest.main()
