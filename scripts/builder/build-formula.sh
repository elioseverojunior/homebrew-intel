#!/usr/bin/env bash

set -Eeuo pipefail

# Build, test, bottle, upload and merge one tap formula on the Intel host:
#   build-formula.sh <name> <pkg-version> <out-dir>
# `brew install --build-bottle` has no reinstall form, so an installed keg is
# uninstalled first. From then on, any failure or interruption removes the
# half-built keg and reinstalls the recorded one (same full name, core as a
# fallback) before exiting non-zero, so /usr/local is never left without it.
# A pending-restore marker (see keg.sh) covers a kill during that restore.
# Must stay compatible with macOS /bin/bash 3.2.

readonly TAP="elioseverojunior/intel"
readonly REPO="elioseverojunior/homebrew-intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/keg.sh
source "${script_dir}/keg.sh"

restore_name=""
build_started=no
bottle_json=""
bottle_asset=""

log() {
  echo "build-formula: $*" >&2
}

# Prints the installed keg's full name (<tap>/<name>, plain <name> for core),
# or nothing when the formula is not installed.
installed_full_name() {
  local name="$1" info
  info="$(brew info --json=v2 --installed "${name}" 2>/dev/null)" || return 0
  python3 -c '
import json, sys
name = sys.argv[1]
for formula in json.loads(sys.stdin.read().strip() or "{}").get("formulae") or []:
    if formula.get("name") == name and formula.get("installed"):
        tap = formula.get("tap") or "homebrew/core"
        print(name if tap == "homebrew/core" else f"{tap}/{name}")
' "${name}" <<<"${info}"
}

# EXIT trap. A cancelled Actions job sends SIGINT and then SIGTERM, so further
# signals are ignored (brew inherits that) and errexit is off: the restore must
# run to the end whatever happens.
restore_previous_keg() {
  local status=$?
  trap '' INT TERM
  set +e
  trap - EXIT
  if [[ "${status}" -eq 0 ]]; then
    [[ -z "${restore_name}" ]] || rm -f "${pending_restore}"
  else
    log "failed (exit ${status})"
    remove_half_built_keg
    reinstall_recorded_keg
  fi
  exit "${status}"
}

remove_half_built_keg() {
  [[ "${build_started}" = yes ]] || return 0
  log "removing the half-built ${TAP}/${name}"
  brew uninstall --ignore-dependencies "${name}"
}

# The marker stays when nothing could be reinstalled; the next run retries.
reinstall_recorded_keg() {
  [[ -n "${restore_name}" ]] || return 0
  log "restoring ${restore_name}"
  if install_keg "${restore_name}"; then
    rm -f "${pending_restore}"
    return 0
  fi
  log "could not restore ${restore_name}; reinstall it by hand"
}

validate_arguments() {
  if [[ $# -ne 3 ]]; then
    log "usage: build-formula.sh <name> <pkg-version> <out-dir>"
    exit 2
  fi
  if [[ ! "$1" =~ ${NAME_PATTERN} || ! "$2" =~ ^[0-9A-Za-z][0-9A-Za-z._+-]*$ ]]; then
    log "invalid formula name or version: '$1' '$2'"
    exit 2
  fi
}

# Uninstalls the installed keg, if any, after recording it for the restore
# here and in the pending-restore marker. The marker holds one keg, so an
# earlier keg whose restore failed blocks every build until it is back.
uninstall_previous_keg() {
  if [[ -f "${pending_restore}" ]]; then
    log "refusing to build: $(cat "${pending_restore}") is still uninstalled (${pending_restore})"
    exit 1
  fi
  restore_name="$(installed_full_name "${name}")"
  if [[ -n "${restore_name}" ]]; then
    write_atomically "${pending_restore}" "${restore_name}"
    log "uninstalling ${restore_name}; it is restored if the build fails"
    brew uninstall --ignore-dependencies "${name}"
  fi
}

build_and_test() {
  build_started=yes
  brew install --build-bottle "${TAP}/${name}"
  brew test "${TAP}/${name}"
}

# Prints "<local_filename> <decoded filename>" of the bottle JSON's single tag.
bottle_filenames() {
  python3 -c '
import json, os, sys
from urllib.parse import unquote
document = json.load(open(sys.argv[1], encoding="utf-8"))
(entry,) = document.values()
(tag,) = entry["bottle"]["tags"].values()
# brew URL-encodes filename (python@3.12 -> python%403.12); GitHub serves the
# asset under its decoded name, so that is the name to upload.
names = (tag["local_filename"], unquote(tag["filename"]))
if any(os.path.basename(n) != n or n.startswith(".") for n in names):
    sys.exit(f"unsafe bottle filename in {sys.argv[1]}")
print(*names)
' "$1"
}

# Writes the bottle into out_dir and renames the tarball to the JSON's filename.
# Sets bottle_json and bottle_asset (globals: a command substitution would run
# this in a subshell where errexit does not apply under bash 3.2).
make_bottle() {
  local root_url="$1" matches pair local_file filename
  (cd "${out_dir}" && brew bottle --json --root-url="${root_url}" "${TAP}/${name}")
  matches="$(find "${out_dir}" -maxdepth 1 -name "${name}--${version}.*.bottle.json")"
  if [[ -z "${matches}" || "${matches}" == *$'\n'* ]]; then
    log "expected exactly one ${name}--${version}.*.bottle.json in ${out_dir}"
    return 1
  fi
  pair="$(bottle_filenames "${matches}")"
  read -r local_file filename <<<"${pair}"
  if [[ "${local_file}" != "${filename}" ]]; then
    mv -f "${out_dir}/${local_file}" "${out_dir}/${filename}"
  fi
  bottle_json="${matches}"
  bottle_asset="${out_dir}/${filename}"
}

upload_asset() {
  local tag="$1" asset="$2"
  if gh release view "${tag}" -R "${REPO}" >/dev/null 2>&1; then
    gh release upload "${tag}" "${asset}" --clobber -R "${REPO}"
  else
    gh release create "${tag}" "${asset}" --title "${tag}" --notes "${name} ${version} Intel bottles" -R "${REPO}"
  fi
}

main() {
  validate_arguments "$@"
  name="$1"
  version="$2"
  mkdir -p "$3"
  out_dir="$(cd "$3" && pwd -P)"
  local root_url
  root_url="$(python3 "${script_dir}/../tap/bottles.py" root-url "${name}" "${version}")"

  trap restore_previous_keg EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  uninstall_previous_keg
  build_and_test
  make_bottle "${root_url}"
  upload_asset "${root_url##*/}" "${bottle_asset}"
  brew bottle --merge --write --no-commit "${bottle_json}"
  log "bottled ${name} ${version}"
}

main "$@"
