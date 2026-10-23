"""Classify Brewfile formulae and casks for Intel macOS Sequoia."""

import brew_api
from brew_api import INTEL_TAG, load_json, load_tag_payload

INTEL_OLDER_TAGS = ("sonoma", "ventura", "monterey", "big_sur", "catalina")
NEEDS_BUILD = ("NO_INTEL_BOTTLE", "OLD_INTEL_BOTTLE")


def load_api():
    """Full formula/cask APIs plus the per-tag evaluations, keyed by name."""
    return {
        "formulas": {formula["name"]: formula for formula in load_json("formula.json")},
        "casks": {cask["token"]: cask for cask in load_json("cask.json")},
        "tags": {tag: load_tag_payload(tag) for tag in (INTEL_TAG, "arm64_sequoia")},
    }


def resolve_formula_name(name, api):
    sequoia = api["tags"]["sequoia"]
    short = name.removeprefix("homebrew/core/")
    if short in api["formulas"]:
        return short
    return {**sequoia.get("formula_aliases", {}), **sequoia.get("formula_renames", {})}.get(short, short)


def intel_dependencies(name, api):
    """(runtime, build) dependencies as evaluated for Intel Sequoia."""
    raw = api["tags"]["sequoia"]["formulae"].get(name, {}).get("stable_dependencies")
    if raw is None:
        formulae = api["formulas"]
        return (
            brew_api.intel_dependencies(name, formulae, "dependencies"),
            brew_api.intel_dependencies(name, formulae, "build_dependencies"),
        )
    runtime, build = [], []
    for dep in raw:
        if isinstance(dep, str):
            runtime.append(dep)
            continue
        for dep_name, kind in dep.items():
            if ":build" in (kind if isinstance(kind, list) else [kind]):
                build.append(dep_name)
    known = api["formulas"]
    return [d for d in runtime if d not in build and d in known], [d for d in build if d in known]


def intel_bottle_tags(formula):
    files = ((formula.get("bottle") or {}).get("stable") or {}).get("files", {})
    return sorted(tag for tag in files if not tag.startswith("arm64") and "linux" not in tag)


def classify_core_formula(name, api):
    formula, tags = api["formulas"][name], api["tags"]
    bottles, reasons = intel_bottle_tags(formula), []
    if any(r["name"] == "arch" and r["version"] == "arm64" for r in formula.get("requirements", [])):
        return "ARM_ONLY", ["requires arch arm64"]
    if formula.get("disabled"):
        reasons.append(f"disabled: {formula.get('disable_reason')}")
    if "sequoia" in bottles or "all" in bottles:
        status = "OK"
        reasons.append("bottle: " + ("sequoia" if "sequoia" in bottles else "all"))
    elif older := [t for t in INTEL_OLDER_TAGS if t in bottles]:
        status = "OLD_INTEL_BOTTLE"
        reasons.append("only older Intel bottle(s): " + ",".join(older))
    else:
        status = "NO_INTEL_BOTTLE"
        reasons.append("no Intel macOS bottle for current version")
    intel_version = tags["sequoia"]["formulae"].get(name, {}).get("stable_version")
    arm_version = tags["arm64_sequoia"]["formulae"].get(name, {}).get("stable_version")
    if intel_version and arm_version and intel_version != arm_version:
        reasons.append(f"Intel pinned to {intel_version} vs ARM {arm_version}")
        status = "INTEL_VERSION_PINNED" if status == "OK" else status
    return status, reasons


def classify_tap_formula(formula):
    bottles, url = intel_bottle_tags(formula), formula["urls"]["stable"]["url"]
    if any(r["name"] == "arch" and r["version"] == "arm64" for r in formula["requirements"]):
        return "ARM_ONLY", ["requires arch arm64"]
    if "sequoia" in bottles or "all" in bottles:
        return "OK", ["tap bottle"]
    if bottles:
        return "OLD_INTEL_BOTTLE", [f"tap bottle only for {','.join(bottles)}"]
    if formula["build_dependencies"] or "/archive/" in url:
        return "NO_INTEL_BOTTLE", [f"builds from source ({url}); build deps {formula['build_dependencies']}"]
    return "OK", [f"prebuilt Intel binary download ({url.rsplit('/', 1)[-1]})"]


def core_record(name, role, api, local):
    status, reasons = classify_core_formula(name, api)
    runtime, build = intel_dependencies(name, api)
    tags = api["tags"]
    return {
        "name": name,
        "role": role,
        "class": status,
        "reasons": reasons,
        "intel_bottle_tags": intel_bottle_tags(api["formulas"][name]),
        "version_intel": tags["sequoia"]["formulae"].get(name, {}).get("stable_version"),
        "version_arm": tags["arm64_sequoia"]["formulae"].get(name, {}).get("stable_version"),
        "runtime_deps": runtime,
        "build_deps": build,
        "installed": name in local["installed_formulas"],
        "outdated": name in local["outdated_formulas"],
        "installed_versions": local["outdated_formulas"].get(name, {}).get("installed_versions"),
        "url": api["formulas"][name]["urls"]["stable"]["url"],
    }


def tap_record(full_name, local):
    formula = local["tap_formulas"][full_name]
    status, reasons = classify_tap_formula(formula)
    return {
        "name": full_name,
        "role": "direct",
        "class": status,
        "reasons": reasons,
        "tap": formula["tap"],
        "version_intel": formula["versions"]["stable"],
        "runtime_deps": formula["dependencies"],
        "build_deps": formula["build_dependencies"],
        "installed": bool(formula.get("installed")),
        "outdated": formula["outdated"],
        "url": formula["urls"]["stable"]["url"],
    }


def runtime_closure(roots, api):
    seen, stack = set(), list(roots)
    while stack:
        name = stack.pop()
        if name in seen or name not in api["formulas"]:
            continue
        seen.add(name)
        stack.extend(intel_dependencies(name, api)[0])
    return seen


def build_formula_records(direct, api, local):
    core_direct = [n for n in direct if n in api["formulas"]]
    tap_direct = [n for n in direct if n in local["tap_formulas"]]
    tap_runtime = [d for n in tap_direct for d in local["tap_formulas"][n]["dependencies"]]
    records = {
        n: core_record(n, "direct" if n in core_direct else "runtime_dep", api, local)
        for n in sorted(runtime_closure(core_direct + tap_runtime, api))
    }
    records.update({n: tap_record(n, local) for n in tap_direct})
    queue = [b for r in records.values() if r["class"] in NEEDS_BUILD for b in r["build_deps"]]
    while queue:
        for name in runtime_closure([queue.pop()], api) - records.keys():
            records[name] = core_record(name, "build_dep", api, local)
            if records[name]["class"] in NEEDS_BUILD:
                queue.extend(records[name]["build_deps"])
    return records, core_direct + tap_direct


def cask_lifecycle_flags(token, api):
    """Compare Intel vs ARM evaluation of disable/deprecate and version."""
    intel = api["tags"]["sequoia"]["casks"].get(token)
    arm = api["tags"]["arm64_sequoia"]["casks"].get(token, {})
    if intel is None:
        return "ARM_ONLY", ["no Intel Sequoia evaluation of this cask"]
    status, reasons = "OK", []
    for key, label in (("disable_args", "DISABLED"), ("deprecate_args", "DEPRECATED")):
        if not intel.get(key):
            continue
        scope = "INTEL" if intel.get(key) != arm.get(key) else "ALL"
        reasons.append(f"{key} ({scope.lower()}): {intel[key]}")
        status = f"{label}_{scope}" if status == "OK" or label == "DISABLED" else status
    intel_version, arm_version = intel.get("version", ""), arm.get("version", "")
    if intel_version.split(",")[0] != arm_version.split(",")[0] and arm_version:
        reasons.append(f"Intel version {intel_version} vs ARM {arm_version}")
        status = "INTEL_VERSION_PINNED" if status == "OK" else status
    return status, reasons


def classify_cask(token, api, local):
    short = token.rsplit("/", 1)[-1]
    record = {
        "name": token,
        "installed": short in local["installed_casks"],
        "outdated": short in local["outdated_casks"],
    }
    if token in local["tap_casks"]:
        url = local["tap_casks"][token]["url"]
        return {**record, "class": "OK", "reasons": [f"third-party tap; {url.rsplit('/', 1)[-1]}"]}
    cask = api["casks"].get(token)
    if cask is None:
        return {**record, "class": "MISSING", "reasons": ["not in cask API (removed or renamed)"]}
    arch = (cask.get("depends_on") or {}).get("arch") or []
    platforms = cask.get("supported_platforms") or []
    if (arch and all(a.get("type") == "arm" for a in arch)) or (platforms and "sequoia" not in platforms):
        return {**record, "class": "ARM_ONLY", "reasons": [f"depends_on arch {arch}; platforms {platforms}"]}
    status, reasons = cask_lifecycle_flags(token, api)
    return {**record, "class": status, "reasons": reasons or ["Intel build available"], "version": cask.get("version")}
