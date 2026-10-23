import unittest

from closure import BOTTLED_INTEL_TAGS, INTEL_VARIATION, build_order, dependencies, expand, needs_intel_bottle


def formula(name, deps=(), build_deps=(), tags=(), test_deps=()):
    return {
        "name": name,
        "dependencies": list(deps),
        "build_dependencies": list(build_deps),
        "test_dependencies": list(test_deps),
        "bottle": {"stable": {"files": {tag: {} for tag in tags}}} if tags else {},
    }


def on_intel(item, **keys):
    """Give a formula dict an Intel variation, as the API writes on_intel/on_arm."""
    return {**item, "variations": {INTEL_VARIATION: keys}}


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


class DependenciesTest(unittest.TestCase):
    def test_intel_variation_replaces_each_key_it_names(self):
        # Modelled on gnu-apl (arm-only llvm@21) and gdb (Intel-only expat).
        formulae = index(
            on_intel(
                formula("a", deps=["gmp"], build_deps=["pkgconf", "llvm@21"], test_deps=["t"]),
                dependencies=["gmp", "expat"],
                build_dependencies=["pkgconf"],
            )
        )
        self.assertEqual(dependencies("a", formulae, "dependencies"), ["gmp", "expat"])
        self.assertEqual(dependencies("a", formulae, "build_dependencies"), ["pkgconf"])
        self.assertEqual(dependencies("a", formulae, "test_dependencies"), ["t"])

    def test_other_variations_are_ignored(self):
        formulae = index(formula("a", deps=["b"]))
        formulae["a"]["variations"] = {"arm64_sequoia": {"dependencies": ["c"]}, "x86_64_linux": {"dependencies": []}}
        self.assertEqual(dependencies("a", formulae, "dependencies"), ["b"])

    def test_unknown_formula_has_no_dependencies(self):
        self.assertEqual(dependencies("a", {}, "dependencies"), [])


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

    def test_expand_adds_unbottled_build_deps(self):
        formulae = index(formula("lz4", build_deps=["cmake"]), formula("cmake"))
        self.assertEqual(expand(["lz4"], formulae), {"lz4", "cmake"})

    def test_expand_skips_bottled_build_deps_but_walks_their_runtime_deps(self):
        formulae = index(
            formula("a", build_deps=["b"]),
            formula("b", deps=["c"], build_deps=["d"], tags={"sonoma"}),
            formula("c"),
            formula("d"),
        )
        self.assertEqual(expand(["a"], formulae), {"a", "c"})

    def test_expand_follows_build_deps_of_added_formulae(self):
        formulae = index(
            formula("a", deps=["b"]),
            formula("b", build_deps=["c"]),
            formula("c", build_deps=["d"]),
            formula("d"),
        )
        self.assertEqual(expand(["a"], formulae), {"a", "b", "c", "d"})

    def test_expand_adds_unbottled_test_deps_of_the_closure_only(self):
        formulae = index(
            formula("a", deps=["b"], test_deps=["t"]),
            formula("b", test_deps=["u"], tags={"sonoma"}),
            formula("t"),
            formula("u"),
        )
        self.assertEqual(expand(["a"], formulae), {"a", "t"})

    def test_expand_uses_intel_dependencies(self):
        # Modelled on gnu-apl (arm-only llvm@21 build dep), ddd (Intel-only
        # gdb test dep) and ollama (arm-only mlx-c runtime dep).
        formulae = index(
            on_intel(formula("gnu-apl", build_deps=["llvm@21"]), build_dependencies=[]),
            on_intel(formula("ddd"), test_dependencies=["gdb"]),
            on_intel(formula("ollama", deps=["mlx-c"]), dependencies=[]),
            formula("llvm@21"),
            formula("gdb"),
            formula("mlx-c"),
        )
        self.assertEqual(expand(["gnu-apl", "ddd", "ollama"], formulae), {"gnu-apl", "ddd", "ollama", "gdb"})

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

    def test_build_order_puts_test_deps_first(self):
        formulae = index(formula("a", test_deps=["b"]), formula("b"))
        self.assertEqual(build_order({"a", "b"}, formulae), ["b", "a"])

    def test_build_order_uses_intel_dependencies(self):
        formulae = index(
            on_intel(formula("a", build_deps=["b"]), build_dependencies=[], test_dependencies=["c"]),
            formula("b"),
            formula("c", test_deps=["b"]),
        )
        self.assertEqual(build_order({"a", "b", "c"}, formulae), ["b", "c", "a"])

    def test_build_order_tolerates_unknown_names(self):
        self.assertEqual(build_order({"go@1.21", "a"}, index(formula("a"))), ["a", "go@1.21"])

    def test_build_order_cycle_raises(self):
        formulae = index(formula("a", deps=["b"]), formula("b", deps=["a"]), formula("c"))
        with self.assertRaisesRegex(ValueError, "a, b"):
            build_order({"a", "b", "c"}, formulae)


if __name__ == "__main__":
    unittest.main()
