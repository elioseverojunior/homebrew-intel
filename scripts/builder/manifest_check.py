"""The manifest half of verify_artifact.py's trust boundary.

The build host writes manifest.json; nothing in it is trusted until these
checks pass: exact key sets, field patterns (no `/`, no whitespace), relpaths
from the name, unique names and bottle asset names, this checkout's commit and
the core commit the hosted prepare job pinned (Pins). The enabled closure in
Pins is what the hosted verify job computed with render.py --print-order from
the checkout's enabled.toml and a fresh API snapshot; load_closure() reads it.
"""

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tap"))
from core_source import formula_relpath
from manifest import MANIFEST, SCALARS, SECTIONS

PATTERNS = {
    "name": re.compile(r"[a-z0-9][a-z0-9@._+-]*"),
    "version": re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*"),
    "tarball": re.compile(r"[a-z0-9][A-Za-z0-9@._+-]*\.tar\.gz"),
    "json": re.compile(r"[a-z0-9][A-Za-z0-9@._+-]*\.json"),
    "log": re.compile(r"[a-z0-9][A-Za-z0-9@._+-]*\.log"),
    "core_commit": re.compile(r"[0-9a-f]{40}"),
    "tap_sha": re.compile(r"[0-9a-f]{40}"),
    "branch_date": re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}"),
}


class Pins(NamedTuple):
    """What the hosted jobs resolved themselves, never read from the artifact."""

    core_commit: str
    closure: frozenset[str]


def load_closure(path: Path) -> frozenset[str]:
    """The whitespace-separated formula names of the enabled closure."""
    names = path.read_text(encoding="utf-8").split()
    if not names:
        msg = f"{path}: the enabled closure is empty"
        raise ValueError(msg)
    if invalid := [name for name in names if not PATTERNS["name"].fullmatch(name)]:
        msg = f"{path}: invalid formula names {invalid}"
        raise ValueError(msg)
    return frozenset(names)


def _field_problems(label: str, entry: Mapping, keys: tuple[str, ...]) -> list[str]:
    if not isinstance(entry, Mapping) or tuple(sorted(entry)) != tuple(sorted(keys)):
        return [f"{label}: expected exactly the keys {', '.join(keys)}"]
    found = [f"{label}: {key} is not a string" for key in keys if not isinstance(entry[key], str)]
    for key in keys:
        pattern = PATTERNS.get(key)
        if not found and pattern and not pattern.fullmatch(entry[key]):
            found.append(f"{label}: invalid {key} '{entry[key]}'")
    if not found and "relpath" in entry and entry["relpath"] != (expected := formula_relpath(entry["name"])):
        found.append(f"{label}: relpath {entry['relpath']} is not {expected}")
    return found


def _scalar_problems(document: Mapping, tap_sha: str, core_commit: str) -> list[str]:
    found = _field_problems(MANIFEST, {key: document[key] for key in SCALARS}, SCALARS)
    if not found and document["tap_sha"] != tap_sha:
        found.append(f"{MANIFEST}: tap_sha {document['tap_sha']} is not the checkout's {tap_sha}")
    if not found and document["core_commit"] != core_commit:
        found.append(f"{MANIFEST}: core_commit {document['core_commit']} is not the pinned {core_commit}")
    return found


def _repeated(values: list[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def manifest_problems(document: object, tap_sha: str, core_commit: str) -> list[str]:
    """Shape problems of the manifest; the per-formula checks need none."""
    if not isinstance(document, Mapping) or set(document) != {*SCALARS, *SECTIONS}:
        return [f"{MANIFEST}: expected exactly the keys {', '.join([*SCALARS, *SECTIONS])}"]
    found = _scalar_problems(document, tap_sha, core_commit)
    names: list[str] = []
    for section, keys in SECTIONS.items():
        entries = document[section] if isinstance(document[section], list) else [None]
        for index, entry in enumerate(entries):
            found += _field_problems(f"{section}[{index}]", entry, keys)
            names += [entry["name"]] if isinstance(entry, Mapping) and "name" in entry else []
    found += [f"{name} is listed more than once" for name in _repeated(names)]
    if found:
        return found
    return [f"asset {name} is claimed more than once" for name in _repeated([e["tarball"] for e in document["built"]])]


def closure_problems(names: list[str], closure: frozenset[str]) -> list[str]:
    """Every published name must be in the enabled closure the hosted job computed."""
    return [f"{name} is not in the enabled closure" for name in names if name not in closure]
