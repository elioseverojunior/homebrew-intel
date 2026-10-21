"""Find homebrew-cask casks that are unavailable, deprecated or pinned on Intel macOS."""

import argparse
import collections

from brew_api import (
    ARM_TAG,
    CURRENT_INTEL_TAGS,
    INTEL_MACOS_TAGS,
    INTEL_TAG,
    load_analytics,
    load_json,
    load_tag_payload,
    write_report,
)

UNAVAILABLE_PREFIXES = ("depends_on arch", "no Intel", "disabled on Intel", "Intel requires")


def platform_reasons(cask):
    """Reasons from the cask's declared architecture and platform list."""
    arch = (cask.get("depends_on") or {}).get("arch") or []
    platforms = set(cask.get("supported_platforms") or [])
    intel_platforms = platforms & set(INTEL_MACOS_TAGS)
    if any(entry.get("type") == "arm" for entry in arch):
        return ["depends_on arch: :arm64"]
    if platforms and not intel_platforms:
        return ["no Intel macOS in supported_platforms"]
    if intel_platforms and not intel_platforms & CURRENT_INTEL_TAGS:
        return ["Intel only up to " + ", ".join(sorted(intel_platforms))]
    return []


def variation_reasons(intel, arm):
    """Reasons from differences between the Intel and ARM evaluations."""
    reasons = []
    if intel.get("disable_args") and intel.get("disable_args") != arm.get("disable_args"):
        reasons.append(f"disabled on Intel: {intel['disable_args']}")
    if intel.get("deprecate_args") and intel.get("deprecate_args") != arm.get("deprecate_args"):
        reasons.append(f"deprecated on Intel: {intel['deprecate_args']}")
    if intel.get("version") != arm.get("version"):
        reasons.append(f"Intel pinned to {intel.get('version')} (ARM {arm.get('version')})")
    minimum_macos = (intel.get("depends_on_args") or {}).get(":macos")
    if minimum_macos and "golden_gate" in str(minimum_macos):
        reasons.append(f"Intel requires macOS {minimum_macos}")
    return reasons


def classify(reasons):
    """Collapse a cask's reasons into one class, most severe first."""
    if any(reason.startswith(UNAVAILABLE_PREFIXES) for reason in reasons):
        return "UNAVAILABLE_ON_INTEL"
    if any(reason.startswith("deprecated on Intel") for reason in reasons):
        return "INTEL_DEPRECATED"
    if any(reason.startswith("Intel pinned") for reason in reasons):
        return "INTEL_VERSION_PINNED"
    return "INTEL_OLD_MACOS_ONLY"


def build_rows():
    """Report rows for casks with at least one Intel problem."""
    intel = load_tag_payload(INTEL_TAG)["casks"]
    arm = load_tag_payload(ARM_TAG)["casks"]
    installs = load_analytics("analytics-cask.json", "cask")
    rows = []
    for cask in load_json("cask.json"):
        token = cask["token"]
        reasons = platform_reasons(cask) + variation_reasons(intel[token], arm[token])
        if reasons:
            rows.append(
                {
                    "token": token,
                    "class": classify(reasons),
                    "reasons": reasons,
                    "installs_90d": installs.get(token, 0),
                    "desc": cask.get("desc"),
                }
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print per-class counts")
    args = parser.parse_args()
    rows = build_rows()
    path = write_report("casks", rows)
    if args.verbose:
        print(collections.Counter(row["class"] for row in rows))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
