#!/usr/bin/env python3
"""Audit a Brewfile for what must be built from source on Intel macOS Sequoia.

Read-only: it reads the Homebrew API dumps in $HOMEBREW_INTEL_DATA (default
<repo>/.cache/api) and queries `brew info/list/outdated`; it never installs.
Writes <repo>/reports/brewfile.json and <repo>/reports/brewfile.md.
"""

import argparse
import json
import logging
import re
import subprocess
from pathlib import Path

from brew_api import DATA_DIR, REPORTS_DIR
from brewfile_classify import build_formula_records, classify_cask, load_api, resolve_formula_name
from brewfile_cost import BuildRequirements, annotate_build_cost, annotate_fan_in, annotate_source_sizes
from markdown import bullet, paragraph

LOG = logging.getLogger("brewfile-audit")
TAP_NAME_SLASHES = 2


def is_tap_name(name):
    """True for fully qualified `user/tap/name` entries."""
    return name.count("/") == TAP_NAME_SLASHES


def run_brew_json(*args):
    LOG.info("brew %s", " ".join(args[:4]))
    result = subprocess.run(["brew", *args], capture_output=True, text=True, check=False)
    return json.loads(result.stdout or "{}")


def collect_local_state(tap_formulas, tap_casks):
    list_lines = lambda kind: subprocess.run(  # noqa: E731
        ["brew", "list", kind, "-1"], capture_output=True, text=True, check=False
    ).stdout.split()
    outdated = run_brew_json("outdated", "--json=v2")
    tap_info = run_brew_json("info", "--json=v2", *tap_formulas) if tap_formulas else {}
    tap_cask_info = run_brew_json("info", "--json=v2", "--cask", *tap_casks) if tap_casks else {}
    return {
        "installed_formulas": set(list_lines("--formula")),
        "installed_casks": set(list_lines("--cask")),
        "outdated_formulas": {o["name"]: o for o in outdated.get("formulae", [])},
        "outdated_casks": {o["name"]: o for o in outdated.get("casks", [])},
        "tap_formulas": {f["full_name"]: f for f in tap_info.get("formulae", [])},
        "tap_casks": {c["full_token"]: c for c in tap_cask_info.get("casks", [])},
    }


def parse_brewfile(path):
    entries = {kind: [] for kind in ("tap", "brew", "cask", "mas", "vscode", "go", "cargo", "whalebrew")}
    for line in Path(path).read_text().splitlines():
        match = re.match(r'^\s*(\w+)\s+"([^"]+)"', line)
        if match and match.group(1) in entries:
            entries[match.group(1)].append(match.group(2))
    return entries


def count_classes(records, key_of):
    counts = {}
    for record in records:
        key = key_of(record)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def source_build_triggers(records):
    """Installed + outdated formulas whose upgrade would compile on this machine."""
    return sorted(
        (r for r in records.values() if r["installed"] and r["outdated"] and r["class"] == "NO_INTEL_BOTTLE"),
        key=lambda r: -r.get("priority", 0),
    )


def build_report(brewfile, entries, missing, records, casks):
    ranked = sorted((r for r in records.values() if "priority" in r), key=lambda r: -r["priority"])
    return {
        "brewfile": str(brewfile),
        "data_dir": str(DATA_DIR),
        "entry_counts": {kind: len(names) for kind, names in entries.items()},
        "missing_from_core": missing,
        "formula_counts": count_classes(records.values(), lambda r: f"{r['class']}/{r['role']}"),
        "cask_counts": count_classes(casks.values(), lambda r: r["class"]),
        "build_ranking": [r["name"] for r in ranked],
        "upgrade_triggers_source_build": [r["name"] for r in source_build_triggers(records)],
        "formulas": records,
        "casks": casks,
    }


def ranking_reason(record):
    parts = [record["class"].lower(), f"weight {record['build_weight']}"]
    if record.get("source_bytes"):
        parts.append(f"src {record['source_bytes'] / 1e6:.0f} MB")
    if record.get("build_toolchains"):
        parts.append("needs " + "+".join(record["build_toolchains"]))
    parts.append(f"fan-in {record['fan_in']} runtime / {record['build_fan_in']} build")
    return "; ".join(parts)


def markdown_header(report):
    removed = ", ".join(report["missing_from_core"]) or "none"
    entries = ", ".join(f"{kind} {count}" for kind, count in report["entry_counts"].items())
    lines = [
        "# Brewfile Intel audit",
        "",
        bullet(f"Brewfile: `{report['brewfile']}`"),
        bullet(f"Entries: {entries}"),
        bullet(f"Removed from core (cannot install): {removed}"),
        "",
        "## Formula classes (class/role)",
        "",
    ]
    lines += [bullet(f"{key}: {count}") for key, count in report["formula_counts"].items()]
    lines += ["", "## Cask classes", ""] + [bullet(f"{k}: {v}") for k, v in report["cask_counts"].items()]
    flagged = [c for c in report["casks"].values() if c["class"] != "OK"]
    lines += ["", "## Flagged casks", ""]
    return lines + [bullet(f"{c['name']}: {c['class']} ({'; '.join(c['reasons'])})") for c in flagged]


def markdown_lines(report, top):
    lines = [*markdown_header(report), "", f"## Top {top} to pre-build", ""]
    formulas = report["formulas"]
    lines += [
        bullet(f"`{name}`: {ranking_reason(formulas[name])}", marker=f"{index}. ")
        for index, name in enumerate(report["build_ranking"][:top], 1)
    ]
    lines += flagged_formula_lines(formulas, "Intel version pinned", "pinned")
    lines += flagged_formula_lines(formulas, "Disabled in core", "disabled:")
    triggers = report["upgrade_triggers_source_build"]
    lines += [
        "",
        f"## Installed and outdated: upgrade compiles from source ({len(triggers)})",
        "",
        paragraph(", ".join(f"`{name}`" for name in triggers)),
    ]
    return [*lines, ""]


def flagged_formula_lines(formulas, title, reason_marker):
    flagged = [r for r in formulas.values() if any(reason_marker in x for x in r["reasons"])]
    rows = [
        bullet(f"`{r['name']}` ({r['role']}): {'; '.join(r['reasons'])}")
        for r in sorted(flagged, key=lambda r: r["name"])
    ]
    return ["", f"## {title}", ""] + (rows or [paragraph("")])


def write_reports(report, top):
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "brewfile.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    (REPORTS_DIR / "brewfile.md").write_text("\n".join(markdown_lines(report, top)))
    LOG.info("wrote %s and %s", REPORTS_DIR / "brewfile.json", REPORTS_DIR / "brewfile.md")


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("brewfile", type=Path, help="path to the Brewfile to audit")
    parser.add_argument("--head-limit", type=int, default=60, help="max HEAD requests for source sizes")
    parser.add_argument("--top", type=int, default=40, help="ranked entries in the Markdown report")
    parser.add_argument("--verbose", "-v", action="store_true", help="log progress to stderr")
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    logging.basicConfig(level=logging.INFO if arguments.verbose else logging.WARNING, format="%(message)s")
    api, entries = load_api(), parse_brewfile(arguments.brewfile)
    local = collect_local_state(
        [n for n in entries["brew"] if is_tap_name(n)], [n for n in entries["cask"] if is_tap_name(n)]
    )
    direct = [resolve_formula_name(n, api) for n in entries["brew"]]
    missing = [n for n in direct if n not in api["formulas"] and n not in local["tap_formulas"]]
    records, known_direct = build_formula_records(direct, api, local)
    requirements = BuildRequirements(records, api)
    annotate_fan_in(records, known_direct, api, requirements)
    annotate_build_cost(records, requirements)
    annotate_source_sizes(records, arguments.head_limit)
    casks = {token: classify_cask(token, api, local) for token in entries["cask"]}
    write_reports(build_report(arguments.brewfile, entries, missing, records, casks), arguments.top)


if __name__ == "__main__":
    main()
