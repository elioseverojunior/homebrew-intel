"""Fake brew and gh executables for builder script tests.

FakeBin writes `brew` and `gh` stubs into a temp directory and builds a PATH
of only that directory plus /usr/bin:/bin, so the real Homebrew can never be
reached. Each call appends one JSON line (tool, argv, cwd, HOMEBREW_* env and
GH_TOKEN) to a log. Rules in a JSON config decide what a call prints and how
it exits; the first rule whose argv is a prefix of the call wins, and unmatched
calls exit 0 silently. `brew bottle --json` also writes a bottle JSON and tarball in its cwd,
the way the real command does, with `filename` URL-encoded as brew encodes it.
A rule may sleep before answering, and each call that runs to completion
appends a second `{"done": argv}` line.

`FakeBin.serve_git(main_sha)` makes the `gh` stub emulate the few GitHub API
calls the publish scripts make, with branch heads kept in a state file: ref
reads, ref creation, `createCommitOnBranch` (stdin is logged, the head moves),
and compare. It fails like gh does ("Not Found") for unknown branches.
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

NOT_FOUND_BODY = (
    '{{"message":"Not Found","documentation_url":"https://docs.github.com/rest/git/refs#get-a-reference",'
    '"status":"404"}}'
)
REPO_API = "repos/elioseverojunior/homebrew-intel/"

LOG, CONFIG = {log!r}, {config!r}
tool, args = os.path.basename(sys.argv[0]), sys.argv[1:]
call = [tool, *args]
env = {{key: value for key, value in os.environ.items() if key.startswith("HOMEBREW_") or key == "GH_TOKEN"}}
stdin = sys.stdin.read() if "--input" in args else None
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"argv": call, "cwd": os.getcwd(), "env": env, "stdin": stdin}}) + "\\n")
config = json.loads(Path(CONFIG).read_text(encoding="utf-8"))


def serve_git():
    state_file = Path(CONFIG).with_name("git-state.json")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    heads, ahead = state["heads"], state["ahead"]
    path = args[1] if call[:2] == ["gh", "api"] and len(args) > 1 else ""
    sha = None
    if path.startswith(REPO_API + "git/ref/heads/"):
        sha = heads.get(path.removeprefix(REPO_API + "git/ref/heads/"))
    elif path.startswith(REPO_API + "compare/main..."):
        branch = path.removeprefix(REPO_API + "compare/main...")
        sha = str(ahead.get(branch, 0)) if branch in heads else None
    elif path == REPO_API + "git/refs":
        fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("-"))
        heads[fields["ref"].removeprefix("refs/heads/")] = fields["sha"]
        sha = ""
    elif path == "graphql":
        change = json.loads(stdin)["variables"]["input"]
        branch = change["branch"]["branchName"]
        if heads.get(branch) != change["expectedHeadOid"]:
            sys.stderr.write("gh: expectedHeadOid does not match\\n")
            sys.exit(1)
        ahead[branch] = ahead.get(branch, 0) + 1
        heads[branch] = f"commit{{ahead[branch]}}"
        sha = json.dumps({{"data": {{"createCommitOnBranch": {{"commit": {{"oid": heads[branch], "url": "u"}}}}}}}})
    elif call[:3] == ["gh", "pr", "create"]:
        sha = ""
    else:
        return
    state_file.write_text(json.dumps(state), encoding="utf-8")
    if sha is None:
        # Real gh prints the raw error body to stdout (no newline) and a summary to stderr.
        sys.stdout.write(NOT_FOUND_BODY)
        sys.stderr.write("gh: Not Found (HTTP 404)\\n")
        sys.exit(1)
    jq = args[args.index("--jq") + 1] if "--jq" in args else ""
    shown = json.dumps({{"object": {{"sha": sha}}}}) if path.startswith(REPO_API + "git/ref/") and not jq else sha
    sys.stdout.write(shown)
    sys.exit(0)


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
if rule is None and config.get("serve_git") and tool == "gh":
    serve_git()
rule = rule or {{"stdout": "", "exit": 0, "sleep": 0}}
time.sleep(rule["sleep"])
sys.stdout.write(rule["stdout"])
sys.stderr.write(rule.get("stderr", ""))
with open(LOG, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"done": call}}) + "\\n")
sys.exit(rule["exit"])
"""


class FakeBin:
    """Context manager owning the stub directory, its call log and its rules."""

    def __init__(self) -> None:
        self.rules: list[dict] = []
        self.serving_git = False

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

    def serve_git(self, main_sha: str = "mainsha", branches: dict[str, int] | None = None) -> None:
        """Emulate GitHub's ref, commit and compare endpoints; `branches` maps name to commits ahead."""
        ahead = dict(branches or {})
        heads = {"main": main_sha, **{branch: f"commit{count}" for branch, count in ahead.items()}}
        state = {"heads": heads, "ahead": ahead}
        (self.root / "git-state.json").write_text(json.dumps(state), encoding="utf-8")
        self.serving_git = True
        self._save()

    def git_state(self) -> dict:
        return json.loads((self.root / "git-state.json").read_text(encoding="utf-8"))

    def respond(self, *argv: str, stdout: str = "", stderr: str = "", exit_code: int = 0, sleep: float = 0) -> None:
        rule = {"argv": list(argv), "stdout": stdout, "stderr": stderr, "exit": exit_code, "sleep": sleep}
        self.rules.append(rule)
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
        document = {"rules": self.rules, "serve_git": self.serving_git}
        self.config.write_text(json.dumps(document), encoding="utf-8")
