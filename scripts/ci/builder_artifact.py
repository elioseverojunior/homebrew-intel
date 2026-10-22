"""Bind every hosted job of a builder run to one builder-out artifact by its digest.

`select LISTING` reads `gh api --paginate .../actions/runs/<id>/artifacts
--jq .artifacts` (one JSON array per page, concatenated), requires exactly one
unexpired `builder-out` with a numeric id and a sha256 digest, and prints
`id=<id>` and `digest=sha256:<hex>` lines for $GITHUB_OUTPUT. The verify job
runs it; the other jobs download that id with actions/download-artifact
(`artifact-ids`, `skip-decompress: true`).

`unpack DOWNLOAD_DIR DIGEST OUT` then requires DOWNLOAD_DIR to hold exactly one
regular file whose sha256 is DIGEST, and extracts it into OUT, which must not
exist yet. Members with an absolute path, a `..` component or a symlink mode
fail the whole artifact, so nothing outside OUT is written and no link is
followed later.
"""

import argparse
import hashlib
import re
import stat
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from verify_bot_pr import load_pages

NAME = "builder-out"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def select(artifacts: Sequence[Mapping]) -> tuple[int, str]:
    """The id and digest of the run's single, unexpired builder-out artifact."""
    found = [artifact for artifact in artifacts if artifact.get("name") == NAME]
    if len(found) != 1:
        msg = f"expected exactly one {NAME} artifact, found {len(found)}"
        raise ValueError(msg)
    (artifact,) = found
    identifier, digest = artifact.get("id"), artifact.get("digest")
    if artifact.get("expired") is not False or type(identifier) is not int or identifier <= 0:
        msg = f"{NAME} is expired or has no valid id: {identifier!r}"
        raise ValueError(msg)
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        msg = f"{NAME} has no sha256 digest: {digest!r}"
        raise ValueError(msg)
    return identifier, digest


def _downloaded_file(download_dir: Path) -> Path:
    entries = list(download_dir.iterdir())
    if len(entries) != 1 or entries[0].is_symlink() or not entries[0].is_file():
        msg = f"{download_dir} must hold exactly one regular file, holds {sorted(e.name for e in entries)}"
        raise ValueError(msg)
    return entries[0]


def _member_problem(member: zipfile.ZipInfo) -> str | None:
    path = PurePosixPath(member.filename)
    if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
        return f"unsafe member path {member.filename!r}"
    if stat.S_ISLNK(member.external_attr >> 16):
        return f"symlink member {member.filename!r}"
    return None


def unpack(download_dir: Path, digest: str, out: Path) -> None:
    """Extract the downloaded artifact into OUT once its digest is DIGEST."""
    archive_path = _downloaded_file(download_dir)
    actual = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if actual != digest:
        msg = f"{archive_path.name} has digest {actual}, not the verified {digest}"
        raise ValueError(msg)
    if out.exists():
        msg = f"{out} already exists"
        raise ValueError(msg)
    with zipfile.ZipFile(archive_path) as archive:
        if problems := [p for p in map(_member_problem, archive.infolist()) if p]:
            raise ValueError("; ".join(problems))
        out.mkdir(parents=True)
        archive.extractall(out)  # every member path was checked above


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("select").add_argument("listing", type=Path)
    unpacking = commands.add_parser("unpack")
    unpacking.add_argument("download_dir", type=Path)
    unpacking.add_argument("digest")
    unpacking.add_argument("out", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "select":
            identifier, digest = select(load_pages(args.listing.read_text(encoding="utf-8")))
            print(f"id={identifier}\ndigest={digest}")
        else:
            unpack(args.download_dir, args.digest, args.out)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"builder-artifact: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
