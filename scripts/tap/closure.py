"""Dependency expansion and build order over homebrew-core API formula dicts."""

from collections.abc import Iterable, Mapping
from collections.abc import Set as AbstractSet

BOTTLED_INTEL_TAGS = frozenset({"all", "sequoia", "sonoma", "ventura", "monterey", "big_sur"})


def needs_intel_bottle(formula: Mapping) -> bool:
    files = ((formula.get("bottle") or {}).get("stable") or {}).get("files", {})
    return BOTTLED_INTEL_TAGS.isdisjoint(files)


def _dependencies(name: str, formulae: Mapping[str, Mapping], *keys: str) -> list[str]:
    formula = formulae.get(name, {})
    return [dependency for key in keys for dependency in formula.get(key) or []]


def expand(enabled: Iterable[str], formulae: Mapping[str, Mapping]) -> set[str]:
    result = set(enabled)
    visited: set[str] = set()
    pending = sorted(result)
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        for dependency in _dependencies(name, formulae, "dependencies"):
            known = dependency in formulae
            if known and needs_intel_bottle(formulae[dependency]):
                result.add(dependency)
            if known:
                pending.append(dependency)
    return result


def build_order(names: AbstractSet[str], formulae: Mapping[str, Mapping]) -> list[str]:
    prerequisites = {
        name: {d for d in _dependencies(name, formulae, "dependencies", "build_dependencies") if d in names}
        for name in names
    }
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
