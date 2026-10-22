#!/usr/bin/env bash

set -Eeuo pipefail

# Open the run's pull request for its bottle branch:
#   open-pr.sh <branch> <summary-file>
# Env: GH_TOKEN, GITHUB_RUN_NUMBER. Does nothing when the branch is missing or
# has no commits ahead of main (a run that bottled nothing).

readonly REPO="elioseverojunior/homebrew-intel"

log() {
  echo "open-pr: $*" >&2
}

validate_arguments() {
  if [[ $# -ne 2 ]]; then
    log "usage: open-pr.sh <branch> <summary-file>"
    exit 2
  fi
  if [[ ! "$1" =~ ^bottle/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+$ ]]; then
    log "invalid branch: '$1'"
    exit 2
  fi
  if [[ ! -f "$2" || ! "${GITHUB_RUN_NUMBER:-}" =~ ^[0-9]+$ ]]; then
    log "summary file missing or GITHUB_RUN_NUMBER is not a number"
    exit 2
  fi
}

# Prints the number of commits the branch is ahead of main; 0 if it is missing.
commits_ahead() {
  local errors status=0 ahead=""
  errors="$(mktemp)"
  ahead="$(gh api "repos/${REPO}/compare/main...$1" --jq .ahead_by 2>"${errors}")" || status=$?
  if [[ "${status}" -ne 0 ]] && ! grep -q "Not Found" "${errors}"; then
    cat "${errors}" >&2
    rm -f "${errors}"
    return "${status}"
  fi
  rm -f "${errors}"
  echo "${ahead:-0}"
}

main() {
  validate_arguments "$@"
  local branch="$1" summary="$2" ahead
  ahead="$(commits_ahead "${branch}")"
  if [[ "${ahead}" -eq 0 ]]; then
    log "nothing to open: ${branch} has no commits ahead of main"
    return 0
  fi
  gh pr create -R "${REPO}" --base main --head "${branch}" \
    --title "bottles: $(date -u +%F) run ${GITHUB_RUN_NUMBER}" --body-file "${summary}"
}

main "$@"
