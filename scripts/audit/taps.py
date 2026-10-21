"""Scan installed third-party taps for formulae and casks that do not work on Intel."""

import argparse
import json
import subprocess

from brew_api import write_report


def brew_json(*args):
    """Run a brew command that prints JSON; return (data, stderr)."""
    result = subprocess.run(["brew", *args], capture_output=True, text=True, check=False)
    try:
        return json.loads(result.stdout), result.stderr
    except json.JSONDecodeError:
        return None, result.stderr


def third_party_taps():
    taps, _ = brew_json("tap-info", "--json", "--installed")
    return [tap for tap in taps if not tap["name"].startswith("homebrew/")]


def package_info(kind, names):
    """`brew info` for many packages, retrying one by one if the batch fails."""
    flag = "--formula" if kind == "formulae" else "--cask"
    data, _ = brew_json("info", "--json=v2", flag, *names)
    if data is not None:
        return data[kind], []
    found, broken = [], []
    for name in names:
        single, error = brew_json("info", "--json=v2", flag, name)
        if single is None:
            last_error = [line for line in error.splitlines() if "Error" in line][-1:]
            broken.append({"item": name, "reasons": ["fails to load: " + "".join(last_error)]})
        else:
            found += single[kind]
    return found, broken


def formula_reasons(formula):
    reasons = []
    if any(req["name"] == "arch" and req["version"] == "arm64" for req in formula["requirements"]):
        reasons.append("depends_on arch: :arm64")
    files = ((formula.get("bottle") or {}).get("stable") or {}).get("files", {})
    if files and all(tag.startswith("arm64") or "linux" in tag for tag in files):
        reasons.append("bottles only for ARM/Linux: " + ", ".join(files))
    if formula.get("disabled"):
        reasons.append(f"disabled: {formula.get('disable_reason')}")
    return reasons


def cask_reasons(cask):
    reasons = []
    if any(entry.get("type") == "arm" for entry in (cask.get("depends_on") or {}).get("arch") or []):
        reasons.append("depends_on arch: :arm64")
    if not cask.get("url"):
        reasons.append("no download URL on Intel")
    if cask.get("disabled"):
        reasons.append(f"disabled: {cask.get('disable_reason')}")
    return reasons


def scan_tap(tap):
    """Report rows for one tap's problematic formulae and casks."""
    rows = []
    for kind, key, reasons_for, id_key in [
        ("formulae", "formula_names", formula_reasons, "full_name"),
        ("casks", "cask_tokens", cask_reasons, "full_token"),
    ]:
        if not tap.get(key):
            continue
        packages, broken = package_info(kind, tap[key])
        rows += [{"tap": tap["name"], "kind": kind, **entry} for entry in broken]
        for package in packages:
            reasons = reasons_for(package)
            if reasons:
                rows.append(
                    {
                        "tap": tap["name"],
                        "kind": kind,
                        "item": package[id_key],
                        "installed": bool(package.get("installed")),
                        "reasons": reasons,
                    }
                )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print each finding")
    args = parser.parse_args()
    rows = [row for tap in third_party_taps() for row in scan_tap(tap)]
    path = write_report("taps", rows)
    if args.verbose:
        for row in rows:
            print(row["tap"], row["item"], row["reasons"])
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
