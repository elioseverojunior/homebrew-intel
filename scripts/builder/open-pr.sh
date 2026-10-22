#!/usr/bin/env bash

set -Eeuo pipefail

# Open the run's pull request for its bottle branch:
#   open-pr.sh <branch> <summary-file>
# Env: GH_TOKEN. The title comes from the branch name (bottle/<date>-<run>), so a
# run that crosses midnight stays consistent. Does nothing when the branch is
# missing, has no commits ahead of main, or already has an open pull request.

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

main() {
  validate_arguments "$@"
  local branch="$1" summary="$2" ahead title
  ahead="$(commits_ahead "${branch}")"
  if [[ "${ahead}" -eq 0 ]]
  then
    log "nothing to open: ${branch} is missing or has no commits ahead of main"
    return 0
  fi
  # A failed lookup reads as no open pull request: gh pr create refuses a
  # duplicate itself, so a transient list failure still gets the run its PR.
  # shellcheck disable=SC2310,SC2312
  if [[ "$(open_pull_requests "${branch}")" -gt 0 ]]
  then
    log "a pull request for ${branch} is already open"
    return 0
  fi
  title="${branch#bottle/}"
  gh pr create -R "${REPO}" --base main --head "${branch}" \
    --title "bottles: ${title:0:10} run ${title:11}" --body-file "${summary}"
}

main "$@"
