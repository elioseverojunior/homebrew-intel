#!/usr/bin/env bash

set -Eeuo pipefail

# Derive each built formula's pkg_version on the hosted runner, never from the
# host-written manifest and never by evaluating an artifact file:
#   derive-versions.sh <renders-dir> <artifact-dir> <versions.json>
# <renders-dir> holds the trusted renders `verify_artifact.py --formulae-only
# --renders` wrote after proving each artifact formula equals its core render
# with a strictly parsed bottle block; only that text, made from core, is ever
# loaded. brew loads formulae only from a tap, so this builds a scratch tap
# (the checkout's formulae plus the renders), links it as
# elioseverojunior/homebrew-intel, trusts just the built formulae and reads
# versions.stable and revision with `brew info`. The artifact only supplies the
# built names. Writes {"<name>": "<pkg_version>"}. Refuses to run with any
# token in its environment, since it loads formula code.
# Env: TAP_DIR (the checkout; default this script's repository).

readonly TAP="elioseverojunior/intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"

log() {
  echo "derive-versions: $*" >&2
}

# Sets scratch to a new tap holding the checkout's Formula plus the renders.
make_scratch_tap() {
  scratch="$(mktemp -d)"
  mkdir -p "${scratch}/Formula"
  [[ ! -d "${TAP_DIR}/Formula" ]] || cp -R "${TAP_DIR}/Formula/." "${scratch}/Formula/"
  [[ ! -d "$1/Formula" ]] || cp -R "$1/Formula/." "${scratch}/Formula/"
}

refuse_tokens() {
  local secret
  for secret in GH_TOKEN GITHUB_TOKEN PRIVATE_GH_TOKEN HOMEBREW_GITHUB_API_TOKEN
  do
    if [[ -n "${!secret:-}" ]]
    then
      log "refusing: ${secret} is set; formula code must not run next to a token"
      exit 2
    fi
  done
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
  if [[ $# -ne 3 || ! -d "$1" || ! -f "$2/manifest.json" ]]
  then
    log "usage: derive-versions.sh <renders-dir> <artifact-dir> <versions.json>"
    exit 2
  fi
  refuse_tokens
  local scratch=""
  make_scratch_tap "$1"
  link_tap "${scratch}"
  write_versions "$2" "$3"
}

main "$@"
