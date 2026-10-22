"""Reader for formulae in the local homebrew-core clone, pinned by commit."""

import os
import subprocess
from pathlib import Path


class CoreSourceError(RuntimeError):
    pass


def formula_relpath(name: str) -> str:
    shard = "lib" if name.startswith("lib") else name[0]
    return f"Formula/{shard}/{name}.rb"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def core_repo() -> Path:
    override = os.environ.get("HOMEBREW_CORE_REPO")
    if override:
        return Path(override)
    result = subprocess.run(
        ["brew", "--repo", "homebrew/core"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = f"brew --repo homebrew/core failed: {result.stderr.strip()}"
        raise CoreSourceError(msg)
    return Path(result.stdout.strip())


def head_commit(repo: Path) -> str:
    result = _git(repo, "rev-parse", "HEAD")
    if result.returncode != 0:
        msg = f"{repo}: cannot resolve HEAD: {result.stderr.strip()}"
        raise CoreSourceError(msg)
    return result.stdout.strip()


def read_formula(repo: Path, name: str, commit: str) -> str:
    if _git(repo, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        msg = f"commit {commit} not in {repo}; run: git -C {repo} fetch origin"
        raise CoreSourceError(msg)
    result = _git(repo, "show", f"{commit}:{formula_relpath(name)}")
    if result.returncode != 0:
        msg = f"{name}: {formula_relpath(name)} not found at core commit {commit}"
        raise CoreSourceError(msg)
    return result.stdout
