"""Dependency expansion and build order over homebrew-core API formula dicts."""

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet

BOTTLED_INTEL_TAGS = frozenset({"all", "sequoia", "sonoma", "ventura", "monterey", "big_sur"})
# The API's top-level dependency lists describe ARM macOS. What differs on the
# Intel system the bottles are built on sits in formula["variations"][tag],
# where each key present replaces the top-level one outright, as brew's
# Homebrew::API.merge_variations does with a shallow Hash#merge.
INTEL_VARIATION = "sequoia"
# What building, testing and bottling a formula on the Intel host installs:
# brew pours its runtime dependencies and builds none of its build or test
# dependencies itself (`brew test` refuses to run without the test ones).
BUILD_KEYS = ("dependencies", "build_dependencies", "test_dependencies")


def needs_intel_bottle(formula: Mapping) -> bool:
    files = ((formula.get("bottle") or {}).get("stable") or {}).get("files", {})
    return BOTTLED_INTEL_TAGS.isdisjoint(files)


def dependencies(name: str, formulae: Mapping[str, Mapping], *keys: str) -> list[str]:
    formula = formulae.get(name, {})
    intel = (formula.get("variations") or {}).get(INTEL_VARIATION) or {}
    return [dependency for key in keys for dependency in intel.get(key, formula.get(key)) or []]


def expand(enabled: Iterable[str], formulae: Mapping[str, Mapping]) -> set[str]:
    """The enabled names plus every dependency they need that has no Intel bottle.

    Runtime dependencies are followed through bottled formulae too, since a
    poured keg still needs its own. Build and test dependencies are followed
    only for formulae in the result: the tap builds and tests those, while a
    bottled formula is poured, never built.
    """
    result = set(enabled)
    visited: set[str] = set()
    pending = sorted(result)
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        keys = BUILD_KEYS if name in result else ("dependencies",)
        for dependency in dependencies(name, formulae, *keys):
            known = dependency in formulae
            if known and needs_intel_bottle(formulae[dependency]):
                result.add(dependency)
            if known:
                pending.append(dependency)
    return result


def build_order(names: AbstractSet[str], formulae: Mapping[str, Mapping]) -> list[str]:
    prerequisites = {name: {d for d in dependencies(name, formulae, *BUILD_KEYS) if d in names} for name in names}
    order: list[str] = []
    remaining = dict(prerequisites)
    while remaining:
        ready = sorted(name for name, needed in remaining.items() if not needed)
        if not ready:
            msg = f"dependency cycle among: {', '.join(sorted(remaining))}"
            raise ValueError(msg)
        order.append(ready[0])
        del remaining[ready[0]]
        for needed in remaining.values():
            needed.discard(ready[0])
    return order
