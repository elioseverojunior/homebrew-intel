"""Decide whether a pull request is a verified bot bottle PR that may auto-merge.

A bot PR passes only when it comes from the builder's GitHub App on a
same-repository `bottle/<YYYY-MM-DD>-<run>` branch, every commit is verified
and was made through the API (author the bot, committer web-flow), and it only
touches `Formula/`. Pull requests by anyone else are skipped with exit 0: they
still need the owner to merge, since only the builder enables auto-merge.

Usage: verify_bot_pr.py --event EVENT_JSON --commits COMMITS --files FILES,
where COMMITS and FILES are the raw output of `gh api --paginate` (one JSON
array per page, concatenated).
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

BOT_LOGIN = "elios-automator[bot]"
COMMITTER_LOGIN = "web-flow"
FORMULA_DIRECTORY = "Formula/"
BRANCH_PATTERN = re.compile(r"bottle/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+")


def _login(user: Mapping | None) -> str | None:
    return (user or {}).get("login")


def is_bot_pr(pull_request: Mapping) -> bool:
    return _login(pull_request.get("user")) == BOT_LOGIN


def _origin_problems(pull_request: Mapping) -> list[str]:
    problems = []
    author_type = (pull_request.get("user") or {}).get("type")
    if author_type != "Bot":
        problems.append(f"author type is '{author_type}', not Bot")
    base = (pull_request["base"].get("repo") or {}).get("full_name")
    head = (pull_request["head"].get("repo") or {}).get("full_name")
    if head != base:
        problems.append(f"head repository '{head}' is not {base}")
    ref = pull_request["head"].get("ref")
    if not BRANCH_PATTERN.fullmatch(ref or ""):
        problems.append(f"head ref '{ref}' is not bottle/<YYYY-MM-DD>-<run>")
    return problems


def _commit_problems(commit: Mapping) -> list[str]:
    label = f"commit {commit['sha'][:12]}"
    problems = []
    verification = commit["commit"].get("verification") or {}
    if verification.get("verified") is not True:
        problems.append(f"{label} is not verified ({verification.get('reason')})")
    if (author := _login(commit.get("author"))) != BOT_LOGIN:
        problems.append(f"{label} author is '{author}', not {BOT_LOGIN}")
    if (committer := _login(commit.get("committer"))) != COMMITTER_LOGIN:
        problems.append(f"{label} committer is '{committer}', not {COMMITTER_LOGIN}")
    return problems


def _file_problems(changed: Mapping) -> list[str]:
    paths = (changed["filename"], changed.get("previous_filename") or changed["filename"])
    outside = dict.fromkeys(path for path in paths if not path.startswith(FORMULA_DIRECTORY))
    return [f"file '{path}' is outside {FORMULA_DIRECTORY}" for path in outside]


def problems(pull_request: Mapping, commits: Sequence[Mapping], files: Sequence[Mapping]) -> list[str]:
    """Every reason the bot pull request must not auto-merge; empty when it may."""
    found = _origin_problems(pull_request)
    if not commits:
        found.append("pull request has no commits")
    if not files:
        found.append("pull request changes no files")
    for commit in commits:
        found += _commit_problems(commit)
    for changed in files:
        found += _file_problems(changed)
    return found


def load_pages(text: str) -> list:
    """Flatten the concatenated JSON arrays `gh api --paginate` prints."""
    decoder, items, rest = json.JSONDecoder(), [], text.strip()
    while rest:
        page, end = decoder.raw_decode(rest)
        items += page
        rest = rest[end:].lstrip()
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for option in ("--event", "--commits", "--files"):
        parser.add_argument(option, type=Path, required=True)
    args = parser.parse_args(argv)
    pull_request = json.loads(args.event.read_text(encoding="utf-8"))["pull_request"]
    number = pull_request["number"]
    if not is_bot_pr(pull_request):
        print(f"pull request #{number} is not a bot PR — skipped")
        return 0
    commits = load_pages(args.commits.read_text(encoding="utf-8"))
    files = load_pages(args.files.read_text(encoding="utf-8"))
    found = problems(pull_request, commits, files)
    for problem in found:
        print(f"verify-bot-pr: {problem}", file=sys.stderr)
    if found:
        print(f"pull request #{number} must not auto-merge", file=sys.stderr)
        return 1
    print(f"pull request #{number} is a verified bot bottle PR ({len(commits)} commits, {len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
