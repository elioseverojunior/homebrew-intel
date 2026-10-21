"""Classify every homebrew-core formula by how usable it is on Intel macOS."""

import argparse
import collections

from brew_api import (
    ARM_TAG,
    CURRENT_INTEL_TAGS,
    INTEL_MACOS_TAGS,
    INTEL_TAG,
    bottle_files,
    load_analytics,
    load_json,
    load_tag_payload,
    write_report,
)


def arm_only_names(formulae):
    """Formulae declaring `depends_on arch: :arm64`."""
    return {
        name
        for name, formula in formulae.items()
        if any(req["name"] == "arch" and req["version"] == "arm64" for req in formula["requirements"])
    }


def dependents_of(roots, formulae):
    """Every formula whose runtime dependency closure reaches one of `roots`."""
    reverse = collections.defaultdict(set)
    for name, formula in formulae.items():
        for dependency in formula["dependencies"]:
            reverse[dependency].add(name)
    blocked, pending = set(), list(roots)
    while pending:
        for dependent in reverse[pending.pop()]:
            if dependent not in roots and dependent not in blocked:
                blocked.add(dependent)
                pending.append(dependent)
    return blocked


def classify(formula, intel_tags, arm_only, blocked):
    """Return the Intel availability class for one formula."""
    files = bottle_files(formula)
    rules = [
        ("ARM_ONLY", formula["name"] in arm_only),
        ("BLOCKED_BY_ARM_DEPENDENCY", formula["name"] in blocked),
        ("DISABLED", bool(formula.get("disabled"))),
        # A bottle pours on its own macOS or newer, so Tahoe-only does not serve Sequoia.
        ("OK", "all" in files or INTEL_TAG in intel_tags),
        ("TAHOE_ONLY_BOTTLE", intel_tags == ["tahoe"]),
        ("OLD_INTEL_BOTTLE", bool(set(intel_tags) - CURRENT_INTEL_TAGS)),
        ("NO_INTEL_BOTTLE", any(tag.startswith("arm64_") for tag in files)),
    ]
    return next((name for name, matches in rules if matches), "NO_BOTTLE_ANY_PLATFORM")


def build_rows():
    """One report row per core formula."""
    formulae = {formula["name"]: formula for formula in load_json("formula.json")}
    intel = load_tag_payload(INTEL_TAG)["formulae"]
    arm = load_tag_payload(ARM_TAG)["formulae"]
    installs = load_analytics("analytics-formula.json", "formula")
    arm_only = arm_only_names(formulae)
    blocked = dependents_of(arm_only, formulae)
    rows = []
    for name, formula in formulae.items():
        intel_tags = [tag for tag in INTEL_MACOS_TAGS if tag in bottle_files(formula)]
        rows.append(
            {
                "name": name,
                "class": classify(formula, intel_tags, arm_only, blocked),
                "newest_intel_bottle": intel_tags[0] if intel_tags else None,
                "intel_version": intel[name].get("stable_version"),
                "arm_version": arm[name].get("stable_version"),
                "installs_90d": installs.get(name, 0),
                "deprecated": formula.get("deprecated"),
                "desc": formula.get("desc"),
                "dependencies": formula["dependencies"],
                "build_dependencies": formula["build_dependencies"],
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print per-class counts")
    args = parser.parse_args()
    rows = build_rows()
    path = write_report("formulae", rows)
    if args.verbose:
        print(collections.Counter(row["class"] for row in rows))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
