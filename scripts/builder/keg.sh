#!/usr/bin/env bash

# Sourced helper shared by build-formula.sh and run.sh: the Homebrew host
# safeguards, the builder cache and the pending-restore marker. build-formula.sh
# writes the marker (the full name of the keg it uninstalled) before the
# uninstall and deletes it once that keg is back, so a run killed mid-restore
# leaves it behind for the next run.sh to reinstall. The caller defines log().
# Must stay compatible with macOS /bin/bash 3.2.

# Host safeguards: never update, clean up, upgrade or rebuild dependents.
export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_NO_INSTALL_CLEANUP=1
export HOMEBREW_NO_INSTALL_UPGRADE=1
export HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1

# shellcheck disable=SC2034 # read by the scripts that source this file
readonly NAME_PATTERN='^[a-z0-9][a-z0-9@._+-]*$'
readonly builder_cache="${BUILDER_CACHE:-${HOME}/Library/Caches/homebrew-intel-builder}"
# shellcheck disable=SC2034 # read by the scripts that source this file
readonly pending_restore="${builder_cache}/pending-restore"

# write_atomically <path> <line>: a kill never leaves a half-written file.
write_atomically() {
  mkdir -p "$(dirname "$1")"
  printf '%s\n' "$2" >"$1.tmp"
  mv -f "$1.tmp" "$1"
}

# install_keg <full name>: a tap name may resolve to a just-failed formula (the
# run's checkout), so a failed tap install falls back to the core formula of the
# same name. Returns non-zero when nothing could be installed.
install_keg() {
  local full_name="$1" short_name="${1##*/}"
  brew install "${full_name}" && return 0
  if [[ "${full_name}" == */* ]]
  then
    log "could not install ${full_name}; falling back to core ${short_name}"
    brew install "${short_name}" && return 0
  fi
  return 1
}
