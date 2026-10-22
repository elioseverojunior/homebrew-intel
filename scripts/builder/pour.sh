#!/usr/bin/env bash

set -Eeuo pipefail

# Pour the bottles the publish job just released, on the self-hosted Mac:
#   pour.sh <artifact-dir>
# Runs in the pour job, with no token, after publish succeeded. Places the
# artifact's formulae into the checkout (the tap commit the build used), points
# the Taps symlink at it (restored on every exit) and swaps each built
# formula's --build-bottle keg for a pour of its bottle (pour-formula.sh, which
# restores the previous keg on failure). A failed pour does not stop the
# others; the job then fails.
# Test seams: TAP_DIR (the checkout whose scripts run), TAPS_LINK, BUILDER_CACHE.
# Must stay compatible with macOS /bin/bash 3.2.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/keg.sh
source "${script_dir}/keg.sh"
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"
export TAP_DIR
# shellcheck source=scripts/builder/taps-link.sh
source "${script_dir}/taps-link.sh"

out_dir=""
status=0

log() {
  echo "pour: $*" >&2
}

rows() {
  python3 "${script_dir}/manifest.py" rows "${out_dir}" "$1"
}

place_formulae() {
  local render_only built listing name relpath
  render_only="$(rows render_only)"
  built="$(rows built)"
  listing="${render_only}"$'\n'"$(cut -f1,3 <<<"${built}")"
  while IFS=$'\t' read -r name relpath <&3
  do
    [[ -n "${name}" ]] || continue
    mkdir -p "$(dirname "${TAP_DIR}/${relpath}")"
    cp -f "${out_dir}/${relpath}" "${TAP_DIR}/${relpath}"
  done 3<<<"${listing}"
}

pour_all() {
  local built name
  built="$(rows built)"
  while IFS=$'\t' read -r name _ <&3
  do
    [[ -n "${name}" ]] || continue
    if ! "${TAP_DIR}/scripts/builder/pour-formula.sh" "${name}"
    then
      log "could not pour ${name}; its --build-bottle keg (or the restored one) stays"
      status=1
    fi
  done 3<<<"${built}"
}

main() {
  if [[ $# -ne 1 || ! -f "$1/manifest.json" ]]
  then
    log "usage: pour.sh <artifact-dir with manifest.json>"
    exit 2
  fi
  exec </dev/null
  refuse_secrets
  out_dir="$(cd "$1" && pwd -P)"
  recover_pending_restore
  place_formulae
  swap_taps_link
  pour_all
  return "${status}"
}

main "$@"
