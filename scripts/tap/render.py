"""Render enabled homebrew-core formulae, and their dependency closure, into this tap."""

import argparse
import sys
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from pathlib import Path

from bottles import bottle_release_tag, pkg_version, release_tag
from closure import DependencyCycleError, build_order, expand
from core_source import CoreSourceError, core_repo, formula_relpath, head_commit, read_formula
from enabled import ConfigError, Entry, load_enabled
from patching import PatchError, apply_patch, make_patch
from transform import TransformError, apply_bottle, extract_bottle_block, render_body, strip_bottle_block

TAP_ROOT = Path(__file__).resolve().parents[2]
RENDER_ERRORS = (ConfigError, CoreSourceError, TransformError, PatchError)


class RenderError(RuntimeError):
    pass


def load_formulae() -> dict[str, Mapping]:
    sys.path.insert(0, str(TAP_ROOT / "scripts" / "audit"))
    from brew_api import load_json  # noqa: PLC0415 - audit helpers are not on sys.path by default

    return {formula["name"]: formula for formula in load_json("formula.json")}


def render_formula(  # noqa: PLR0913 - keyword-only signature fixed by the design
    source: str,
    *,
    name: str,
    commit: str,
    tap_names: AbstractSet[str],
    patch: str | None,
    bottle_block: str | None,
) -> str:
    body = render_body(source, name=name, commit=commit, tap_names=tap_names)
    if patch:
        body = apply_patch(body, patch, name=name)
    return apply_bottle(body, bottle_block)


def patch_path(tap_dir: Path, name: str) -> Path:
    return tap_dir / "patches" / f"{name}.patch"


def formula_files(tap_dir: Path) -> list[Path]:
    return sorted((tap_dir / "Formula").glob("**/*.rb"))


def read_patch(tap_dir: Path, name: str) -> str | None:
    path = patch_path(tap_dir, name)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    print(f"render: {name}: no {path.relative_to(tap_dir)} yet; rendered unpatched", file=sys.stderr)
    return None


def existing_bottle(path: Path, name: str, formulae: Mapping[str, Mapping]) -> str | None:
    """Return the committed bottle block unless the API says its version is stale."""
    block = extract_bottle_block(path.read_text(encoding="utf-8")) if path.is_file() else None
    if block is None or name not in formulae:
        return block
    current = release_tag(name, pkg_version(formulae[name]))
    return block if bottle_release_tag(block) == current else None


def render_one(
    entry: Entry, repo: Path, commit: str, tap_names: AbstractSet[str], formulae: Mapping[str, Mapping]
) -> str:
    patched = entry.kind == "patched"
    source_commit = entry.base if patched and entry.base else commit
    return render_formula(
        read_formula(repo, entry.name, source_commit),
        name=entry.name,
        commit=source_commit,
        tap_names=tap_names,
        patch=read_patch(TAP_ROOT, entry.name) if patched else None,
        bottle_block=existing_bottle(TAP_ROOT / formula_relpath(entry.name), entry.name, formulae),
    )


def render_all(
    order: list[str], entries: Mapping[str, Entry], commit: str | None, formulae: Mapping[str, Mapping]
) -> dict[Path, str]:
    repo = core_repo()
    commit = commit or head_commit(repo)
    rendered = {}
    for name in order:
        entry = entries.get(name, Entry(name, "generated", None))
        try:
            rendered[TAP_ROOT / formula_relpath(name)] = render_one(entry, repo, commit, set(order), formulae)
        except RENDER_ERRORS as error:
            msg = f"{name}: {error}"
            raise RenderError(msg) from error
    return rendered


def write_all(rendered: Mapping[Path, str]) -> None:
    for path, text in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for path in formula_files(TAP_ROOT):
        if path not in rendered:
            print(f"warning: {path.relative_to(TAP_ROOT)} is not in the enabled set", file=sys.stderr)


def make_patch_file(name: str, entries: Mapping[str, Entry], tap_names: AbstractSet[str]) -> None:
    entry = entries.get(name)
    if entry is None or entry.base is None:
        msg = f"{name}: --make-patch needs a patched entry with base in enabled.toml"
        raise ConfigError(msg)
    relpath = formula_relpath(name)
    if not (TAP_ROOT / relpath).is_file():
        msg = f"{name}: {relpath} does not exist"
        raise ConfigError(msg)
    original = render_body(
        read_formula(core_repo(), name, entry.base), name=name, commit=entry.base, tap_names=tap_names
    )
    edited = strip_bottle_block((TAP_ROOT / relpath).read_text(encoding="utf-8"))
    path = patch_path(TAP_ROOT, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(make_patch(original, edited, relpath), encoding="utf-8")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-commit", metavar="SHA", help="core commit for generated formulae (default: HEAD)")
    parser.add_argument("--print-order", action="store_true", help="print the build order and write nothing")
    parser.add_argument("--make-patch", metavar="NAME", help="write patches/NAME.patch from the committed formula")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> None:
    entries = {entry.name: entry for entry in load_enabled(TAP_ROOT / "enabled.toml")}
    formulae = load_formulae()
    order = build_order(expand(entries, formulae), formulae)
    if args.print_order:
        for name in order:
            print(name)
    elif args.make_patch:
        make_patch_file(args.make_patch, entries, set(order))
    else:
        write_all(render_all(order, entries, args.core_commit, formulae))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except (*RENDER_ERRORS, RenderError, DependencyCycleError, OSError) as error:
        print(f"render: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
