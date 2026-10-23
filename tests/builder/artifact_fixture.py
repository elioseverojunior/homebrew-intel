"""A temp core repo, tap checkout and builder artifact that verify_artifact accepts.

ArtifactTestCase builds core (lz4, z3, llvm depending on z3), a tap checkout
committed with lz4 (bottled on main), and an artifact that bottles llvm and z3
(z3 only exists in the artifact, so llvm's dependency is qualified) and
re-renders lz4 as render-only with main's bottle block. The pins are what the
hosted jobs resolved: the core commit and the enabled closure (lz4, z3, llvm).
Tests then break one thing and expect verify_artifact to refuse.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from bottles import root_url
from render import render_formula
from transform import apply_bottle
from verify_artifact import Pins

from tests.tap.fixtures import CORE_FORMULAE, TAP_BOTTLE, git

TAP = "homebrew-intel/tap"


def bottle_block(name: str, version: str, sha: str, rebuild: int = 0) -> str:
    lines = [f'    root_url "{root_url(name, version)}"\n']
    lines += [f"    rebuild {rebuild}\n"] if rebuild else []
    lines += [f'    sha256 cellar: :any, sequoia: "{sha}"\n']
    return "  bottle do\n" + "".join(lines) + "  end\n"


def bottle_json(name: str, version: str, sha: str) -> dict:
    tag = {"filename": f"{name}-{version}.sequoia.bottle.tar.gz", "sha256": sha}
    tag["local_filename"] = f"{name}--{version}.sequoia.bottle.tar.gz"
    spec = {"root_url": root_url(name, version), "rebuild": 0, "tags": {"sequoia": tag}}
    return {f"{TAP}/{name}": {"formula": {"name": name}, "bottle": spec}}


class ArtifactTestCase(unittest.TestCase):
    def setUp(self):
        self.core, self.tap, self.out = (self.directory() for _ in range(3))
        self.git_init(self.core, CORE_FORMULAE)
        self.commit = git(self.core, "rev-parse", "HEAD")
        lz4 = apply_bottle(self.render("lz4", set()), TAP_BOTTLE)
        self.git_init(self.tap, {"Formula/l/lz4.rb": lz4, "enabled.toml": '[formula.lz4]\nkind = "generated"\n'})
        self.tap_sha = git(self.tap, "rev-parse", "HEAD")
        self.manifest = {"core_commit": self.commit, "tap_sha": self.tap_sha, "branch_date": "2026-10-22"}
        self.manifest |= {"built": [], "failed": [], "skipped": [], "render_only": []}
        names = {"lz4", "z3", "llvm"}
        for name in ("z3", "llvm"):
            self.add_built(name, self.render(name, names))
        self.write(self.out / "Formula/l/lz4.rb", apply_bottle(self.render("lz4", names), TAP_BOTTLE))
        self.manifest["render_only"].append({"name": "lz4", "relpath": "Formula/l/lz4.rb"})
        self.closure = {"lz4", "z3", "llvm"}
        self.save()

    def pins(self) -> Pins:
        return Pins(self.commit, frozenset(self.closure))

    def pin_arguments(self) -> list[str]:
        """verify_artifact.py's --artifact, --tap, --core-commit and --closure for the pins."""
        closure = self.out.parent / "closure.txt"
        closure.write_text("".join(f"{name}\n" for name in sorted(self.closure)), encoding="utf-8")
        locations = ["--artifact", str(self.out), "--tap", str(self.tap)]
        return [*locations, "--core-commit", self.commit, "--closure", str(closure)]

    def directory(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name).resolve()

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git_init(self, repo: Path, files: dict[str, str]) -> None:
        for relpath, text in files.items():
            self.write(repo / relpath, text)
        git(repo, "init", "-q")
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            git(repo, "config", key, value)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")

    def render(self, name: str, tap_names: set[str], commit: str | None = None, patch: str | None = None) -> str:
        commit = commit or self.commit
        source = git(self.core, "show", f"{commit}:Formula/{name[0]}/{name}.rb") + "\n"
        return render_formula(source, name=name, commit=commit, tap_names=tap_names, patch=patch, bottle_block=None)

    def add_built(self, name: str, body: str, version: str = "1.10.0") -> None:
        content = f"{name} bottle".encode()
        sha = hashlib.sha256(content).hexdigest()
        tarball, json_name = f"{name}-{version}.sequoia.bottle.tar.gz", f"{name}--{version}.sequoia.bottle.json"
        (self.out / "bottles").mkdir(exist_ok=True)
        (self.out / "bottles" / tarball).write_bytes(content)
        self.write(self.out / "bottles" / json_name, json.dumps(bottle_json(name, version, sha)))
        relpath = f"Formula/{name[0]}/{name}.rb"
        self.write(self.out / relpath, apply_bottle(body, bottle_block(name, version, sha)))
        entry = {"name": name, "version": version, "relpath": relpath, "tarball": tarball, "json": json_name}
        self.manifest["built"].append(entry)

    def save(self) -> None:
        self.write(self.out / "manifest.json", json.dumps(self.manifest))

    def entry(self, section: str, name: str) -> dict:
        return next(entry for entry in self.manifest[section] if entry["name"] == name)

    def edit(self, relpath: str, old: str, new: str) -> None:
        path = self.out / relpath
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
