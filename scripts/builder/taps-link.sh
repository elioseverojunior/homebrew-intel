#!/usr/bin/env bash

# Sourced helper shared by run.sh and pour.sh: points the Taps symlink brew
# resolves elioseverojunior/intel through at the job's checkout (TAP_DIR) and
# restores it on every exit. The caller sources keg.sh first and defines log().
# Test seam: TAPS_LINK (the Taps symlink).
# Must stay compatible with macOS /bin/bash 3.2.

# The Taps link's original target, kept while the link is swapped. A job killed
# with SIGKILL cannot restore the link; the next one reads it back from here.
# shellcheck disable=SC2154 # builder_cache comes from keg.sh
readonly saved_target="${builder_cache}/taps-link-target"
taps_link=""
link_target=""

# EXIT trap. A cancelled Actions job sends SIGINT and then SIGTERM, so further
# signals are ignored and errexit is off: the symlink must be put back.
restore_taps_link() {
  local status=$?
  trap '' INT TERM
  set +e
  trap - EXIT
  log "restoring ${taps_link} -> ${link_target}"
  if ln -sfn "${link_target}" "${taps_link}"
  then
    rm -f "${saved_target}"
  else
    log "could not restore ${taps_link}; point it at ${link_target} by hand"
  fi
  exit "${status}"
}

# Sets taps_link, the symlink brew resolves elioseverojunior/intel through.
locate_taps_link() {
  taps_link="${TAPS_LINK:-$(brew --repository)/Library/Taps/elioseverojunior/homebrew-intel}"
}

# True when the link already points at the checkout and no interrupted job
# saved the original target: the owner's tap clone would be lost, so a real job
# refuses.
# A link that cannot be resolved prints nothing, compares unequal and reads as
# not lost; that is the predicate's answer, not an error to abort on.
# shellcheck disable=SC2154,SC2312 # TAP_DIR is the caller's checkout
link_target_is_lost() {
  [[ ! -f "${saved_target}" ]] &&
    [[ "$(cd "${taps_link}" 2>/dev/null && pwd -P)" = "$(cd "${TAP_DIR}" && pwd -P)" ]]
}

# Sets link_target: the target saved by an interrupted job, else the link's
# current one, saved atomically before the swap.
record_link_target() {
  # shellcheck disable=SC2310 # pure predicate
  if link_target_is_lost
  then
    log "refusing to start: ${taps_link} already points at ${TAP_DIR}; repoint it at your tap clone"
    exit 1
  fi
  if [[ -f "${saved_target}" ]]
  then
    link_target="$(cat "${saved_target}")"
    log "recovering Taps link from a previous interrupted run (${link_target})"
    return 0
  fi
  link_target="$(readlink "${taps_link}")"
  write_atomically "${saved_target}" "${link_target}"
}

# brew resolves elioseverojunior/intel through this symlink, so it must point
# at the checkout being built. A real directory there is the owner's tap clone;
# refuse rather than replace it.
swap_taps_link() {
  locate_taps_link
  if [[ ! -L "${taps_link}" ]]
  then
    log "refusing to start: ${taps_link} is not a symlink"
    exit 1
  fi
  record_link_target
  trap restore_taps_link EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  log "pointing ${taps_link} at ${TAP_DIR} (was ${link_target})"
  ln -sfn "${TAP_DIR}" "${taps_link}"
}
