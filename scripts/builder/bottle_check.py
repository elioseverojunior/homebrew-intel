"""Check one built formula's bottle block, bottle JSON and tarball against each other.

Part of verify_artifact.py's trust boundary. syntax_problems() is the strict
grammar every bottle block must pass before anything else, since the core
identity check strips the block and could not see code hidden in it: only
the lines brew writes (a root_url under this tap's releases, an optional
rebuild, sha256 lines for sequoia or tahoe with a known cellar), nothing else.
problems() then checks a built formula's block in full. It must be exactly what
`brew bottle --merge --write` writes for a single Sequoia bottle: a root_url
equal to this tap's release URL, an optional rebuild and one sequoia sha256
line with a known cellar, nothing else (a cellar string could interpolate Ruby).
Its sha256 must be the tarball's and the JSON's, and the file names must be
the ones brew derives from name, version and rebuild.
"""

import hashlib
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tap"))
from bottles import ROOT_URL_BASE, root_url
from transform import TAP

_CELLAR = r'(?:cellar: (?::any|:any_skip_relocation|"/usr/local/Cellar"), +)?'
SYNTAX = re.compile(
    r"  bottle do\n"
    rf'    root_url "{re.escape(ROOT_URL_BASE)}/[a-z0-9][A-Za-z0-9@._+-]*"\n'
    r"(?:    rebuild [1-9][0-9]*\n)?"
    rf'(?:    sha256 {_CELLAR}(?:sequoia|tahoe): +"[0-9a-f]{{64}}"\n)+'
    r"  end\n",
)
BLOCK = re.compile(
    r"  bottle do\n"
    r'    root_url "(?P<root_url>[^"\\#\n]+)"\n'
    r"(?:    rebuild (?P<rebuild>[1-9][0-9]*)\n)?"
    r'    sha256 (?:cellar: (?::any|:any_skip_relocation|"/usr/local/Cellar"), +)?'
    r'sequoia: +"(?P<sha256>[0-9a-f]{64})"\n'
    r"  end\n",
)
MALFORMED = (KeyError, TypeError, AttributeError, ValueError)


class Bottle(NamedTuple):
    """A built manifest entry: the tarball path and the bottle JSON's file name."""

    name: str
    version: str
    tarball: Path
    json_name: str


def tarball_name(name: str, version: str, rebuild: int) -> str:
    suffix = f".{rebuild}" if rebuild else ""
    return f"{name}-{version}.sequoia.bottle{suffix}.tar.gz"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_problems(bottle: Bottle, rebuild: int, sha: str) -> list[str]:
    problems = []
    if bottle.tarball.name != (expected := tarball_name(bottle.name, bottle.version, rebuild)):
        problems.append(f"tarball {bottle.tarball.name} is not {expected}")
    if bottle.json_name != (expected := f"{bottle.name}--{bottle.version}.sequoia.bottle.json"):
        problems.append(f"bottle JSON {bottle.json_name} is not {expected}")
    if _sha256(bottle.tarball) != sha:
        problems.append(f"bottle block sha256 {sha} does not match the tarball")
    return problems


def _json_problems(document: Mapping, bottle: Bottle, rebuild: int, sha: str) -> list[str]:
    key = f"{TAP}/{bottle.name}"
    if list(document) != [key]:
        return [f"bottle JSON is not for {key} alone"]
    spec = document[key]["bottle"]
    if list(spec["tags"]) != ["sequoia"]:
        return [f"bottle JSON tags are {sorted(spec['tags'])}, not sequoia alone"]
    tag, problems = spec["tags"]["sequoia"], []
    if tag["sha256"] != sha:
        problems.append(f"bottle JSON sha256 {tag['sha256']} is not the block's {sha}")
    if unquote(tag["filename"]) != bottle.tarball.name:
        problems.append(f"bottle JSON filename {tag['filename']} is not {bottle.tarball.name}")
    if spec.get("rebuild", 0) != rebuild or spec["root_url"] != root_url(bottle.name, bottle.version):
        problems.append("bottle JSON rebuild or root_url differs from the block")
    return problems


def syntax_problems(block: str) -> list[str]:
    """Empty when the block holds only lines brew writes for this tap."""
    return [] if SYNTAX.fullmatch(block) else ["bottle block has a line brew does not write"]


def problems(block: str, document: object, bottle: Bottle) -> list[str]:
    """Every reason the bottle block, JSON and tarball do not agree; empty when they do."""
    match = BLOCK.fullmatch(block)
    if match is None:
        return ["bottle block has lines other than root_url, rebuild and one sequoia sha256"]
    expected_url = root_url(bottle.name, bottle.version)
    found = [] if match["root_url"] == expected_url else [f"bottle block root_url is not {expected_url}"]
    rebuild, sha = int(match["rebuild"] or 0), match["sha256"]
    found += _file_problems(bottle, rebuild, sha)
    try:
        found += _json_problems(document, bottle, rebuild, sha)  # type: ignore[arg-type]
    except MALFORMED as error:
        found.append(f"malformed bottle JSON: {error!r}")
    return found
