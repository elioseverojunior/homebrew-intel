"""Report tap formulae that no longer match what render.py would produce from core."""

import argparse
import difflib
import sys
from collections.abc import Set as AbstractSet
from pathlib import Path

from core_source import core_repo, read_formula
from enabled import Entry, load_enabled
from render import RENDER_ERRORS, TAP_ROOT, formula_files, patch_path, render_formula
from transform import parse_header, strip_bottle_block

DIFF_CONTEXT = 1
DIFF_MAX_LINES = 40


def short_diff(expected: str, actual: str, relpath: str) -> str:
    lines = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"expected/{relpath}",
            tofile=f"actual/{relpath}",
            n=DIFF_CONTEXT,
        ),
    )
    if len(lines) > DIFF_MAX_LINES:
        lines = [*lines[:DIFF_MAX_LINES], f"... {len(lines) - DIFF_MAX_LINES} more diff lines\n"]
    return "".join(lines)


def check_formula(path: Path, tap_dir: Path, repo: Path, tap_names: AbstractSet[str]) -> str | None:
    relpath = str(path.relative_to(tap_dir))
    text = path.read_text(encoding="utf-8")
    patch = patch_path(tap_dir, path.stem)
    try:
        commit = parse_header(text)
        expected = render_formula(
            read_formula(repo, path.stem, commit),
            name=path.stem,
            commit=commit,
            tap_names=tap_names,
            patch=patch.read_text(encoding="utf-8") if patch.is_file() else None,
            bottle_block=None,
        )
    except RENDER_ERRORS as error:
        return f"{relpath}: {error}"
    actual = strip_bottle_block(text)
    if actual == expected:
        return None
    return f"{relpath}: differs from core@{commit} (+ patch):\n{short_diff(expected, actual, relpath).rstrip()}"


def check_bookkeeping(tap_dir: Path, files: list[Path], entries: list[Entry]) -> list[str]:
    by_name = {path.stem: path for path in files}
    problems = [
        f"{path.relative_to(tap_dir)}: patch without a formula"
        for path in sorted((tap_dir / "patches").glob("*.patch"))
        if path.stem not in by_name
    ]
    for entry in entries:
        path = by_name.get(entry.name)
        if path is None:
            problems.append(f"enabled.toml: {entry.name} has no formula file")
            continue
        commit = header_commit(path)
        if entry.kind == "patched" and commit != entry.base:
            relpath = path.relative_to(tap_dir)
            problems.append(f"{relpath}: header commit {commit} differs from base {entry.base} in enabled.toml")
    return problems


def header_commit(path: Path) -> str | None:
    try:
        return parse_header(path.read_text(encoding="utf-8"))
    except RENDER_ERRORS:
        return None


def check(tap_dir: Path, repo: Path) -> list[str]:
    files = formula_files(tap_dir)
    enabled_path = tap_dir / "enabled.toml"
    entries = load_enabled(enabled_path) if enabled_path.is_file() else []
    tap_names = {path.stem for path in files}
    problems = [check_formula(path, tap_dir, repo, tap_names) for path in files]
    return [problem for problem in problems if problem] + check_bookkeeping(tap_dir, files, entries)


def header_commits(tap_dir: Path) -> list[str]:
    return sorted({commit for path in formula_files(tap_dir) if (commit := header_commit(path))})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-commits", action="store_true", help="print the unique core commits in headers")
    args = parser.parse_args(argv)
    if args.list_commits:
        for commit in header_commits(TAP_ROOT):
            print(commit)
        return 0
    try:
        problems = check(TAP_ROOT, core_repo())
    except RENDER_ERRORS as error:
        problems = [str(error)]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
