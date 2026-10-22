#!/usr/bin/env bash

set -Eeuo pipefail

# Run one Intel bottle build on the self-hosted Mac, from the tap checkout:
#   run.sh [--force NAME ...] [--dry-run]
# Env: GH_TOKEN (App token), GITHUB_RUN_NUMBER, PRIVATE_GH_TOKEN (failure
# issues; skipped with a warning when unset), BUILDER_CACHE (core clone, default
# ~/Library/Caches/homebrew-intel-builder), BUILDER_LOG_DIR (default
# <checkout>/.builder/logs).
# Test seams: TAP_DIR (the checkout whose scripts run; default this script's
# repository), TAPS_LINK (the Taps symlink), BUILDER_CORE_URL (core remote).
# Steps: point the Taps symlink at the checkout (restored on every exit), fetch
# the API, sync the core clone, render and commit changed formulae, build each
# planned formula in order (skipping dependents of failures), open the PR.
# --dry-run fetches the API and prints the plan; it changes nothing else.
# Must stay compatible with macOS /bin/bash 3.2.

readonly PRIVATE_REPO="elioseverojunior/homebrew-intel-private"
readonly NAME_PATTERN='^[a-z0-9][a-z0-9@._+-]*$'
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"
export TAP_DIR
readonly run_dir="${TAP_DIR}/.builder"
readonly log_dir="${BUILDER_LOG_DIR:-${run_dir}/logs}"
readonly cache_dir="${BUILDER_CACHE:-${HOME}/Library/Caches/homebrew-intel-builder}"
readonly core_url="${BUILDER_CORE_URL:-https://github.com/Homebrew/homebrew-core}"
# The Taps link's original target, kept while the link is swapped. A run killed
# with SIGKILL cannot restore the link; the next run reads it back from here.
readonly saved_target="${cache_dir}/taps-link-target"

dry_run=no
force_args=()
branch=""
core_commit=""
taps_link=""
link_target=""
# " name name " lists for membership tests (no associative arrays in bash 3.2).
unbuilt=" "
built_report=""
failed_report=""
skipped_report=""

log() {
  echo "run: $*" >&2
}

usage() {
  log "usage: run.sh [--force NAME ...] [--dry-run]"
  exit 2
}

parse_arguments() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) dry_run=yes ;;
      --force)
        [[ $# -ge 2 && "$2" =~ ${NAME_PATTERN} ]] || usage
        force_args+=(--force "$2")
        shift
        ;;
      *) usage ;;
    esac
    shift
  done
}

# Sets branch to bottle/<UTC date>-<run number>, once, so a run that crosses
# midnight keeps one branch.
set_branch() {
  local run_number="${GITHUB_RUN_NUMBER:-}"
  if [[ "${dry_run}" = yes && -z "${run_number}" ]]; then
    run_number=0
  fi
  if [[ ! "${run_number}" =~ ^[0-9]+$ ]]; then
    log "GITHUB_RUN_NUMBER must be a number, got '${run_number}'"
    exit 2
  fi
  branch="bottle/$(date -u +%F)-${run_number}"
}

# EXIT trap. A cancelled Actions job sends SIGINT and then SIGTERM, so further
# signals are ignored and errexit is off: the symlink must be put back.
restore_taps_link() {
  local status=$?
  trap '' INT TERM
  set +e
  trap - EXIT
  log "restoring ${taps_link} -> ${link_target}"
  if ln -sfn "${link_target}" "${taps_link}"; then
    rm -f "${saved_target}"
  else
    log "could not restore ${taps_link}; point it at ${link_target} by hand"
  fi
  exit "${status}"
}

# Sets link_target: the target saved by an interrupted run, else the link's
# current one, saved atomically before the swap.
record_link_target() {
  if [[ -f "${saved_target}" ]]; then
    link_target="$(cat "${saved_target}")"
    log "recovering Taps link from a previous interrupted run (${link_target})"
    return 0
  fi
  if [[ "$(cd "${taps_link}" 2>/dev/null && pwd -P)" = "$(cd "${TAP_DIR}" && pwd -P)" ]]; then
    log "refusing to start: ${taps_link} already points at ${TAP_DIR}; repoint it at your tap clone"
    exit 1
  fi
  link_target="$(readlink "${taps_link}")"
  mkdir -p "${cache_dir}"
  printf '%s\n' "${link_target}" >"${saved_target}.tmp"
  mv -f "${saved_target}.tmp" "${saved_target}"
}

# brew resolves elioseverojunior/intel through this symlink, so it must point
# at the checkout being built. A real directory there is the owner's tap clone;
# refuse rather than replace it.
swap_taps_link() {
  taps_link="${TAPS_LINK:-$(brew --repository)/Library/Taps/elioseverojunior/homebrew-intel}"
  if [[ ! -L "${taps_link}" ]]; then
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

fetch_snapshot() {
  export HOMEBREW_INTEL_DATA="${run_dir}/api"
  "${TAP_DIR}/scripts/audit/fetch-api.sh" >&2
  core_commit="$(python3 "${TAP_DIR}/scripts/tap/plan.py" commit)"
  if [[ ! "${core_commit}" =~ ^[0-9a-f]{40}$ ]]; then
    log "plan.py commit printed '${core_commit}', not a commit SHA"
    exit 1
  fi
}

sync_core_clone() {
  local clone="${cache_dir}/homebrew-core"
  if [[ -d "${clone}/.git" ]]; then
    git -C "${clone}" fetch --quiet --filter=blob:none origin "${core_commit}"
  else
    mkdir -p "${cache_dir}"
    git clone --quiet --filter=blob:none --no-checkout "${core_url}" "${clone}"
  fi
  export HOMEBREW_CORE_REPO="${clone}"
}

# Commits every formula the render changed, so a render-only change still
# reaches the branch when nothing needs a bottle. Deletions are left alone.
render_and_commit() {
  local changed line path
  python3 "${TAP_DIR}/scripts/tap/render.py" --core-commit "${core_commit}"
  changed="$(git -C "${TAP_DIR}" status --porcelain --untracked-files=all -- Formula)"
  while IFS= read -r line <&3; do
    path="${line:3}"
    [[ -n "${line}" && "${line:0:2}" != *D* && "${path}" == *.rb ]] || continue
    "${TAP_DIR}/scripts/builder/commit-formula.sh" "${branch}" "$(basename "${path}" .rb)" \
      "$(basename "${path}" .rb): update from core ${core_commit:0:7}"
  done 3<<<"${changed}"
}

planned_builds() {
  python3 "${TAP_DIR}/scripts/tap/plan.py" builds ${force_args[@]+"${force_args[@]}"}
}

record_built() {
  built_report+="- $1 $2"$'\n'
}

record_failed() {
  log "failed: $1 $2: $3"
  unbuilt+="$1 "
  failed_report+="- $1 $2: $3"$'\n'
}

record_skipped() {
  log "skipped: $1: $2"
  unbuilt+="$1 "
  skipped_report+="- $1: $2"$'\n'
}

# A cancelled job signals the whole process group. tee ignores INT and TERM so
# it keeps draining build-formula.sh's output: if tee died, the keg restore in
# build-formula.sh would be killed by SIGPIPE on its next write.
tee_to_log() {
  trap '' INT TERM
  exec tee "$1"
}

open_issue() {
  local name="$1" version="$2" log_file="$3" body="${run_dir}/issue-$1.md"
  if [[ -z "${PRIVATE_GH_TOKEN:-}" ]]; then
    log "warning: PRIVATE_GH_TOKEN is unset; no issue opened for ${name}"
    return 0
  fi
  {
    printf 'Last 200 lines of the %s %s build log:\n\n```\n' "${name}" "${version}"
    tail -n 200 "${log_file}"
    printf '```\n'
  } >"${body}"
  GH_TOKEN="${PRIVATE_GH_TOKEN}" gh issue create -R "${PRIVATE_REPO}" \
    --title "build failed: ${name} ${version}" --body-file "${body}" ||
    log "warning: could not open an issue for ${name}"
}

build_one() {
  local name="$1" version="$2" log_file="${log_dir}/$1.log" bottle_dir="${run_dir}/bottles/$1"
  rm -rf "${bottle_dir}"
  log "building ${name} ${version} (log: ${log_file})"
  if ! "${TAP_DIR}/scripts/builder/build-formula.sh" "${name}" "${version}" "${bottle_dir}" 2>&1 |
    tee_to_log "${log_file}"; then
    record_failed "${name}" "${version}" "build failed"
    open_issue "${name}" "${version}" "${log_file}"
    return 0
  fi
  if ! "${TAP_DIR}/scripts/builder/commit-formula.sh" "${branch}" "${name}" "${name}: add ${version} sequoia bottle" 2>&1 |
    tee -a "${log_file}"; then
    record_failed "${name}" "${version}" "bottled, but the commit failed"
    return 0
  fi
  record_built "${name}" "${version}"
}

# Arguments: one plan line, "<name> <pkg-version|-> <tap-dep>...".
build_planned_formula() {
  local name="$1" version="$2" dependency
  shift 2
  if [[ ! "${name}" =~ ${NAME_PATTERN} ]]; then
    record_failed "${name}" "${version}" "invalid formula name in the plan"
    return 0
  fi
  if [[ "${version}" = "-" ]]; then
    record_skipped "${name}" "no API entry"
    return 0
  fi
  for dependency in "$@"; do
    if [[ "${unbuilt}" == *" ${dependency} "* ]]; then
      record_skipped "${name}" "dependency ${dependency} did not build"
      return 0
    fi
  done
  build_one "${name}" "${version}"
}

build_all() {
  local plan fields
  plan="$(planned_builds)"
  mkdir -p "${log_dir}"
  while read -r -a fields <&3; do
    [[ ${#fields[@]} -ge 2 ]] || continue
    build_planned_formula "${fields[@]}"
  done 3<<<"${plan}"
}

summary_section() {
  printf '\n## %s\n\n%s' "$1" "${2:-"- none"$'\n'}"
}

write_summary() {
  {
    echo "Intel (Sequoia) bottles built from homebrew-core ${core_commit}."
    summary_section Built "${built_report}"
    summary_section Failed "${failed_report}"
    summary_section Skipped "${skipped_report}"
  } >"${run_dir}/summary.md"
}

print_dry_run() {
  local plan
  fetch_snapshot
  plan="$(planned_builds)"
  echo "dry run: branch ${branch}, core commit ${core_commit}"
  echo "would point ${TAPS_LINK:-the Taps symlink} at ${TAP_DIR} and sync ${cache_dir}/homebrew-core"
  echo "would render at ${core_commit:0:7} and commit each changed formula"
  echo "plan (before render, so formulae the render changes may be missing):"
  echo "${plan:-  nothing to build}"
  echo "would build each in order, commit '<name>: add <version> sequoia bottle',"
  echo "open an issue in ${PRIVATE_REPO} per failure, and open the pull request"
}

main() {
  parse_arguments "$@"
  # Nothing in a run reads stdin; children (brew, gh) get /dev/null.
  exec </dev/null
  set_branch
  mkdir -p "${run_dir}"
  if [[ "${dry_run}" = yes ]]; then
    print_dry_run
    return 0
  fi
  if [[ -z "${GH_TOKEN:-}" ]]; then
    log "GH_TOKEN is required"
    exit 2
  fi
  swap_taps_link
  fetch_snapshot
  sync_core_clone
  render_and_commit
  build_all
  write_summary
  printf 'Built:\n%sFailed:\n%sSkipped:\n%s' "${built_report}" "${failed_report}" "${skipped_report}"
  "${TAP_DIR}/scripts/builder/open-pr.sh" "${branch}" "${run_dir}/summary.md"
  [[ -z "${failed_report}" ]]
}

main "$@"
