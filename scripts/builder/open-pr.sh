#!/usr/bin/env bash

set -Eeuo pipefail

# Open the run's pull request for its bottle branch:
#   open-pr.sh <branch> <expected-head-sha> <summary-file>
# Env: GH_TOKEN (App token). The title comes from the branch name
# (bottle/<date>-<run>), so a run that crosses midnight stays consistent. Does
# nothing when the branch is missing or has no commits ahead of main.
# <expected-head-sha> is the last commit this run created. Only when the
# remote branch head is exactly that commit does the script attest it with a
# successful `bottle-builder` check run whose external_id is that commit too
# (the trust anchor of verify-bot-pr) and enable squash auto-merge bound to
# that commit (--match-head-commit), on a new or an already open bot pull
# request (same repository, authored by the App; anyone else's pull request on
# a branch of the same name is ignored). Auto-merge is enabled only while
# main's ruleset requires the verify-bot-pr check from GitHub Actions
# (integration id 15368). A foreign head gets neither:
# the pull request is still opened (or left open) for the owner, and the
# script exits 1 so the run reports it. A failure to create the check run, a
# missing ruleset or a failure to enable auto-merge only warns; the owner then
# merges by hand.

readonly REPO="homebrew-intel/homebrew-tap"
readonly CHECK_NAME="bottle-builder"
readonly GATE_CHECK="verify-bot-pr"
# GitHub Actions' App id: the required check must come from a workflow run, so
# no other App or commit status can satisfy it.
readonly GATE_INTEGRATION_ID=15368
readonly BOT_AUTHOR="app/homebrew-intel"
readonly OWNER="homebrew-intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/gh-lookup.sh
source "${script_dir}/gh-lookup.sh"

log() {
  echo "open-pr: $*" >&2
}

validate_arguments() {
  if [[ $# -ne 3 ]]
  then
    log "usage: open-pr.sh <branch> <expected-head-sha> <summary-file>"
    exit 2
  fi
  if [[ ! "$1" =~ ^bottle/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+$ ]]
  then
    log "invalid branch: '$1'"
    exit 2
  fi
  if [[ ! "$2" =~ ^[0-9a-f]{40}$ ]]
  then
    log "invalid expected head sha: '$2'"
    exit 2
  fi
  if [[ ! -f "$3" ]]
  then
    log "summary file missing: '$3'"
    exit 2
  fi
}

# Prints the number of commits the branch is ahead of main; 0 if it is missing.
commits_ahead() {
  local ahead
  # shellcheck disable=SC2310 # gh_lookup captures and returns its own status; || return passes it on
  ahead="$(gh_lookup "repos/${REPO}/compare/main...$1" --jq .ahead_by)" || return $?
  echo "${ahead:-0}"
}

# Prints the number of the open bot pull request for the branch, if any: same
# repository, authored by the App. A failed lookup prints nothing.
# shellcheck disable=SC2312 # a failed list reads as none: gh pr create refuses a duplicate itself
bot_pull_request() {
  gh pr list -R "${REPO}" --head "$1" --state open --json number,headRepositoryOwner,author 2>/dev/null |
    python3 -c '
import json, sys
owner, author = sys.argv[1:]
pulls = json.loads(sys.stdin.read().strip() or "[]")
ours = [p["number"] for p in pulls if p["headRepositoryOwner"]["login"] == owner and p["author"]["login"] == author]
print(*ours[:1])
' "${OWNER}" "${BOT_AUTHOR}"
}

# Succeeds when main's rules require the verify-bot-pr check from GitHub
# Actions, without which an auto-merge would wait for nothing but the other
# checks (or for a check anyone could report).
gate_is_required() {
  local rules
  rules="$(gh api "repos/${REPO}/rules/branches/main" 2>/dev/null)" || return 1
  python3 -c '
import json, sys
rules, context, integration = json.loads(sys.argv[1]), sys.argv[2], int(sys.argv[3])
checks = [(c.get("context"), c.get("integration_id")) for r in rules if r.get("type") == "required_status_checks"
          for c in (r.get("parameters") or {}).get("required_status_checks") or []]
sys.exit(0 if (context, integration) in checks else 1)
' "${rules}" "${GATE_CHECK}" "${GATE_INTEGRATION_ID}"
}

# Succeeds when the remote branch head is the expected commit.
head_is_expected() {
  local branch="$1" expected="$2" head
  head="$(gh api "repos/${REPO}/git/ref/heads/${branch}" --jq .object.sha)"
  [[ "${head}" = "${expected}" ]] && return 0
  log "warning: ${branch} head ${head} is not the builder's ${expected}; no check run, no auto-merge"
  return 1
}

create_check_run() {
  gh api "repos/${REPO}/check-runs" -f "name=${CHECK_NAME}" -f "head_sha=$1" -f "external_id=$1" \
    -f status=completed -f conclusion=success -f "output[title]=Intel bottle builder" \
    -f "output[summary]=Bottles built and committed by the private Intel builder." >/dev/null
}

# Attests the commit; a failure only warns (verify-bot-pr then fails and
# auto-merge waits for the owner).
attest_head() {
  # shellcheck disable=SC2310 # a failed check run only warns
  if create_check_run "$1"
  then
    log "marked $1 with the ${CHECK_NAME} check run"
    return 0
  fi
  log "warning: could not create the ${CHECK_NAME} check run on $1; verify-bot-pr will block auto-merge"
}

# enable_auto_merge <selector> <expected-head>: squash auto-merge, only of that
# head and only while the gate is required; a failure (e.g. the repository
# setting is off) only warns.
enable_auto_merge() {
  # shellcheck disable=SC2310 # a missing gate only warns
  if ! gate_is_required
  then
    log "warning: main's ruleset does not require ${GATE_CHECK}; auto-merge not enabled on $1"
    return 0
  fi
  if ! gh pr merge "$1" --auto --squash --match-head-commit "$2" -R "${REPO}"
  then
    log "warning: could not enable auto-merge on $1; merge it by hand"
  fi
}

# Prints the new pull request's URL.
create_pull_request() {
  local branch="$1" summary="$2" title="${1#bottle/}"
  gh pr create -R "${REPO}" --base main --head "${branch}" \
    --title "bottles: ${title:0:10} run ${title:11}" --body-file "${summary}"
}

main() {
  validate_arguments "$@"
  local branch="$1" expected="$2" summary="$3" ahead trusted=yes selector
  ahead="$(commits_ahead "${branch}")"
  if [[ "${ahead}" -eq 0 ]]
  then
    log "nothing to open: ${branch} is missing or has no commits ahead of main"
    return 0
  fi
  # shellcheck disable=SC2310 # the mismatch is reported, then the PR still opens
  head_is_expected "${branch}" "${expected}" || trusted=no
  [[ "${trusted}" = no ]] || attest_head "${expected}"
  selector="$(bot_pull_request "${branch}")"
  if [[ -n "${selector}" ]]
  then
    log "bot pull request #${selector} for ${branch} is already open"
  else
    selector="$(create_pull_request "${branch}" "${summary}")"
    echo "${selector}"
  fi
  [[ "${trusted}" = yes ]] || return 1
  enable_auto_merge "${selector}" "${expected}"
}

main "$@"
