"""Shared helpers for the Intel-support audit: paths, API loading, report output."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# scripts/tap/closure.py (stdlib-only) owns how brew resolves a core formula's
# dependency keys on Intel; appended so this directory's modules keep precedence.
sys.path.append(str(REPO_ROOT / "scripts" / "tap"))
import closure  # noqa: E402

DATA_DIR = Path(os.environ.get("HOMEBREW_INTEL_DATA", REPO_ROOT / ".cache" / "api"))
REPORTS_DIR = REPO_ROOT / "reports"

INTEL_MACOS_TAGS = ["tahoe", "sequoia", "sonoma", "ventura", "monterey", "big_sur"]
CURRENT_INTEL_TAGS = {"tahoe", "sequoia"}
INTEL_TAG = closure.INTEL_VARIATION
ARM_TAG = "arm64_sequoia"


def intel_dependencies(name, formulae, *keys):
    """A formula.json entry's dependency keys as brew resolves them on Intel Sequoia.

    The top-level lists describe ARM macOS; each key in the Intel variation
    replaces its top-level list outright.
    """
    return closure.dependencies(name, formulae, *keys)


def load_json(name):
    """Load a JSON file from the data directory, failing fast if it is missing."""
    path = DATA_DIR / name
    if not path.exists():
        message = f"missing {path}; run scripts/audit/fetch-api.sh first"
        raise SystemExit(message)
    with path.open() as handle:
        return json.load(handle)


def load_tag_payload(tag):
    """Load the per-bottle-tag internal API (a JWS whose payload is a JSON string)."""
    return json.loads(load_json(f"packages.{tag}.jws.json")["payload"])


def load_analytics(name, key):
    """Return {package: 90-day install count} from an analytics file."""
    items = load_json(name)["items"]
    return {item.get(key): int(item["count"].replace(",", "")) for item in items}


def bottle_files(formula):
    """Bottle tags of the formula's current stable version."""
    return ((formula.get("bottle") or {}).get("stable") or {}).get("files", {})


def brew_repo(tap=None):
    """Path of the Homebrew repository or of a tap's git checkout."""
    args = ["brew", "--repo"] + ([tap] if tap else [])
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip()


def write_report(name, rows):
    """Write rows as reports/<name>.json and return the path."""
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"{name}.json"
    path.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n")
    return path
