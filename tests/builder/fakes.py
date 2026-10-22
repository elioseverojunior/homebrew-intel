"""Fake brew and gh executables for builder script tests.

FakeBin writes `brew` and `gh` stubs into a temp directory and builds a PATH
of only that directory plus /usr/bin:/bin, so the real Homebrew can never be
reached. Each call appends one JSON line (tool, argv, cwd, HOMEBREW_* env) to
a log. Rules in a JSON config decide what a call prints and how it exits; the
first rule whose argv is a prefix of the call wins, and unmatched calls exit 0
silently. `brew bottle --json` also writes a bottle JSON and tarball in its cwd,
the way the real command does, with `filename` URL-encoded as brew encodes it.
A rule may sleep before answering, and each call that runs to completion
appends a second `{"done": argv}` line.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Self

STUB = """#!{python}
import json, os, sys, time
from pathlib import Path
from urllib.parse import quote

LOG, CONFIG = {log!r}, {config!r}
tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]
call = [tool, *args]
env = {{key: value for key, value in os.environ.items() if key.startswith("HOMEBREW_")}}
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": call, "cwd": os.getcwd(), "env": env}}) + "\\n")
config = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
if call[:2] == ["brew", "bottle"] and "--json" in args and "--merge" not in args:
    name = args[-1].rsplit("/", 1)[-1]
    root_url = next(arg for arg in args if arg.startswith("--root-url="))
    version = root_url.rsplit("/", 1)[-1][len(name) + 1 :]
    local, final = f"{{name}}--{{version}}.sequoia.bottle.tar.gz", f"{{name}}-{{version}}.sequoia.bottle.tar.gz"
    Path(local).write_bytes(b"bottle")
    tag = {{"filename": quote(final, safe=""), "local_filename": local}}
    document = {{f"elioseverojunior/intel/{{name}}": {{"bottle": {{"tags": {{"sequoia": tag}}}}}}}}
    Path(f"{{name}}--{{version}}.sequoia.bottle.json").write_text(json.dumps(document), encoding="utf-8")
rule = next((r for r in config["rules"] if call[: len(r["argv"])] == r["argv"]), None)
rule = rule or {{"stdout": "", "exit": 0, "sleep": 0}}
time.sleep(rule["sleep"])
sys.stdout.write(rule["stdout"])
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"done": call}}) + "\\n")
sys.exit(rule["exit"])
"""


class FakeBin:
    """Context manager owning the stub directory, its call log and its rules."""

    def __init__(self) -> None:
        self.rules: list[dict] = []

    def __enter__(self) -> Self:
        self.root = Path(tempfile.mkdtemp())
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.jsonl"
        self.log.touch()
        self.config = self.root / "config.json"
        self._save()
        stub = STUB.format(python=sys.executable, log=str(self.log), config=str(self.config))
        for tool in ("brew", "gh"):
            path = self.bin / tool
            path.write_text(stub, encoding="utf-8")
            path.chmod(0o755)
        (self.bin / "python3").symlink_to(sys.executable)
        return self

    def __exit__(self, *_exc: object) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def respond(self, *argv: str, stdout: str = "", exit_code: int = 0, sleep: float = 0) -> None:
        self.rules.append({"argv": list(argv), "stdout": stdout, "exit": exit_code, "sleep": sleep})
        self._save()

    def fail(self, *argv: str) -> None:
        self.respond(*argv, exit_code=1)

    def calls(self) -> list[dict]:
        return [entry for entry in self._entries() if "argv" in entry]

    def finished(self) -> list[list[str]]:
        """Argv of the calls that ran to completion (not killed mid-call)."""
        return [entry["done"] for entry in self._entries() if "done" in entry]

    def _entries(self) -> list[dict]:
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def argvs(self) -> list[list[str]]:
        return [call["argv"] for call in self.calls()]

    def environment(self) -> dict[str, str]:
        base = {key: value for key, value in os.environ.items() if not key.startswith("HOMEBREW_")}
        return {**base, "PATH": f"{self.bin}:/usr/bin:/bin"}

    def _save(self) -> None:
        document = {"rules": self.rules}
        self.config.write_text(json.dumps(document), encoding="utf-8")
