#!/usr/bin/env bash

set -Eeuo pipefail

# Full Intel-support audit: refresh the API snapshot, classify core formulae,
# casks, removals and third-party taps, then render reports/*.md.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
verbose=()
[[ "${VERBOSE:-0}" = 1 ]] && verbose=(--verbose)

[[ "${SKIP_FETCH:-0}" = 1 ]] || "${script_dir}/fetch-api.sh"
for step in formulae casks removed taps summary
do
  python3 "${script_dir}/${step}.py" "${verbose[@]}"
done

# The Brewfile audit is personal, so it only runs when a Brewfile is found.
brewfile="${BREWFILE:-${HOMEBREW_BUNDLE_FILE:-${HOME}/Brewfile}}"
if [[ -f "${brewfile}" ]]
then
  python3 "${script_dir}/brewfile.py" "${brewfile}" "${verbose[@]}"
fi
