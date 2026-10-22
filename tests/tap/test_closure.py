import unittest

from closure import BOTTLED_INTEL_TAGS, build_order, expand, needs_intel_bottle


def formula(name, deps=(), build_deps=(), tags=()):
    return {
        "name": name,
        "dependencies": list(deps),
        "build_dependencies": list(build_deps),
        "bottle": {"stable": {"files": {tag: {} for tag in tags}}} if tags else {},
    }


def index(*formulae):
    return {item["name"]: item for item in formulae}


class NeedsIntelBottleTest(unittest.TestCase):
    def test_bottled_tags(self):
        self.assertIn("sonoma", BOTTLED_INTEL_TAGS)
        self.assertFalse(needs_intel_bottle(formula("a", tags={"sonoma"})))
        self.assertFalse(needs_intel_bottle(formula("a", tags={"all"})))
        self.assertTrue(needs_intel_bottle(formula("a", tags={"tahoe", "arm64_sequoia"})))
        self.assertTrue(needs_intel_bottle(formula("a")))

    def test_missing_bottle_key(self):
        self.assertTrue(needs_intel_bottle({"name": "a"}))


class ExpandTest(unittest.TestCase):
    def test_expand_adds_unbottled_runtime_deps(self):
        formulae = index(
            formula("llvm", deps=["z3", "zstd"], tags={"arm64_sequoia"}),
            formula("z3", tags={"arm64_sequoia"}),
            formula("zstd", tags={"sequoia"}),
        )
        self.assertEqual(expand(["llvm"], formulae), {"llvm", "z3"})

    def test_expand_walks_through_bottled_deps(self):
        formulae = index(
            formula("a", deps=["b"]),
            formula("b", deps=["c"], tags={"sonoma"}),
            formula("c"),
        )
        self.assertEqual(expand(["a"], formulae), {"a", "c"})

    def test_expand_ignores_build_deps(self):
        formulae = index(formula("a", build_deps=["cmake"]), formula("cmake"))
        self.assertEqual(expand(["a"], formulae), {"a"})

    def test_expand_keeps_unknown_names(self):
        formulae = index(formula("a", deps=["go@1.21"]))
        self.assertEqual(expand(["a", "go@1.21"], formulae), {"a", "go@1.21"})
        self.assertEqual(expand(["a"], formulae), {"a"})

    def test_expand_handles_cycles(self):
        formulae = index(formula("a", deps=["b"]), formula("b", deps=["a"]))
        self.assertEqual(expand(["a"], formulae), {"a", "b"})


class BuildOrderTest(unittest.TestCase):
    def test_build_order_deps_first_and_stable(self):
        formulae = index(formula("llvm", deps=["z3"]), formula("z3"), formula("lz4"))
        self.assertEqual(build_order({"llvm", "z3", "lz4"}, formulae), ["lz4", "z3", "llvm"])

    def test_build_order_uses_build_deps_inside_set(self):
        formulae = index(formula("a", build_deps=["b", "outside"]), formula("b"))
        self.assertEqual(build_order({"a", "b"}, formulae), ["b", "a"])

    def test_build_order_tolerates_unknown_names(self):
        self.assertEqual(build_order({"go@1.21", "a"}, index(formula("a"))), ["a", "go@1.21"])

    def test_build_order_cycle_raises(self):
        formulae = index(formula("a", deps=["b"]), formula("b", deps=["a"]), formula("c"))
        with self.assertRaisesRegex(ValueError, "a, b"):
            build_order({"a", "b", "c"}, formulae)


if __name__ == "__main__":
    unittest.main()
