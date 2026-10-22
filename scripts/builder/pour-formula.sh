#!/usr/bin/env bash

set -Eeuo pipefail

# Swap one tap formula's --build-bottle keg for a pour of its published bottle:
#   pour-formula.sh <name>
# A keg built with --build-bottle keeps that option in its receipt, so a later
# reinstall or upgrade would build from source. Runs in the pour job, after the
# publish job uploaded the asset, with no token. The keg swap (keg-swap.sh)
# reinstalls the previous keg if the pour fails or is interrupted.
# Must stay compatible with macOS /bin/bash 3.2.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/keg.sh
source "${script_dir}/keg.sh"
# shellcheck source=scripts/builder/keg-swap.sh
source "${script_dir}/keg-swap.sh"

log() {
  echo "pour-formula: $*" >&2
}

main() {
  if [[ $# -ne 1 || ! "$1" =~ ${NAME_PATTERN} ]]
  then
    log "usage: pour-formula.sh <name>"
    exit 2
  fi
  start_keg_swap "$1"
  keg_touched=yes
  brew install --force-bottle "${TAP}/$1"
  log "poured ${TAP}/$1"
}

main "$@"
