"""Shared fixtures for render and drift tests: a throwaway core repo and tap dir."""

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import render

BOTTLE = '  bottle do\n    sha256 cellar: :any, arm64_sequoia: "aaa"\n  end\n'
LZ4_ROOT_URL = "https://github.com/elioseverojunior/homebrew-intel/releases/download/lz4-1.10.0"
TAP_BOTTLE = f'  bottle do\n    root_url "{LZ4_ROOT_URL}"\n    sha256 cellar: :any, sequoia: "bbb"\n  end\n'


def formula(class_name: str, *dependencies: str) -> str:
    lines = [f"class {class_name} < Formula\n", '  desc "Test formula"\n', '  url "https://example.com/x.tar.gz"\n']
    lines.extend(["\n", BOTTLE, "\n"])
    lines.extend(f'  depends_on "{dependency}"\n' for dependency in dependencies)
    lines.extend(f"  # filler {index}\n" for index in range(10))
    lines.append('  def install\n    system "make"\n  end\nend\n')
    return "".join(lines)


CORE_FORMULAE = {
    "Formula/l/lz4.rb": formula("Lz4"),
    "Formula/z/z3.rb": formula("Z3"),
    "Formula/l/llvm.rb": formula("Llvm", "z3"),
}

UNBOTTLED = {"stable": {"files": {"arm64_sequoia": {}}}}
BOTTLED = {"stable": {"files": {"sequoia": {}}}}
VERSIONS = {"stable": "1.10.0"}
API = {
    "lz4": {"dependencies": [], "bottle": BOTTLED, "versions": VERSIONS},
    "z3": {"dependencies": [], "bottle": UNBOTTLED, "versions": VERSIONS},
    "llvm": {"dependencies": ["z3"], "bottle": BOTTLED, "versions": VERSIONS},
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


class TapTestCase(unittest.TestCase):
    """Creates self.core (a git repo with CORE_FORMULAE) and an empty self.tap dir."""

    def setUp(self):
        self.core = self.temporary_directory()
        self.tap = self.temporary_directory()
        git(self.core, "init", "-q")
        git(self.core, "config", "user.name", "Test")
        git(self.core, "config", "user.email", "test@example.com")
        git(self.core, "config", "commit.gpgsign", "false")
        for relpath, content in CORE_FORMULAE.items():
            self.write(self.core / relpath, content)
        git(self.core, "add", "-A")
        git(self.core, "commit", "-q", "-m", "first")
        self.first = git(self.core, "rev-parse", "HEAD")
        environment = mock.patch.dict(os.environ, {"HOMEBREW_CORE_REPO": str(self.core)})
        environment.start()
        self.addCleanup(environment.stop)

    def temporary_directory(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    @staticmethod
    def write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def enable(self, toml: str) -> None:
        self.write(self.tap / "enabled.toml", toml)

    def read(self, relpath: str) -> str:
        return (self.tap / relpath).read_text(encoding="utf-8")

    def tree(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.tap)): path.read_text(encoding="utf-8")
            for path in sorted(self.tap.rglob("*"))
            if path.is_file()
        }


class RenderTestCase(TapTestCase):
    def run_render(self, *argv: str, api: dict | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(render, "TAP_ROOT", self.tap),
            mock.patch.object(render, "load_formulae", return_value=API if api is None else api),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = render.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()
