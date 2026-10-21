"""List formulae and casks deleted from homebrew-core/cask and why, from git history."""

import argparse
import collections
import re
import subprocess

from brew_api import brew_repo, write_report

TAPS = {"formula": ("homebrew/core", "Formula"), "cask": ("homebrew/cask", "Casks")}
REASON_PATTERN = re.compile(r'(deprecate!|disable!)[^\n]*because: ("[^"]*"|:\w+)')
INTEL_PATTERN = re.compile(r"on_intel|arch: :intel|x86_64|rosetta|Support-Tiers", re.IGNORECASE)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False).stdout


def deletions(repo, directory, since):
    """Yield (commit, date, subject, path) for each deleted file under `directory`."""
    log = git(
        repo, "log", f"--since={since}", "--diff-filter=D", "--name-only", "--format=@@%h|%cs|%s", "--", directory
    )
    commit = None
    for line in log.splitlines():
        if line.startswith("@@"):
            commit = line[2:].split("|", 2)
        elif line:
            yield (*commit, line)


def describe(repo, kind, deletion):
    """Inspect the last version of a deleted file and summarize why it went away."""
    commit, date, subject, path = deletion
    source = git(repo, "show", f"{commit}^:{path}")
    name = path.rsplit("/", 1)[-1].removesuffix(".rb")
    added = git(repo, "show", "--diff-filter=A", "--name-only", "--format=", commit).split()
    return {
        "kind": kind,
        "name": name,
        "date": date,
        "commit": commit,
        "subject": subject,
        "moved": any(item.endswith(f"/{name}.rb") for item in added),
        "arm_only": "depends_on arch: :arm64" in source,
        "mentions_intel": bool(INTEL_PATTERN.search(source)),
        "reasons": [reason for _, reason in REASON_PATTERN.findall(source)],
    }


def build_rows(since):
    rows = []
    for kind, (tap, directory) in TAPS.items():
        repo = brew_repo(tap)
        rows += [describe(repo, kind, entry) for entry in deletions(repo, directory, since)]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2025-09-01", help="git --since date")
    parser.add_argument("--verbose", action="store_true", help="print reason counts")
    args = parser.parse_args()
    rows = build_rows(args.since)
    path = write_report("removed", rows)
    if args.verbose:
        print(collections.Counter((row["kind"], tuple(row["reasons"][:1])) for row in rows).most_common(20))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
