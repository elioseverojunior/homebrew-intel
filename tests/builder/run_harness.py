"""Shared harness for run.sh tests: script stubs, a temp tap and core repo."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.builder.fakes import FakeBin

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "builder" / "run.sh"
STUBBED = (
    "scripts/audit/fetch-api.sh",
    "scripts/tap/plan.py",
    "scripts/tap/render.py",
    "scripts/builder/build-formula.sh",
    "scripts/builder/pour-formula.sh",
)

# One stub stands in for every script run.sh calls. Each call is logged with
# where the Taps symlink pointed at that moment; stubs.json decides the plan,
# the files render.py rewrites, and which builds fail, stall or leave no bottle.
# A successful build-formula.sh writes a bottle JSON and tarball into its
# out-dir and rewrites the formula, the way `brew bottle --merge --write` does.
STUB = """#!{python}
import json, os, sys, time
from pathlib import Path

root = Path({root!r})
config = json.loads((root / "stubs.json").read_text(encoding="utf-8"))
script, args = os.path.basename(sys.argv[0]), sys.argv[1:]
link = root / "Taps" / "homebrew-tap"


def formula_relpath(name):
    return f"Formula/{{'lib' if name.startswith('lib') else name[0]}}/{{name}}.rb"


def write_bottle(name, version, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{{name}}--{{version}}.sequoia.bottle.json").write_text("{{}}", encoding="utf-8")
    (out / f"{{name}}-{{version}}.sequoia.bottle.tar.gz").write_bytes(b"bottle")
    formula = Path(os.environ["TAP_DIR"]) / formula_relpath(name)
    formula.parent.mkdir(parents=True, exist_ok=True)
    formula.write_text(f"bottled {{name}}\\n", encoding="utf-8")


names = ("TAP_DIR", "HOMEBREW_INTEL_DATA", "HOMEBREW_CORE_REPO")
entry = {{
    "script": script,
    "argv": args,
    "link": os.readlink(link) if link.is_symlink() else None,
    "saved": (root / "cache" / "taps-link-target").is_file(),
    "env": {{name: os.environ.get(name) for name in names}},
}}
with open(root / "stubs.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps(entry) + "\\n")
if script == "plan.py":
    print(config["commit"] if args[0] == "commit" else config["plan"], end="")
elif script == "render.py":
    for relpath, text in config["render"].items():
        path = Path(os.environ["TAP_DIR"]) / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
elif script == "build-formula.sh":
    print(f"building {{args[0]}}", flush=True)
    built = Path(os.environ["TAP_DIR"]) / formula_relpath(args[0])
    if built.is_file():
        print(f"formula header: {{built.read_text(encoding='utf-8').splitlines()[0]}}", flush=True)
    if args[0] in config.get("drain", []):
        sys.stdin.read()
    time.sleep(config["sleep"].get(args[0], 0))
    if args[0] in config["fail"]:
        print(f"error: {{args[0]}} does not compile")
        sys.exit(1)
    if args[0] not in config.get("no_bottle", []):
        write_bottle(*args)
elif script == "pour-formula.sh":
    time.sleep(config["sleep"].get(args[0], 0))
    sys.exit(1 if args[0] in config["fail"] else 0)
"""


def git(*args: str) -> str:
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    result = subprocess.run(["git", *identity, *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def make_repo(path: Path, files: dict[str, str]) -> str:
    for relpath, text in files.items():
        (path / relpath).parent.mkdir(parents=True, exist_ok=True)
        (path / relpath).write_text(text, encoding="utf-8")
    git("init", "-q", "-b", "main", str(path))
    git("-C", str(path), "add", ".")
    git("-C", str(path), "commit", "-q", "-m", "init")
    return git("-C", str(path), "rev-parse", "HEAD")


class RunTest(unittest.TestCase):
    def setUp(self):
        self.fake = self.enterContext(FakeBin())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.tap = self.root / "tap"
        make_repo(self.tap, {"Formula/l/lz4.rb": "# header a\nlz4\n", "Formula/z/z3.rb": "# header a\nz3\n"})
        # actions/checkout fetches main as origin/main but creates no origin/HEAD.
        git("-C", str(self.tap), "update-ref", "refs/remotes/origin/main", "HEAD")
        self.write_stubs()
        self.core_commit = make_repo(self.root / "core", {"Formula/l/lz4.rb": "core lz4\n"})
        self.original = self.root / "original"
        self.original.mkdir()
        (self.root / "Taps").mkdir()
        self.link = self.root / "Taps" / "homebrew-tap"
        self.link.symlink_to(self.original)
        self.configure(plan="")

    def write_stubs(self) -> None:
        stub = STUB.format(python=sys.executable, root=str(self.root))
        for relpath in STUBBED:
            path = self.tap / relpath
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(stub, encoding="utf-8")
            path.chmod(0o755)

    def configure(self, plan: str, fail: tuple[str, ...] = (), **extra: object) -> None:
        config = {"commit": self.core_commit, "plan": plan, "fail": list(fail), "render": {}, "sleep": {}}
        (self.root / "stubs.json").write_text(json.dumps({**config, **extra}), encoding="utf-8")

    def environment(self, **extra: str) -> dict[str, str]:
        env = {
            **self.fake.environment(),
            "TAP_DIR": str(self.tap),
            "TAPS_LINK": str(self.link),
            "BUILDER_CACHE": str(self.root / "cache"),
            "BUILDER_CORE_URL": str(self.root / "core"),
        }
        for secret in ("GH_TOKEN", "GITHUB_TOKEN", "PRIVATE_GH_TOKEN"):
            env.pop(secret, None)
        return {**env, **extra}

    def run_bare(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        argv = ["bash", str(SCRIPT), *args]
        return subprocess.run(argv, env=self.environment(**extra), capture_output=True, text=True, check=False)

    def run_script(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return self.run_bare("--build-only", *args, **extra)

    def stub_calls(self, script: str | None = None) -> list[dict]:
        log = self.root / "stubs.jsonl"
        entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        return [entry for entry in entries if script in (None, entry["script"])]

    def stub_argvs(self, script: str) -> list[list[str]]:
        return [entry["argv"] for entry in self.stub_calls(script)]

    def built(self) -> list[str]:
        return [argv[0] for argv in self.stub_argvs("build-formula.sh")]

    @property
    def out(self) -> Path:
        return self.tap / ".builder" / "out"

    def manifest(self) -> dict:
        return json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))

    def section(self, name: str) -> list[str]:
        return [entry["name"] for entry in self.manifest()[name]]

    @property
    def saved_target(self) -> Path:
        return self.root / "cache" / "taps-link-target"

    def assert_link_restored(self) -> None:
        self.assertEqual(self.link.readlink(), self.original)
