#!/usr/bin/env bash

set -Eeuo pipefail

# Open the run's pull request for its bottle branch:
#   open-pr.sh <branch> <summary-file>
# Env: GH_TOKEN. The title comes from the branch name (bottle/<date>-<run>), so a
# run that crosses midnight stays consistent. Does nothing when the branch is
# missing, has no commits ahead of main, or already has an open pull request.
# The branch head first gets a successful `bottle-builder` check run, created
# with the App token: verify-bot-pr trusts exactly that commit, so any later
# push to the branch blocks auto-merge. A new pull request gets auto-merge
# (squash) enabled; it merges once the required checks pass. If the check run
# or auto-merge cannot be set up, the run still succeeds and the owner merges
# by hand.

readonly REPO="elioseverojunior/homebrew-intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/gh-lookup.sh
source "${script_dir}/gh-lookup.sh"

log() {
  echo "open-pr: $*" >&2
}

validate_arguments() {
  if [[ $# -ne 2 ]]
  then
    log "usage: open-pr.sh <branch> <summary-file>"
    exit 2
  fi
  if [[ ! "$1" =~ ^bottle/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+$ ]]
  then
    log "invalid branch: '$1'"
    exit 2
  fi
  if [[ ! -f "$2" ]]
  then
    log "summary file missing: '$2'"
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

open_pull_requests() {
  gh pr list -R "${REPO}" --head "$1" --state open --json number --jq length
}

readonly CHECK_NAME="bottle-builder"

create_check_run() {
  gh api "repos/${REPO}/check-runs" -f "name=${CHECK_NAME}" -f "head_sha=$1" \
    -f status=completed -f conclusion=success -f "output[title]=Intel bottle builder" \
    -f "output[summary]=Bottles built and committed by the private Intel builder." >/dev/null
}

# Marks the branch head with the check run; a failure only warns (verify-bot-pr
# then fails and auto-merge waits for the owner).
mark_head_built() {
  local head=""
  # shellcheck disable=SC2310 # gh_lookup prints gh's error itself; any failure warns below
  head="$(gh_lookup "repos/${REPO}/git/ref/heads/$1" --jq .object.sha)" || head=""
  # shellcheck disable=SC2310 # a failed check run only warns
  if [[ -n "${head}" ]] && create_check_run "${head}"
  then
    log "marked ${head} with the ${CHECK_NAME} check run"
    return 0
  fi
  log "warning: could not create the ${CHECK_NAME} check run on $1; verify-bot-pr will block auto-merge"
}

# Enables auto-merge; a failure (e.g. the repository setting is off) only warns.
enable_auto_merge() {
  if ! gh pr merge "$1" --auto --squash -R "${REPO}"
  then
    log "warning: could not enable auto-merge on $1; merge it by hand"
  fi
}

main() {
  validate_arguments "$@"
  local branch="$1" summary="$2" ahead title url
  ahead="$(commits_ahead "${branch}")"
  if [[ "${ahead}" -eq 0 ]]
  then
    log "nothing to open: ${branch} is missing or has no commits ahead of main"
    return 0
  fi
  mark_head_built "${branch}"
  # A failed lookup reads as no open pull request: gh pr create refuses a
  # duplicate itself, so a transient list failure still gets the run its PR.
  # shellcheck disable=SC2310,SC2312
  if [[ "$(open_pull_requests "${branch}")" -gt 0 ]]
  then
    log "a pull request for ${branch} is already open"
    return 0
  fi
  title="${branch#bottle/}"
  url="$(gh pr create -R "${REPO}" --base main --head "${branch}" \
    --title "bottles: ${title:0:10} run ${title:11}" --body-file "${summary}")"
  echo "${url}"
  enable_auto_merge "${url}"
}

main "$@"
