#!/usr/bin/env bash

set -Eeuo pipefail

# Build Intel bottles on the self-hosted Mac, with no secret in reach:
#   run.sh --build-only [--core-commit SHA] [--force NAME ...] [--dry-run]
# Writes what the hosted publish job needs to .builder/out (see manifest.py):
# manifest.json, bottles and their JSON, rendered formulae and build logs. It
# uploads, commits and pours nothing, and refuses a token in its environment.
# Env: BUILDER_CACHE (core clone and run-state markers, default
# ~/Library/Caches/homebrew-intel-builder).
# Test seams: TAP_DIR (the checkout whose scripts run; default this script's
# repository), TAPS_LINK (the Taps symlink), BUILDER_CORE_URL (core remote).
# Steps: reinstall a keg an interrupted build left uninstalled, point the Taps
# symlink at the checkout (restored on every exit), fetch the API, sync the core
# clone, render, plan, record the changed formulae that need no bottle, build
# each planned formula in order (skipping dependents of failures). A failed
# formula is recorded, not fatal: the run fails only when it cannot run or the
# plan names an invalid formula. --dry-run fetches the API and prints the plan.
# --core-commit pins the run to the homebrew-core commit the hosted prepare job
# resolved; without it the run uses the API snapshot's commit. When the API
# snapshot names another commit, the pinned one wins for the core clone and the
# render, and the difference is logged.
# Must stay compatible with macOS /bin/bash 3.2.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/keg.sh
source "${script_dir}/keg.sh"
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"
export TAP_DIR
# shellcheck source=scripts/builder/taps-link.sh
source "${script_dir}/taps-link.sh"
# shellcheck source=scripts/builder/render-plan.sh
source "${script_dir}/render-plan.sh"
readonly run_dir="${TAP_DIR}/.builder"
readonly out_dir="${run_dir}/out"
readonly log_dir="${out_dir}/logs"
readonly core_url="${BUILDER_CORE_URL:-https://github.com/Homebrew/homebrew-core}"

build_only=no
dry_run=no
force_args=()
core_commit=""
pinned_core_commit=""
plan=""
# " name name " list for membership tests (no associative arrays in bash 3.2).
unbuilt=" "
invalid_plan=no

log() {
  echo "run: $*" >&2
}

usage() {
  log "usage: run.sh --build-only [--core-commit SHA] [--force NAME ...] [--dry-run]"
  exit 2
}

parse_arguments() {
  while [[ $# -gt 0 ]]
  do
    case "$1" in
      --build-only) build_only=yes ;;
      --dry-run) dry_run=yes ;;
      --force)
        [[ $# -ge 2 && "$2" =~ ${NAME_PATTERN} ]] || usage
        force_args+=(--force "$2")
        shift
        ;;
      --core-commit)
        [[ $# -ge 2 && "$2" =~ ^[0-9a-f]{40}$ ]] || usage
        pinned_core_commit="$2"
        shift
        ;;
      *) usage ;;
    esac
    shift
  done
  [[ "${build_only}" = yes ]] || usage
}

manifest() {
  python3 "${script_dir}/manifest.py" "$@"
}

fetch_snapshot() {
  export HOMEBREW_INTEL_DATA="${run_dir}/api"
  "${TAP_DIR}/scripts/audit/fetch-api.sh" >&2
  core_commit="$(python3 "${TAP_DIR}/scripts/tap/plan.py" commit)"
  if [[ ! "${core_commit}" =~ ^[0-9a-f]{40}$ ]]
  then
    log "plan.py commit printed '${core_commit}', not a commit SHA"
    exit 1
  fi
  [[ -n "${pinned_core_commit}" ]] || return 0
  if [[ "${core_commit}" != "${pinned_core_commit}" ]]
  then
    log "API snapshot is at core ${core_commit}; rendering at the pinned ${pinned_core_commit}"
  fi
  core_commit="${pinned_core_commit}"
}

# brew bottle numbers a rebuild from origin/HEAD, which actions/checkout does
# not create; without it a rebuild of an unchanged version would be rebuild 0
# and clobber the live asset.
set_origin_head() {
  git -C "${TAP_DIR}" symbolic-ref -q refs/remotes/origin/HEAD >/dev/null && return 0
  if ! git -C "${TAP_DIR}" rev-parse -q --verify refs/remotes/origin/main >/dev/null
  then
    log "warning: no origin/main in ${TAP_DIR}; bottle rebuild numbers may be wrong"
    return 0
  fi
  git -C "${TAP_DIR}" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
}

# A shallow, blobless fetch of just the run's core commit; render's `git show`
# fetches the blobs it reads on demand from the promisor remote.
sync_core_clone() {
  local clone="${builder_cache}/homebrew-core"
  if [[ ! -d "${clone}/.git" ]]
  then
    git init --quiet "${clone}"
    git -C "${clone}" remote add origin "${core_url}"
  fi
  git -C "${clone}" fetch --quiet --depth=1 --filter=blob:none origin "${core_commit}"
  export HOMEBREW_CORE_REPO="${clone}"
}

# The branch date is fixed here, once, so a run that crosses midnight keeps
# one branch; publish.sh adds the run number.
start_manifest() {
  local tap_sha branch_date
  tap_sha="$(git -C "${TAP_DIR}" rev-parse HEAD)"
  branch_date="$(date -u +%F)"
  manifest init "${out_dir}" --core-commit "${core_commit}" --tap-sha "${tap_sha}" \
    --branch-date "${branch_date}"
  mkdir -p "${log_dir}"
}

record_failed() {
  log "failed: $1 $2"
  unbuilt+="$1 "
  manifest failed "${out_dir}" "$1" "$2"
}

record_skipped() {
  log "skipped: $1: $2"
  unbuilt+="$1 "
  manifest skipped "${out_dir}" "$1" "$2"
}

# A cancelled job signals the whole process group. tee ignores INT and TERM so
# it keeps draining build-formula.sh's output: if tee died, the keg restore in
# build-formula.sh would be killed by SIGPIPE on its next write.
tee_to_log() {
  trap '' INT TERM
  exec tee -a "$1"
}

# Builds one formula into its own bottle directory, then moves the bottle and
# the bottled formula into the output (manifest.py built).
build_one() {
  local name="$1" version="$2" log_file="${log_dir}/$1.log" bottle_dir="${run_dir}/bottles/$1"
  rm -rf "${bottle_dir}"
  log "building ${name} ${version} (log: ${log_file})"
  # The pipelines' status is the condition by design; tee_to_log only sets a
  # trap and execs tee, so there is no errexit inside it to lose.
  # shellcheck disable=SC2310
  if "${TAP_DIR}/scripts/builder/build-formula.sh" "${name}" "${version}" "${bottle_dir}" 2>&1 |
     tee_to_log "${log_file}" &&
     manifest built "${out_dir}" "${TAP_DIR}" "${name}" "${version}" "${bottle_dir}" 2>&1 |
     tee_to_log "${log_file}"
  then
    log "built ${name} ${version}"
    return 0
  fi
  record_failed "${name}" "${version}"
}

# Arguments: one plan line, "<name> <pkg-version|-> <tap-dep>...".
build_planned_formula() {
  local name="$1" version="$2" dependency
  shift 2
  if [[ ! "${name}" =~ ${NAME_PATTERN} ]]
  then
    log "invalid formula name in the plan: '${name}'"
    invalid_plan=yes
    return 0
  fi
  if [[ "${version}" = "-" ]]
  then
    record_skipped "${name}" "no API entry"
    return 0
  fi
  for dependency in "$@"
  do
    if [[ "${unbuilt}" == *" ${dependency} "* ]]
    then
      record_skipped "${name}" "dependency ${dependency} did not build"
      return 0
    fi
  done
  build_one "${name}" "${version}"
}

build_all() {
  local fields
  while read -r -a fields <&3
  do
    [[ ${#fields[@]} -ge 2 ]] || continue
    build_planned_formula "${fields[@]}"
  done 3<<<"${plan}"
}

print_dry_run() {
  fetch_snapshot
  plan="$(planned_builds)"
  locate_taps_link
  echo "dry run: core commit ${core_commit}"
  # shellcheck disable=SC2310 # pure predicate
  if link_target_is_lost
  then
    echo "${taps_link} already points at ${TAP_DIR} and no target is saved: a real run would refuse"
  fi
  echo "would point ${taps_link} at ${TAP_DIR} and sync ${builder_cache}/homebrew-core"
  echo "would render at ${core_commit:0:7}: a planned formula keeps its render, pinned header included,"
  echo "and goes in with its bottle; outside the plan, header-only changes are reverted and other changes recorded render-only"
  echo "plan (before render, so formulae the render changes may be missing):"
  echo "${plan:-  nothing to build}"
  echo "would build and bottle each in order into ${out_dir} for the publish job"
}

main() {
  parse_arguments "$@"
  # Nothing in a run reads stdin; children (brew) get /dev/null.
  exec </dev/null
  refuse_secrets
  mkdir -p "${run_dir}"
  if [[ "${dry_run}" = yes ]]
  then
    print_dry_run
    return 0
  fi
  # A previous run's output must never be uploaded as this one's.
  rm -rf "${out_dir}"
  recover_pending_restore
  swap_taps_link
  set_origin_head
  fetch_snapshot
  sync_core_clone
  start_manifest
  render_and_classify
  build_all
  manifest summary "${out_dir}"
  [[ "${invalid_plan}" = no ]]
}

main "$@"
