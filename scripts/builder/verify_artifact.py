"""Verify the build host's artifact before anything from it is published.

The trust boundary between the self-hosted build (which runs formula code and
holds no secret) and the hosted publish job (which holds the App token). It
fails closed unless the manifest is well formed (manifest_check.py), names this
checkout's commit and the core commit the hosted prepare job pinned, every
built or render-only formula is in the enabled closure the hosted verify job
computed (render.py --print-order), and each is, bottle block aside, exactly
what render.py makes from homebrew-core at that commit (the entry's base and
patch for a patched formula) with the closure as the tap names, so neither
hand-made formula code nor a host-chosen tap dependency can pass. A built
formula's version must be the one the hosted job derived itself from the
verified formula (derive-versions.sh), never just the manifest's, and its
bottle block must agree with that version, its tarball and its bottle JSON
(bottle_check.py). A render-only one has no block, or main's while its release
tag is the derived version's.

Usage: verify_artifact.py --artifact DIR [--tap DIR] --core-commit SHA
--closure FILE (--formulae-only [--renders DIR] | --versions JSON |
--list-commits). The core repository comes from HOMEBREW_CORE_REPO.
--formulae-only checks the manifest, each bottle section's strict grammar and
the formula texts, before anything evaluates a formula; with --renders it then
writes each formula's trusted render (made here from core, never copied from
the artifact) for derive-versions.sh to evaluate. --versions maps each built
and render-only name to its derived pkg_version for the full check.
--list-commits validates the manifest and prints the core commits to fetch,
one per line.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tap"))
from bottle_check import Bottle, syntax_problems
from bottle_check import problems as bottle_problems
from bottles import bottle_release_tag, release_tag
from core_source import core_repo, read_formula
from drift import short_diff
from enabled import Entry, load_enabled
from manifest import MANIFEST
from manifest_check import PATTERNS, Pins, closure_problems, load_closure, manifest_problems
from render import RENDER_ERRORS, formula_files, patch_path, render_formula
from transform import BOTTLE_MARKER, bottle_blocks, strip_bottle_block

PUBLISHED = ("built", "render_only")


class Context(NamedTuple):
    """What every formula check reads: the artifact, the checkout, core and the pins."""

    out: Path
    tap: Path
    repo: Path
    document: Mapping
    entries: Mapping[str, Entry]
    pins: Pins
    versions: Mapping[str, str] | None


def expected_formula(context: Context, name: str) -> str:
    entry = context.entries.get(name, Entry(name, "generated", None))
    patched = entry.kind == "patched"
    commit = entry.base if patched and entry.base else context.document["core_commit"]
    patch = patch_path(context.tap, name)
    patch_text = patch.read_text(encoding="utf-8") if patched and patch.is_file() else None
    source = read_formula(context.repo, name, commit)
    closure = context.pins.closure
    return render_formula(source, name=name, commit=commit, tap_names=closure, patch=patch_text, bottle_block=None)


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


def _render_only_problems(context: Context, entry: Mapping, text: str) -> list[str]:
    """Main's block stays only while its tag is the derived version's (render.py's existing_bottle)."""
    if not (blocks := bottle_blocks(text)):
        return []
    name, tag = entry["name"], bottle_release_tag(blocks[0])
    if (derived := (context.versions or {}).get(name)) is None:
        return ["render-only bottle block needs a derived version"]
    expected = release_tag(name, derived)
    return [] if tag == expected else [f"render-only bottle block is for {tag}, not {expected}"]


def _contents_problems(context: Context, section: str, entry: Mapping, text: str) -> list[str]:
    if context.versions is None:
        return []
    return (_bottle_problems if section == "built" else _render_only_problems)(context, entry, text)


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
    found = _contents_problems(context, section, entry, text)
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


def _check(out: Path, tap: Path, repo: Path, pins: Pins, versions: Mapping[str, str] | None) -> tuple[list[str], dict]:
    try:
        document = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"{MANIFEST}: {error}"], {}
    if found := manifest_problems(document, checkout_sha(tap), pins.core_commit):
        return found, {}
    published = [(section, entry) for section in PUBLISHED for entry in document[section]]
    listed = {entry["relpath"] for _, entry in published}
    paths = [path.relative_to(out).as_posix() for path in formula_files(out)]
    found = [f"{path} is not listed in the manifest" for path in paths if path not in listed]
    found += closure_problems([entry["name"] for _, entry in published], pins.closure)
    entries = {entry.name: entry for entry in load_enabled(tap / "enabled.toml")}
    context = Context(out, tap, repo, document, entries, pins, versions)
    if versions is not None:
        found += version_problems(document["built"], versions)
    renders = {}
    for section, entry in published:
        problems_found, render = _checked_render(context, section, entry)
        found += problems_found
        renders[entry["relpath"]] = render
    return found, renders


def problems(out: Path, tap: Path, repo: Path, pins: Pins, versions: Mapping[str, str] | None) -> list[str]:
    """Every reason the artifact must not be published; empty when it may.

    With versions None, the manifest, the bottle sections' grammar and the
    formula texts are checked, but not bottle contents or versions.
    """
    return _check(out, tap, repo, pins, versions)[0]


def write_renders(out: Path, tap: Path, repo: Path, pins: Pins, renders_dir: Path) -> list[str]:
    """Run the formulae-only check; only when it passes, write each trusted render."""
    found, renders = _check(out, tap, repo, pins, None)
    if found:
        return found
    for relpath, text in renders.items():
        (renders_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (renders_dir / relpath).write_text(text, encoding="utf-8")
    return []


def needed_commits(out: Path, tap: Path, pins: Pins) -> list[str]:
    document = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    if found := manifest_problems(document, checkout_sha(tap), pins.core_commit):
        raise ValueError("; ".join(found))
    names = {entry["name"] for section in PUBLISHED for entry in document[section]}
    bases = {e.base for e in load_enabled(tap / "enabled.toml") if e.kind == "patched" and e.base and e.name in names}
    return [document["core_commit"], *sorted(bases - {document["core_commit"]})]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact", type=Path, required=True, help="the downloaded builder-out directory")
    parser.add_argument("--tap", type=Path, default=Path(__file__).resolve().parents[2], help="the tap checkout")
    parser.add_argument("--core-commit", required=True, help="the homebrew-core commit the prepare job pinned")
    parser.add_argument("--closure", type=Path, required=True, help="the enabled closure, whitespace-separated")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--formulae-only", action="store_true", help="check the manifest and formula texts only")
    mode.add_argument("--versions", type=Path, help="JSON mapping each built name to its derived pkg_version")
    mode.add_argument("--list-commits", action="store_true", help="print the core commits to fetch")
    parser.add_argument("--renders", type=Path, help="with --formulae-only: write each trusted render here")
    args = parser.parse_args(argv)
    if args.renders and not args.formulae_only:
        parser.error("--renders needs --formulae-only")
    if not PATTERNS["core_commit"].fullmatch(args.core_commit):
        parser.error("--core-commit needs a 40-hex commit")
    return args


def run(args: argparse.Namespace) -> list[str]:
    pins = Pins(args.core_commit, load_closure(args.closure))
    if args.list_commits:
        print("\n".join(needed_commits(args.artifact, args.tap, pins)))
        return []
    if args.renders:
        return write_renders(args.artifact, args.tap, core_repo(), pins, args.renders)
    versions = None
    if args.versions:
        versions = json.loads(args.versions.read_text(encoding="utf-8"))
        if not isinstance(versions, dict) or not all(isinstance(v, str) for v in versions.values()):
            return [f"{args.versions}: expected a JSON object of name to version strings"]
    return problems(args.artifact, args.tap, core_repo(), pins, versions)


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
