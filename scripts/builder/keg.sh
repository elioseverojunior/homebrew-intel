#!/usr/bin/env bash

# Sourced helper shared by the scripts that run on the build host: the Homebrew
# host safeguards, the no-secrets guard, the builder cache and the
# pending-restore marker. build-formula.sh and pour-formula.sh write the marker
# (the full name of the keg they uninstalled) before the uninstall and delete it
# once that keg is back, so a job killed mid-restore leaves it behind for the
# next run.sh or pour.sh to reinstall. The caller defines log().
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

# Formula code (install, test) runs as this user and can read the environment
# of every ancestor process (`ps -E`), so a token here could be stolen and
# shipped inside a public bottle. The host jobs get none; refuse if one leaks in.
refuse_secrets() {
  local secret
  for secret in GH_TOKEN GITHUB_TOKEN PRIVATE_GH_TOKEN
  do
    if [[ -n "${!secret:-}" ]]
    then
      log "refusing to start: ${secret} is set; no token may reach the build host"
      exit 2
    fi
  done
}

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

# Reinstalls the keg an interrupted job left uninstalled, before anything
# else; stops the job, Taps link untouched, when that fails.
recover_pending_restore() {
  [[ -f "${pending_restore}" ]] || return 0
  local full_name
  full_name="$(cat "${pending_restore}")"
  log "reinstalling ${full_name}, left uninstalled by an interrupted build"
  # install_keg checks each brew install itself (tap, then core fallback) and its
  # failure is handled below, so errexit is not needed inside it.
  # shellcheck disable=SC2310
  if [[ "${full_name}" =~ ^([a-z0-9-]+/[a-z0-9-]+/)?[a-z0-9][a-z0-9@._+-]*$ ]] &&
     install_keg "${full_name}"
  then
    rm -f "${pending_restore}"
    return 0
  fi
  log "could not reinstall '${full_name}'; reinstall it by hand and delete ${pending_restore}"
  exit 1
}
