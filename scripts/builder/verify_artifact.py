"""Verify the build host's artifact before anything from it is published.

The trust boundary between the self-hosted build (which runs formula code and
holds no secret) and the hosted publish job (which holds the App token). It
fails closed unless the manifest is well formed, names this checkout's commit,
and every built or render-only formula is, bottle block aside, exactly what
render.py makes from homebrew-core at the manifest's core commit (the entry's
base and patch for a patched formula), so no hand-made formula code can pass.
A built formula's version must be the one the publish job derived itself from
the verified formula (derive-versions.sh), never just the manifest's, and its
bottle block must agree with that version, its tarball and its bottle JSON
(bottle_check.py); a render-only one keeps main's block or has none.

Usage: verify_artifact.py --artifact DIR [--tap DIR]
(--formulae-only [--renders DIR] | --versions JSON | --list-commits). The
core repository comes from HOMEBREW_CORE_REPO. --formulae-only checks the
manifest, each bottle section's strict grammar and the formula texts, before
anything evaluates a formula; with --renders it then writes each formula's
trusted render (made here from core, never copied from the artifact) for
derive-versions.sh to evaluate. --versions maps each built name to its
derived pkg_version for the full check. --list-commits validates the manifest
and prints the core commits to fetch, one per line.
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tap"))
from bottle_check import Bottle, syntax_problems
from bottle_check import problems as bottle_problems
from bottles import release_tag
from core_source import core_repo, formula_relpath, read_formula
from drift import short_diff
from enabled import Entry, load_enabled
from manifest import MANIFEST, SCALARS, SECTIONS
from render import RENDER_ERRORS, formula_files, patch_path, render_formula
from transform import BOTTLE_MARKER, bottle_blocks, strip_bottle_block

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
PUBLISHED = ("built", "render_only")


class Context(NamedTuple):
    """What every formula check reads: the artifact, the checkout and core."""

    out: Path
    tap: Path
    repo: Path
    document: Mapping
    entries: Mapping[str, Entry]
    tap_names: set[str]
    versions: Mapping[str, str] | None


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


def manifest_problems(document: object, tap_sha: str) -> list[str]:
    """Shape problems of the manifest; the per-formula checks need none."""
    if not isinstance(document, Mapping) or set(document) != {*SCALARS, *SECTIONS}:
        return [f"{MANIFEST}: expected exactly the keys {', '.join([*SCALARS, *SECTIONS])}"]
    found = _field_problems(MANIFEST, {key: document[key] for key in SCALARS}, SCALARS)
    if not found and document["tap_sha"] != tap_sha:
        found.append(f"{MANIFEST}: tap_sha {document['tap_sha']} is not the checkout's {tap_sha}")
    names: list[str] = []
    for section, keys in SECTIONS.items():
        entries = document[section] if isinstance(document[section], list) else [None]
        for index, entry in enumerate(entries):
            found += _field_problems(f"{section}[{index}]", entry, keys)
            names += [entry["name"]] if isinstance(entry, Mapping) and "name" in entry else []
    found += [f"{name} is listed more than once" for name in sorted({n for n in names if names.count(n) > 1})]
    return found


def expected_formula(context: Context, name: str) -> str:
    entry = context.entries.get(name, Entry(name, "generated", None))
    patched = entry.kind == "patched"
    commit = entry.base if patched and entry.base else context.document["core_commit"]
    patch = patch_path(context.tap, name)
    patch_text = patch.read_text(encoding="utf-8") if patched and patch.is_file() else None
    source = read_formula(context.repo, name, commit)
    tap_names = context.tap_names
    return render_formula(source, name=name, commit=commit, tap_names=tap_names, patch=patch_text, bottle_block=None)


def _regular_file(path: Path, label: str) -> list[str]:
    return [] if path.is_file() and not path.is_symlink() else [f"{label} is not a regular file"]


def _placement_problems(text: str, block: str) -> list[str]:
    after_marker = f"{BOTTLE_MARKER}\n{block}" in text
    before_marker = f"{block}\n{BOTTLE_MARKER}\n" in text
    return [] if after_marker or before_marker else ["bottle block is not next to the bottle marker"]


def _shape_problems(context: Context, section: str, entry: Mapping, text: str) -> list[str]:
    """The bottle section's grammar, checked in every mode before anything else."""
    blocks = bottle_blocks(text)
    if section == "render_only":
        main_path = context.tap / entry["relpath"]
        main = bottle_blocks(main_path.read_text(encoding="utf-8")) if main_path.is_file() else []
        return [] if not blocks or blocks == main else ["render-only bottle block differs from main's"]
    if len(blocks) != 1:
        return [f"expected one bottle block, found {len(blocks)}"]
    return syntax_problems(blocks[0]) or _placement_problems(text, blocks[0])


def _bottle_problems(context: Context, entry: Mapping, text: str) -> list[str]:
    (block,) = bottle_blocks(text)
    tarball, json_path = (context.out / "bottles" / entry[key] for key in ("tarball", "json"))
    found = _regular_file(tarball, entry["tarball"]) + _regular_file(json_path, entry["json"])
    if found:
        return found
    version = (context.versions or {}).get(entry["name"], entry["version"])
    bottle = Bottle(entry["name"], version, tarball, entry["json"])
    return bottle_problems(block, json.loads(json_path.read_text(encoding="utf-8")), bottle)


def _checked_render(context: Context, section: str, entry: Mapping) -> tuple[list[str], str | None]:
    """Problems of one formula and, when there are none, its trusted render."""
    relpath = entry["relpath"]
    if found := _regular_file(context.out / relpath, relpath):
        return found, None
    text = (context.out / relpath).read_text(encoding="utf-8")
    if found := _shape_problems(context, section, entry, text):
        return [f"{relpath}: {problem}" for problem in found], None
    try:
        expected = expected_formula(context, entry["name"])
    except RENDER_ERRORS as error:
        return [f"{relpath}: {error}"], None
    found = [] if context.versions is None or section != "built" else _bottle_problems(context, entry, text)
    if (actual := strip_bottle_block(text)) != expected:
        commit = context.document["core_commit"]
        found.append(f"differs from core@{commit} (+ patch):\n{short_diff(expected, actual, relpath).rstrip()}")
    return [f"{relpath}: {problem}" for problem in found], None if found else expected


def checkout_sha(tap: Path) -> str:
    result = subprocess.run(["git", "-C", str(tap), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def version_problems(built: list[Mapping], versions: Mapping[str, str]) -> list[str]:
    """The manifest's versions must be the derived ones, and release tags unique."""
    found, tags = [], [release_tag(entry["name"], entry["version"]) for entry in built]
    for entry in built:
        derived = versions.get(entry["name"])
        if derived is None:
            found.append(f"{entry['name']}: no derived version")
        elif derived != entry["version"]:
            found.append(f"{entry['name']}: manifest version {entry['version']} is not {derived}")
    duplicates = sorted({tag for tag in tags if tags.count(tag) > 1})
    return found + [f"release tag {tag} is claimed more than once" for tag in duplicates]


def _check(out: Path, tap: Path, repo: Path, versions: Mapping[str, str] | None) -> tuple[list[str], dict]:
    try:
        document = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"{MANIFEST}: {error}"], {}
    if found := manifest_problems(document, checkout_sha(tap)):
        return found, {}
    published = [(section, entry) for section in PUBLISHED for entry in document[section]]
    listed = {entry["relpath"] for _, entry in published}
    paths = [path.relative_to(out).as_posix() for path in formula_files(out)]
    found = [f"{path} is not listed in the manifest" for path in paths if path not in listed]
    tap_names = {path.stem for path in formula_files(tap)} | {entry["name"] for _, entry in published}
    entries = {entry.name: entry for entry in load_enabled(tap / "enabled.toml")}
    context = Context(out, tap, repo, document, entries, tap_names, versions)
    if versions is not None:
        found += version_problems(document["built"], versions)
    renders = {}
    for section, entry in published:
        problems_found, render = _checked_render(context, section, entry)
        found += problems_found
        renders[entry["relpath"]] = render
    return found, renders


def problems(out: Path, tap: Path, repo: Path, versions: Mapping[str, str] | None) -> list[str]:
    """Every reason the artifact must not be published; empty when it may.

    With versions None, the manifest, the bottle sections' grammar and the
    formula texts are checked, but not bottle contents or versions.
    """
    return _check(out, tap, repo, versions)[0]


def write_renders(out: Path, tap: Path, repo: Path, renders_dir: Path) -> list[str]:
    """Run the formulae-only check; only when it passes, write each trusted render."""
    found, renders = _check(out, tap, repo, None)
    if found:
        return found
    for relpath, text in renders.items():
        (renders_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (renders_dir / relpath).write_text(text, encoding="utf-8")
    return []


def needed_commits(out: Path, tap: Path) -> list[str]:
    document = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    if found := manifest_problems(document, checkout_sha(tap)):
        raise ValueError("; ".join(found))
    names = {entry["name"] for section in PUBLISHED for entry in document[section]}
    bases = {e.base for e in load_enabled(tap / "enabled.toml") if e.kind == "patched" and e.base and e.name in names}
    return [document["core_commit"], *sorted(bases - {document["core_commit"]})]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact", type=Path, required=True, help="the downloaded builder-out directory")
    parser.add_argument("--tap", type=Path, default=Path(__file__).resolve().parents[2], help="the tap checkout")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--formulae-only", action="store_true", help="check the manifest and formula texts only")
    mode.add_argument("--versions", type=Path, help="JSON mapping each built name to its derived pkg_version")
    mode.add_argument("--list-commits", action="store_true", help="print the core commits to fetch")
    parser.add_argument("--renders", type=Path, help="with --formulae-only: write each trusted render here")
    args = parser.parse_args(argv)
    if args.renders and not args.formulae_only:
        parser.error("--renders needs --formulae-only")
    return args


def run(args: argparse.Namespace) -> list[str]:
    if args.list_commits:
        print("\n".join(needed_commits(args.artifact, args.tap)))
        return []
    if args.renders:
        return write_renders(args.artifact, args.tap, core_repo(), args.renders)
    versions = None
    if args.versions:
        versions = json.loads(args.versions.read_text(encoding="utf-8"))
        if not isinstance(versions, dict) or not all(isinstance(v, str) for v in versions.values()):
            return [f"{args.versions}: expected a JSON object of name to version strings"]
    return problems(args.artifact, args.tap, core_repo(), versions)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        found = run(args)
    except (*RENDER_ERRORS, OSError, ValueError) as error:
        found = [str(error)]
    for problem in found:
        print(f"verify-artifact: {problem}", file=sys.stderr)
    if found:
        print("verify-artifact: refusing to publish this artifact", file=sys.stderr)
        return 1
    if not args.list_commits:
        print(f"verify-artifact: {'formula texts' if args.formulae_only else 'formulae and bottles'} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
