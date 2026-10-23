"""Decide whether a pull request is a verified bot bottle PR that may auto-merge.

A bot PR passes only when it comes from the builder's GitHub App on a
same-repository `bottle/<YYYY-MM-DD>-<run>` branch into `main`, and its head
commit carries a successful `bottle-builder` check run created by that App
(its id and slug) whose `head_sha` and `external_id` both name that commit.
The check run is the trust anchor: commit author, committer and verification can be forged by
anyone with write access, but only the App can create its own check runs, and
any later push moves the head to a commit without one. The commit checks stay
as an extra layer. The PR must only touch `Formula/`, and the fetched commit
and file lists must match the event's counts (and stay below the API listing
limits) so a truncated listing cannot pass. Pull requests by anyone else are
skipped with exit 0: they still need the owner to merge, since only the
builder enables auto-merge. Status checks belong to a commit, not a pull
request, so such a skip would also turn the gate green for every pull request
on the same head; a pull request that is not the bot's therefore fails when its
head carries any `bottle-builder` check run or is the head of another open
same-repository `bottle/*` pull request.

Usage: verify_bot_pr.py --event EVENT_JSON --commits COMMITS --files FILES
--check-runs CHECK_RUNS --open-pulls OPEN_PULLS, where the last four are the
output of `gh api --paginate` (one JSON array per page, concatenated; check
runs as `--jq .check_runs`, open pulls from `pulls?state=open`).
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

BOT_LOGIN = "homebrew-intel[bot]"
APP_SLUG = "homebrew-intel"
# The App's numeric id never changes or moves to another App; the slug is kept
# as a second condition.
APP_ID = 5443354
CHECK_NAME = "bottle-builder"
# GitHub lists at most this many commits / files of a pull request.
COMMIT_LIMIT = 250
FILE_LIMIT = 3000
COMMITTER_LOGIN = "web-flow"
BASE_REF = "main"
FORMULA_DIRECTORY = "Formula/"
BRANCH_PATTERN = re.compile(r"bottle/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+")


class Evidence(NamedTuple):
    """What the GitHub API returned for the pull request."""

    commits: Sequence[Mapping]
    files: Sequence[Mapping]
    check_runs: Sequence[Mapping]


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
    if (base_ref := pull_request["base"].get("ref")) != BASE_REF:
        problems.append(f"base ref '{base_ref}' is not {BASE_REF}")
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


def _built_by_the_app(check_run: Mapping, head_sha: str) -> bool:
    return (
        check_run.get("name") == CHECK_NAME
        and (check_run.get("app") or {}).get("id") == APP_ID
        and (check_run.get("app") or {}).get("slug") == APP_SLUG
        and check_run.get("conclusion") == "success"
        and check_run.get("head_sha") == head_sha
        and check_run.get("external_id") == head_sha
    )


def _anchor_problems(pull_request: Mapping, check_runs: Sequence[Mapping]) -> list[str]:
    head_sha = pull_request["head"]["sha"]
    if any(_built_by_the_app(check_run, head_sha) for check_run in check_runs):
        return []
    return [f"head {head_sha[:12]} has no successful {CHECK_NAME} check run from {APP_SLUG}"]


def _bottle_branch_pull(pull: Mapping, base: str | None) -> bool:
    head = pull.get("head") or {}
    return (head.get("repo") or {}).get("full_name") == base and bool(BRANCH_PATTERN.fullmatch(head.get("ref") or ""))


def impersonation_problems(
    pull_request: Mapping, check_runs: Sequence[Mapping], open_pulls: Sequence[Mapping]
) -> list[str]:
    """Why a pull request that is not the bot's must fail rather than skip; empty when it may skip."""
    head_sha, base = pull_request["head"]["sha"], (pull_request["base"].get("repo") or {}).get("full_name")
    found = []
    if any(check_run.get("name") == CHECK_NAME for check_run in check_runs):
        found.append(f"head {head_sha[:12]} carries a {CHECK_NAME} check run, but the pull request is not the bot's")
    for pull in open_pulls:
        twin = pull.get("number") != pull_request["number"] and (pull.get("head") or {}).get("sha") == head_sha
        if twin and _bottle_branch_pull(pull, base):
            found.append(f"head {head_sha[:12]} is the head of bot branch pull request #{pull['number']}")
    return found


def _count_problems(kind: str, fetched: int, expected: int, limit: int) -> list[str]:
    problems = []
    if fetched != expected:
        problems.append(f"fetched {fetched} {kind}, but the pull request has {expected}")
    if fetched >= limit:
        problems.append(f"{fetched} {kind} reach the API listing limit of {limit}")
    return problems


def problems(pull_request: Mapping, evidence: Evidence) -> list[str]:
    """Every reason the bot pull request must not auto-merge; empty when it may."""
    found = _origin_problems(pull_request) + _anchor_problems(pull_request, evidence.check_runs)
    found += _count_problems("commits", len(evidence.commits), pull_request["commits"], COMMIT_LIMIT)
    found += _count_problems("files", len(evidence.files), pull_request["changed_files"], FILE_LIMIT)
    if not evidence.commits:
        found.append("pull request has no commits")
    if not evidence.files:
        found.append("pull request changes no files")
    for commit in evidence.commits:
        found += _commit_problems(commit)
    for changed in evidence.files:
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
    for option in ("--event", "--commits", "--files", "--check-runs", "--open-pulls"):
        parser.add_argument(option, type=Path, required=True)
    args = parser.parse_args(argv)
    pull_request = json.loads(args.event.read_text(encoding="utf-8"))["pull_request"]
    number = pull_request["number"]
    pages = (load_pages(path.read_text(encoding="utf-8")) for path in (args.commits, args.files, args.check_runs))
    evidence = Evidence(*pages)
    if is_bot_pr(pull_request):
        found = problems(pull_request, evidence)
    else:
        open_pulls = load_pages(args.open_pulls.read_text(encoding="utf-8"))
        found = impersonation_problems(pull_request, evidence.check_runs, open_pulls)
        if not found:
            print(f"pull request #{number} is not a bot PR — skipped")
            return 0
    for problem in found:
        print(f"verify-bot-pr: {problem}", file=sys.stderr)
    if found:
        print(f"pull request #{number} must not auto-merge", file=sys.stderr)
        return 1
    counts = f"{len(evidence.commits)} commits, {len(evidence.files)} files"
    print(f"pull request #{number} is a verified bot bottle PR ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
