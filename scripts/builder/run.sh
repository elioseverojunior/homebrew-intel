#!/usr/bin/env bash

set -Eeuo pipefail

# Run one Intel bottle build on the self-hosted Mac, from the tap checkout:
#   run.sh [--force NAME ...] [--dry-run]
# Env: GH_TOKEN (App token), GITHUB_RUN_NUMBER, PRIVATE_GH_TOKEN (failure
# issues; skipped with a warning when unset), BUILDER_CACHE (core clone and
# run-state markers, default ~/Library/Caches/homebrew-intel-builder),
# BUILDER_LOG_DIR (default <checkout>/.builder/logs).
# Test seams: TAP_DIR (the checkout whose scripts run; default this script's
# repository), TAPS_LINK (the Taps symlink), BUILDER_CORE_URL (core remote).
# Steps: reinstall a keg an interrupted build left uninstalled, point the Taps
# symlink at the checkout (restored on every exit), fetch the API, sync the core
# clone, render, plan, commit the changed formulae that need no bottle, build
# each planned formula in order (skipping dependents of failures; its commit
# carries the render too), open the PR.
# --dry-run fetches the API and prints the plan; it changes nothing else.
# Must stay compatible with macOS /bin/bash 3.2.

readonly PRIVATE_REPO="elioseverojunior/homebrew-intel-private"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/keg.sh
source "${script_dir}/keg.sh"
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"
export TAP_DIR
readonly run_dir="${TAP_DIR}/.builder"
readonly log_dir="${BUILDER_LOG_DIR:-${run_dir}/logs}"
readonly core_url="${BUILDER_CORE_URL:-https://github.com/Homebrew/homebrew-core}"
# The Taps link's original target, kept while the link is swapped. A run killed
# with SIGKILL cannot restore the link; the next run reads it back from here.
readonly saved_target="${builder_cache}/taps-link-target"

dry_run=no
force_args=()
branch=""
core_commit=""
plan=""
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

# Sets taps_link, the symlink brew resolves elioseverojunior/intel through.
locate_taps_link() {
  taps_link="${TAPS_LINK:-$(brew --repository)/Library/Taps/elioseverojunior/homebrew-intel}"
}

# True when the link already points at the checkout and no interrupted run
# saved the original target: the owner's tap clone would be lost, so a real run
# refuses.
link_target_is_lost() {
  [[ ! -f "${saved_target}" ]] &&
    [[ "$(cd "${taps_link}" 2>/dev/null && pwd -P)" = "$(cd "${TAP_DIR}" && pwd -P)" ]]
}

# Sets link_target: the target saved by an interrupted run, else the link's
# current one, saved atomically before the swap.
record_link_target() {
  if link_target_is_lost; then
    log "refusing to start: ${taps_link} already points at ${TAP_DIR}; repoint it at your tap clone"
    exit 1
  fi
  if [[ -f "${saved_target}" ]]; then
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

# Reinstalls the keg an interrupted build left uninstalled (keg.sh), before
# anything else; stops the run, Taps link untouched, when that fails.
recover_pending_restore() {
  [[ -f "${pending_restore}" ]] || return 0
  local full_name
  full_name="$(cat "${pending_restore}")"
  log "reinstalling ${full_name}, left uninstalled by an interrupted build"
  if [[ "${full_name}" =~ ^([a-z0-9-]+/[a-z0-9-]+/)?[a-z0-9][a-z0-9@._+-]*$ ]] &&
    install_keg "${full_name}"; then
    rm -f "${pending_restore}"
    return 0
  fi
  log "could not reinstall '${full_name}'; reinstall it by hand and delete ${pending_restore}"
  exit 1
}

# brew bottle numbers a rebuild from origin/HEAD, which actions/checkout does
# not create; without it a rebuild of an unchanged version would be rebuild 0
# and clobber the live asset.
set_origin_head() {
  git -C "${TAP_DIR}" symbolic-ref -q refs/remotes/origin/HEAD >/dev/null && return 0
  if ! git -C "${TAP_DIR}" rev-parse -q --verify refs/remotes/origin/main >/dev/null; then
    log "warning: no origin/main in ${TAP_DIR}; bottle rebuild numbers may be wrong"
    return 0
  fi
  git -C "${TAP_DIR}" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
}

# A shallow, blobless fetch of just the run's core commit; render's `git show`
# fetches the blobs it reads on demand from the promisor remote.
sync_core_clone() {
  local clone="${builder_cache}/homebrew-core"
  if [[ ! -d "${clone}/.git" ]]; then
    git init --quiet "${clone}"
    git -C "${clone}" remote add origin "${core_url}"
  fi
  git -C "${clone}" fetch --quiet --depth=1 --filter=blob:none origin "${core_commit}"
  export HOMEBREW_CORE_REPO="${clone}"
}

# Prints the Formula/*.rb paths the render added or modified (deletions are
# left alone).
changed_formulae() {
  local line path
  while IFS= read -r line; do
    path="${line:3}"
    [[ -n "${line}" && "${line:0:2}" != *D* && "${path}" == *.rb ]] || continue
    printf '%s\n' "${path}"
  done <<<"$(git -C "${TAP_DIR}" status --porcelain --untracked-files=all -- Formula)"
}

# True when a tracked file differs from HEAD only in line 1, the generated
# header naming the core commit.
header_only_change() {
  git -C "${TAP_DIR}" cat-file -e "HEAD:$1" 2>/dev/null || return 1
  cmp -s <(git -C "${TAP_DIR}" show "HEAD:$1" | tail -n +2) <(tail -n +2 "${TAP_DIR}/$1")
}

# Renders, then plans. A header-only change is reverted. Other changes are
# committed now only for formulae outside the plan: a planned formula's bottle
# commit carries its render, so a failed version bump never lands.
render_and_commit() {
  local path name
  python3 "${TAP_DIR}/scripts/tap/render.py" --core-commit "${core_commit}"
  plan="$(planned_builds)"
  while IFS= read -r path <&3; do
    [[ -n "${path}" ]] || continue
    name="$(basename "${path}" .rb)"
    if header_only_change "${path}"; then
      git -C "${TAP_DIR}" checkout --quiet -- "${path}"
    elif ! planned "${name}"; then
      "${TAP_DIR}/scripts/builder/commit-formula.sh" "${branch}" "${name}" \
        "${name}: update from core ${core_commit:0:7}"
    fi
  done 3<<<"$(changed_formulae)"
}

planned_builds() {
  python3 "${TAP_DIR}/scripts/tap/plan.py" builds ${force_args[@]+"${force_args[@]}"}
}

# True when <name> starts a line of the plan.
planned() {
  local first rest
  while read -r first rest; do
    [[ "${first}" = "$1" ]] && return 0
  done <<<"${plan}"
  return 1
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
  local fields
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
  fetch_snapshot
  plan="$(planned_builds)"
  locate_taps_link
  echo "dry run: branch ${branch}, core commit ${core_commit}"
  if link_target_is_lost; then
    echo "${taps_link} already points at ${TAP_DIR} and no target is saved: a real run would refuse"
  fi
  echo "would point ${taps_link} at ${TAP_DIR} and sync ${builder_cache}/homebrew-core"
  echo "would render at ${core_commit:0:7}, revert header-only changes and commit each other"
  echo "changed formula that is not planned (a planned one goes in with its bottle)"
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
  recover_pending_restore
  swap_taps_link
  set_origin_head
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
