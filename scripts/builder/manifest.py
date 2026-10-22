"""Write and read the builder's artifact manifest, <out>/manifest.json.

run.sh writes it on the build host: `init` once the core commit is known, then
one `built`, `render-only`, `failed` or `skipped` entry per formula, copying the
files an entry names into <out> (Formula/..., bottles/<file>). publish.sh and
pour.sh read it with `rows` (tab-separated fields, for bash) and `field`;
`summary` prints the pull request body. The host is untrusted:
verify_artifact.py validates the manifest before anything is published.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tap"))
from core_source import formula_relpath

MANIFEST = "manifest.json"
SECTIONS = {
    "built": ("name", "version", "relpath", "tarball", "json"),
    "failed": ("name", "version", "log"),
    "skipped": ("name", "reason"),
    "render_only": ("name", "relpath"),
}
SCALARS = ("core_commit", "tap_sha", "branch_date")


class ManifestError(RuntimeError):
    pass


def load(out: Path) -> dict:
    return json.loads((out / MANIFEST).read_text(encoding="utf-8"))


def _save(out: Path, document: dict) -> None:
    temporary = out / f"{MANIFEST}.tmp"
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(out / MANIFEST)


def init(out: Path, core_commit: str, tap_sha: str, branch_date: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    document = {"core_commit": core_commit, "tap_sha": tap_sha, "branch_date": branch_date}
    _save(out, document | {section: [] for section in SECTIONS})


def _append(out: Path, section: str, entry: dict) -> None:
    document = load(out)
    document[section].append(entry)
    _save(out, document)


def _copy_formula(out: Path, tap: Path, name: str) -> str:
    relpath = formula_relpath(name)
    (out / relpath).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tap / relpath, out / relpath)
    return relpath


def _only(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        msg = f"expected one {pattern} in {directory}, found {len(matches)}"
        raise ManifestError(msg)
    return matches[0]


def add_built(out: Path, tap: Path, name: str, version: str, bottle_dir: Path) -> None:
    bottle_json, tarball = _only(bottle_dir, "*.bottle.json"), _only(bottle_dir, "*.tar.gz")
    relpath = _copy_formula(out, tap, name)
    (out / "bottles").mkdir(exist_ok=True)
    for path in (bottle_json, tarball):
        shutil.move(path, out / "bottles" / path.name)
    entry = {"name": name, "version": version, "relpath": relpath}
    _append(out, "built", entry | {"tarball": tarball.name, "json": bottle_json.name})


def add_render_only(out: Path, tap: Path, name: str) -> None:
    _append(out, "render_only", {"name": name, "relpath": _copy_formula(out, tap, name)})


def rows(document: dict, section: str) -> list[str]:
    return ["\t".join(entry[key] for key in SECTIONS[section]) for entry in document[section]]


def _section(title: str, lines: list[str]) -> str:
    return f"\n## {title}\n\n" + "".join(f"- {line}\n" for line in lines or ["none"])


def summary(document: dict) -> str:
    built = [f"{entry['name']} {entry['version']}" for entry in document["built"]]
    failed = [f"{entry['name']} {entry['version']}: build failed" for entry in document["failed"]]
    skipped = [f"{entry['name']}: {entry['reason']}" for entry in document["skipped"]]
    updated = [entry["name"] for entry in document["render_only"]]
    text = f"Intel (Sequoia) bottles built from homebrew-core {document['core_commit']}.\n"
    text += _section("Built", built) + _section("Failed", failed) + _section("Skipped", skipped)
    return text + _section("Updated from core", updated)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    output = argparse.ArgumentParser(add_help=False)
    output.add_argument("out", type=Path, help="the builder output directory")
    start = commands.add_parser("init", parents=[output])
    for option in ("--core-commit", "--tap-sha", "--branch-date"):
        start.add_argument(option, required=True)
    for command, count, names in (
        ("built", 4, "TAP NAME VERSION BOTTLE_DIR"),
        ("render-only", 2, "TAP NAME"),
        ("failed", 2, "NAME VERSION"),
        ("skipped", 2, "NAME REASON"),
    ):
        commands.add_parser(command, parents=[output]).add_argument("fields", nargs=count, help=names)
    commands.add_parser("rows", parents=[output]).add_argument("section", choices=SECTIONS)
    commands.add_parser("field", parents=[output]).add_argument("key", choices=SCALARS)
    commands.add_parser("summary", parents=[output])
    return parser.parse_args(argv)


def write(args: argparse.Namespace) -> None:
    out, fields = args.out, getattr(args, "fields", [])
    if args.command == "init":
        init(out, args.core_commit, args.tap_sha, args.branch_date)
    elif args.command == "built":
        add_built(out, Path(fields[0]), fields[1], fields[2], Path(fields[3]))
    elif args.command == "render-only":
        add_render_only(out, Path(fields[0]), fields[1])
    elif args.command == "failed":
        _append(out, "failed", {"name": fields[0], "version": fields[1], "log": f"{fields[0]}.log"})
    else:
        _append(out, "skipped", {"name": fields[0], "reason": fields[1]})


def read(args: argparse.Namespace) -> None:
    document = load(args.out)
    if args.command == "rows":
        print("".join(f"{row}\n" for row in rows(document, args.section)), end="")
    elif args.command == "field":
        print(document[args.key])
    else:
        print(summary(document), end="")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        (read if args.command in ("rows", "field", "summary") else write)(args)
    except (ManifestError, OSError, KeyError, ValueError) as error:
        print(f"manifest: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
