#!/usr/bin/env bash

set -Eeuo pipefail

# Fetch homebrew-core commits into a shallow, blobless clone, refusing any
# commit that homebrew-core's HEAD does not contain:
#   fetch-core.sh <dir> [<commit> ...]
# GitHub also serves commits from forks of homebrew-core through its URL, so a
# successful fetch proves nothing about where a SHA comes from; the compare API
# does. Used by the drift job and by the publish job, whose core commit comes
# from the untrusted build host. Env: GH_TOKEN (any token; public read).
# Test seam: CORE_URL (the core remote).

readonly core_url="${CORE_URL:-https://github.com/Homebrew/homebrew-core}"

log() {
  echo "fetch-core: $*" >&2
}

validate_arguments() {
  if [[ $# -lt 1 ]]
  then
    log "usage: fetch-core.sh <dir> [<commit> ...]"
    exit 2
  fi
  local commit
  for commit in "${@:2}"
  do
    if [[ ! "${commit}" =~ ^[0-9a-f]{40}$ ]]
    then
      log "invalid commit: '${commit}'"
      exit 2
    fi
  done
}

# Fails unless homebrew-core's HEAD is the commit or descends from it.
require_on_core_head() {
  local status
  status="$(gh api "repos/Homebrew/homebrew-core/compare/$1...HEAD" --jq .status)"
  case "${status}" in
    ahead | identical) ;;
    *)
      log "$1 is not on homebrew-core HEAD (status: ${status})"
      exit 1
      ;;
  esac
}

main() {
  validate_arguments "$@"
  local clone="$1" commit
  shift
  if [[ ! -d "${clone}/.git" ]]
  then
    git init --quiet "${clone}"
    git -C "${clone}" remote add origin "${core_url}"
  fi
  for commit in "$@"
  do
    git -C "${clone}" fetch --quiet --depth=1 --filter=blob:none origin "${commit}"
    require_on_core_head "${commit}"
  done
}

main "$@"
