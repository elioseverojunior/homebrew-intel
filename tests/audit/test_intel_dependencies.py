import unittest
from unittest import mock

import brewfile_classify
import formulae
from brew_api import INTEL_TAG


def core(name, deps=(), build_deps=(), intel=None):
    """A formula.json entry; `intel` is its Intel Sequoia variation, as the API writes on_intel."""
    item = {
        "name": name,
        "dependencies": list(deps),
        "build_dependencies": list(build_deps),
        "requirements": [],
        "bottle": {},
    }
    if intel is not None:
        item["variations"] = {INTEL_TAG: intel}
    return item


def index(*items):
    return {item["name"]: item for item in items}


ARM = {**core("arm"), "requirements": [{"name": "arch", "version": "arm64"}]}
API = index(
    ARM,
    core("intel-only", intel={"dependencies": ["arm"]}),
    core("arm-side", deps=["arm"], intel={"dependencies": []}),
    core("plain", deps=["arm"]),
)


class DependentsOfTest(unittest.TestCase):
    def test_follows_the_intel_variation(self):
        self.assertEqual(formulae.dependents_of({"arm"}, API), {"intel-only", "plain"})


class BuildRowsTest(unittest.TestCase):
    def test_rows_list_intel_dependencies(self):
        tag = {"formulae": {name: {} for name in API}}
        with (
            mock.patch.object(formulae, "load_json", return_value=list(API.values())),
            mock.patch.object(formulae, "load_tag_payload", return_value=tag),
            mock.patch.object(formulae, "load_analytics", return_value={}),
        ):
            rows = {row["name"]: row for row in formulae.build_rows()}
        self.assertEqual(rows["intel-only"]["dependencies"], ["arm"])
        self.assertEqual(rows["arm-side"]["dependencies"], [])
        self.assertEqual(rows["arm-side"]["class"], "NO_BOTTLE_ANY_PLATFORM")


class BrewfileIntelDependenciesTest(unittest.TestCase):
    def test_fallback_follows_the_intel_variation(self):
        api = {
            "formulas": index(core("a", deps=["x"], build_deps=["y"], intel={"build_dependencies": ["z"]})),
            "tags": {INTEL_TAG: {"formulae": {}}},
        }
        self.assertEqual(brewfile_classify.intel_dependencies("a", api), (["x"], ["z"]))


if __name__ == "__main__":
    unittest.main()
