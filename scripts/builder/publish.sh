#!/usr/bin/env bash

set -Eeuo pipefail

# Publish a verified build artifact from the hosted runner:
#   publish.sh <artifact-dir>
# Runs only after verify_artifact.py accepted <artifact-dir> (the build job's
# .builder/out), with the tap checked out at the commit the build used.
# Env: GH_TOKEN (App token for the public tap), PRIVATE_GH_TOKEN (failure
# issues in the private repository; skipped with a warning when unset),
# GITHUB_RUN_NUMBER, TAP_DIR (the checkout; default this script's repository).
# Places each formula into the checkout, commits the render-only formulae, then
# for each bottle uploads the release asset and commits the formula, every
# commit chained on the run's previous one (commit-formula.sh), the first on
# the manifest's tap_sha (the commit verify_artifact.py checked). An asset is
# never overwritten: one already on the release is kept only when its digest is
# the tarball's, and two formulae claiming one asset name are both refused.
# Opens the pull request on the run's last commit (open-pr.sh) and one issue
# per failed build (issue_body.py). Exits non-zero when anything failed or was
# not published.

readonly REPO="homebrew-intel/homebrew-tap"
readonly PRIVATE_REPO="homebrew-intel/builder"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
TAP_DIR="${TAP_DIR:-$(cd "${script_dir}/../.." && pwd -P)}"
export TAP_DIR
readonly work_dir="${TAP_DIR}/.builder"

out_dir=""
branch=""
core_commit=""
last_commit=""
unpublished=""
status=0

log() {
  echo "publish: $*" >&2
}

validate_arguments() {
  if [[ $# -ne 1 || ! -f "$1/manifest.json" ]]
  then
    log "usage: publish.sh <artifact-dir with manifest.json>"
    exit 2
  fi
  if [[ -z "${GH_TOKEN:-}" || ! "${GITHUB_RUN_NUMBER:-}" =~ ^[0-9]+$ ]]
  then
    log "GH_TOKEN and a numeric GITHUB_RUN_NUMBER are required"
    exit 2
  fi
}

manifest() {
  python3 "${script_dir}/manifest.py" "$1" "${out_dir}" "${@:2}"
}

place_formula() {
  mkdir -p "$(dirname "${TAP_DIR}/$1")"
  cp -f "${out_dir}/$1" "${TAP_DIR}/$1"
}

record_unpublished() {
  log "not published: $1"
  unpublished+="- $1"$'\n'
  status=1
}

# commit_to_branch <name> <headline>: commits the placed formula on top of the
# run's previous commit (none for the first: commit-formula.sh then creates the
# branch). Explicit returns: callers use it as a condition.
commit_to_branch() {
  local oid
  oid="$("${script_dir}/commit-formula.sh" "${branch}" "$1" "$2" ${last_commit:+"${last_commit}"})" || return $?
  last_commit="${oid}"
}

# asset_digest <tag> <asset-name>: prints the asset's digest ("none" when
# GitHub has none for it) or nothing when the release lacks the asset; fails
# when the release cannot be read (e.g. it does not exist).
asset_digest() {
  gh release view "$1" -R "${REPO}" --json assets 2>/dev/null | python3 -c '
import json, sys
assets = json.load(sys.stdin)["assets"]
print(*[asset.get("digest") or "none" for asset in assets if asset["name"] == sys.argv[1]][:1])
' "$2"
}

file_digest() {
  python3 -c 'import hashlib, sys; print("sha256:" + hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
}

# Never --clobber: a release that already holds the asset keeps it, and the run
# goes on only when that asset is byte for byte this bottle.
upload_release() {
  local name="$1" version="$2" asset="$3" tag="$1-$2" listed digest
  # shellcheck disable=SC2310 # an unreadable release is created; create refuses an existing one
  if ! listed="$(asset_digest "${tag}" "${asset##*/}")"
  then
    gh release create "${tag}" "${asset}" --title "${tag}" --notes "${name} ${version} Intel bottles" -R "${REPO}"
    return
  fi
  if [[ -z "${listed}" ]]
  then
    gh release upload "${tag}" "${asset}" -R "${REPO}"
    return
  fi
  digest="$(file_digest "${asset}")"
  if [[ "${listed}" = "${digest}" ]]
  then
    log "${tag} already has the identical ${asset##*/}; kept"
    return 0
  fi
  log "refusing: ${tag} already has ${asset##*/} with another digest (${listed})"
  return 1
}

publish_render_only() {
  local name relpath rows
  rows="$(manifest rows render_only)"
  while IFS=$'\t' read -r name relpath <&3
  do
    [[ -n "${name}" ]] || continue
    place_formula "${relpath}"
    # shellcheck disable=SC2310 # a refused commit is recorded, the run goes on
    commit_to_branch "${name}" "${name}: update from core ${core_commit:0:7}" ||
      record_unpublished "${name}: the commit failed"
  done 3<<<"${rows}"
}

# A bottle's commit goes in only after its asset is up, so a merged block never
# points at a missing release asset.
publish_bottles() {
  local name version relpath tarball rows claimed
  rows="$(manifest rows built)"
  claimed="$(cut -f4 <<<"${rows}" | sort | uniq -d)"
  while IFS=$'\t' read -r name version relpath tarball _ <&3
  do
    [[ -n "${name}" ]] || continue
    if [[ -n "${claimed}" ]] && grep -qxF "${tarball}" <<<"${claimed}"
    then
      record_unpublished "${name} ${version}: asset ${tarball} is claimed by another formula"
      continue
    fi
    place_formula "${relpath}"
    # shellcheck disable=SC2310 # a failed upload is recorded, the run goes on
    if ! upload_release "${name}" "${version}" "${out_dir}/bottles/${tarball}"
    then
      record_unpublished "${name} ${version}: release upload failed"
      continue
    fi
    # shellcheck disable=SC2310 # a refused commit is recorded, the run goes on
    commit_to_branch "${name}" "${name}: add ${version} sequoia bottle" ||
      record_unpublished "${name} ${version}: uploaded, but the commit failed"
  done 3<<<"${rows}"
}

write_summary() {
  manifest summary >"${work_dir}/summary.md"
  [[ -z "${unpublished}" ]] || printf '\n## Not published\n\n%s' "${unpublished}" >>"${work_dir}/summary.md"
}

# open-pr.sh attests and auto-merges the branch only if its head is still the
# last commit this run created.
open_pull_request() {
  if [[ -z "${last_commit}" ]]
  then
    log "no commits in this run; no pull request"
    return 0
  fi
  "${script_dir}/open-pr.sh" "${branch}" "${last_commit}" "${work_dir}/summary.md" || status=1
}

open_issue() {
  local name="$1" version="$2" body="${work_dir}/issue-$1.md"
  python3 "${script_dir}/issue_body.py" "${out_dir}/logs" "$3" "${name}" "${version}" >"${body}"
  GH_TOKEN="${PRIVATE_GH_TOKEN}" gh issue create -R "${PRIVATE_REPO}" \
    --title "build failed: ${name} ${version}" --body-file "${body}" ||
    log "warning: could not open an issue for ${name}"
}

open_issues() {
  local name version log_name rows
  rows="$(manifest rows failed)"
  [[ -n "${rows}" ]] || return 0
  status=1
  if [[ -z "${PRIVATE_GH_TOKEN:-}" ]]
  then
    log "warning: PRIVATE_GH_TOKEN is unset; no issues opened for failed builds"
    return 0
  fi
  while IFS=$'\t' read -r name version log_name <&3
  do
    open_issue "${name}" "${version}" "${log_name}"
  done 3<<<"${rows}"
}

main() {
  validate_arguments "$@"
  exec </dev/null
  out_dir="$(cd "$1" && pwd -P)"
  mkdir -p "${work_dir}"
  branch="bottle/$(manifest field branch_date)-${GITHUB_RUN_NUMBER}"
  core_commit="$(manifest field core_commit)"
  BASE_SHA="$(manifest field tap_sha)"
  export BASE_SHA
  publish_render_only
  publish_bottles
  write_summary
  open_pull_request
  open_issues
  return "${status}"
}

main "$@"
