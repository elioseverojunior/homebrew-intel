#!/usr/bin/env bash

set -Eeuo pipefail

# Derive each built formula's pkg_version on the hosted runner, from the
# verified formula itself and never from the host-written manifest:
#   derive-versions.sh <artifact-dir> <versions.json>
# Run it only after `verify_artifact.py --formulae-only` proved every artifact
# formula equals its core render, so loading one runs only core's own code.
# brew loads formulae only from a tap, so this builds a scratch tap (the
# checkout's formulae plus the artifact's), links it as
# elioseverojunior/homebrew-intel, trusts just the built formulae and reads
# versions.stable and revision with `brew info`. Writes {"<name>": "<pkg_version>"}.
# Env: TAP_DIR (the checkout; default this script's repository).

readonly TAP="elioseverojunior/intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"

log() {
  echo "derive-versions: $*" >&2
}

# Prints "<name>\t<relpath>" of every formula in the artifact.
artifact_formulae() {
  local render_only built
  render_only="$(python3 "${script_dir}/manifest.py" rows "$1" render_only)"
  built="$(python3 "${script_dir}/manifest.py" rows "$1" built)"
  printf '%s\n' "${render_only}"
  cut -f1,3 <<<"${built}"
}

# Sets scratch to a new tap holding the checkout's Formula plus the artifact's.
make_scratch_tap() {
  local out="$1" listing name relpath
  listing="$(artifact_formulae "${out}")"
  scratch="$(mktemp -d)"
  mkdir -p "${scratch}/Formula"
  [[ ! -d "${TAP_DIR}/Formula" ]] || cp -R "${TAP_DIR}/Formula/." "${scratch}/Formula/"
  while IFS=$'\t' read -r name relpath <&3
  do
    [[ -n "${name}" ]] || continue
    mkdir -p "$(dirname "${scratch}/${relpath}")"
    cp -f "${out}/${relpath}" "${scratch}/${relpath}"
  done 3<<<"${listing}"
}

link_tap() {
  local link
  link="$(brew --repository)/Library/Taps/elioseverojunior/homebrew-intel"
  if [[ -e "${link}" && ! -L "${link}" ]]
  then
    log "refusing: ${link} already exists and is not this job's link"
    exit 1
  fi
  mkdir -p "$(dirname "${link}")"
  ln -sfn "$1" "${link}"
}

# Prints <name>'s pkg_version from `brew info`, failing unless brew described
# exactly that formula.
pkg_version() {
  brew info --json=v2 "${TAP}/$1" | python3 -c '
import json, sys
sys.path.insert(0, sys.argv[2])
from bottles import pkg_version
(formula,) = json.load(sys.stdin)["formulae"]
described = formula["name"]
print(pkg_version(formula)) if described == sys.argv[1] else sys.exit(f"brew info described {described}")
' "$1" "${script_dir}/../tap"
}

# Writes {"<name>": "<pkg_version>"} for the built formulae to <versions.json>.
write_versions() {
  local out="$1" built name names=() lines="" version
  built="$(python3 "${script_dir}/manifest.py" rows "${out}" built)"
  while IFS=$'\t' read -r name _ <&3
  do
    [[ -z "${name}" ]] || names+=("${name}")
  done 3<<<"${built}"
  [[ ${#names[@]} -eq 0 ]] || brew trust --formula "${names[@]/#/${TAP}/}"
  for name in ${names[@]+"${names[@]}"}
  do
    version="$(pkg_version "${name}")"
    lines+="${name}"$'\t'"${version}"$'\n'
  done
  python3 -c 'import json, sys; print(json.dumps(dict(l.split("\t") for l in sys.argv[1].splitlines())))' \
    "${lines}" >"$2"
}

main() {
  if [[ $# -ne 2 || ! -f "$1/manifest.json" ]]
  then
    log "usage: derive-versions.sh <artifact-dir> <versions.json>"
    exit 2
  fi
  local scratch=""
  make_scratch_tap "$1"
  link_tap "${scratch}"
  write_versions "$1" "$2"
}

main "$@"
