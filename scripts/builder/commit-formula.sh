#!/usr/bin/env bash

set -Eeuo pipefail

# Commit one tap formula to a run branch as a GPG-signed (GitHub-verified) commit:
#   commit-formula.sh <branch> <name> <headline> [<expected-parent-sha>]
# Env: GH_TOKEN (App token), TAP_DIR (the run's tap checkout), BASE_SHA (the
# tap commit the run built and verified against: the manifest's tap_sha).
# Without <expected-parent-sha> (the run's first commit) the branch must not
# exist yet: it is created at BASE_SHA, which becomes the parent, so the pull
# request starts from the commit verify_artifact.py checked, never from a main
# that moved on in between. With it
# (the oid of the run's previous commit) the branch head must be exactly that
# commit. Either way the commit goes through GraphQL createCommitOnBranch with
# the parent as expectedHeadOid, so GitHub enforces it too, and a commit pushed
# by anyone else is never built upon (and so never attested by open-pr.sh).
# Prints the oid of the commit it created on stdout; publish.sh chains the next
# commit on it and hands the last one to open-pr.sh.

readonly REPO="elioseverojunior/homebrew-intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/gh-lookup.sh
source "${script_dir}/gh-lookup.sh"

log() {
  echo "commit-formula: $*" >&2
}

validate_arguments() {
  if [[ $# -lt 3 || $# -gt 4 ]]
  then
    log "usage: commit-formula.sh <branch> <name> <headline> [<expected-parent-sha>]"
    exit 2
  fi
  if [[ $# -eq 4 && ! "$4" =~ ^[0-9a-f]{40}$ ]]
  then
    log "invalid expected parent sha: '$4'"
    exit 2
  fi
  if [[ ! "$1" =~ ^bottle/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+$ ]]
  then
    log "invalid branch: '$1'"
    exit 2
  fi
  if [[ ! "$2" =~ ^[a-z0-9][a-z0-9@._+-]*$ || -z "$3" || -z "${TAP_DIR:-}" ]]
  then
    log "invalid formula name, empty headline or TAP_DIR unset"
    exit 2
  fi
  if [[ $# -eq 3 && ! "${BASE_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
  then
    log "the run's first commit needs BASE_SHA, a 40-hex commit"
    exit 2
  fi
}

# Prints the branch head SHA; prints nothing when the branch does not exist.
branch_head() {
  gh_lookup "repos/${REPO}/git/ref/heads/$1" --jq .object.sha
}

# Creates the branch at BASE_SHA and sets parent to it. Fails when the branch
# already exists: then this run did not create it.
create_branch() {
  local branch="$1" head
  head="$(branch_head "${branch}")"
  if [[ -n "${head}" ]]
  then
    log "refusing: ${branch} already exists at ${head}; this run did not create it"
    exit 1
  fi
  parent="${BASE_SHA}"
  log "creating ${branch} from the run's base ${parent}"
  gh api "repos/${REPO}/git/refs" -f "ref=refs/heads/${branch}" -f "sha=${parent}" >/dev/null
}

# Sets parent to the expected commit, failing unless it is the branch head.
expect_head() {
  local branch="$1" head
  head="$(branch_head "${branch}")"
  if [[ "${head}" != "$2" ]]
  then
    log "refusing: ${branch} head ${head} is not the expected parent $2"
    exit 1
  fi
  parent="$2"
}

# Prints the createCommitOnBranch request body (query + variables) as JSON.
# shellcheck disable=SC2016 # "$input" is GraphQL syntax, not shell
build_request() {
  python3 -c '
import base64, json, sys
repo, branch, head, headline, path, file = sys.argv[1:]
with open(file, "rb") as handle:
    contents = base64.b64encode(handle.read()).decode("ascii")
mutation = (
    "mutation($input: CreateCommitOnBranchInput!) "
    "{ createCommitOnBranch(input: $input) { commit { oid url } } }"
)
change = {
    "branch": {"repositoryNameWithOwner": repo, "branchName": branch},
    "expectedHeadOid": head,
    "message": {"headline": headline},
    "fileChanges": {"additions": [{"path": path, "contents": contents}]},
}
print(json.dumps({"query": mutation, "variables": {"input": change}}))
' "$@"
}

# Prints the created commit's oid from the createCommitOnBranch response.
created_oid() {
  python3 -c '
import json, sys
print(json.loads(sys.argv[1])["data"]["createCommitOnBranch"]["commit"]["oid"])
' "$1"
}

formula_path() {
  PYTHONPATH="${script_dir}/../tap" python3 -c \
    'import sys; from core_source import formula_relpath; print(formula_relpath(sys.argv[1]))' "$1"
}

main() {
  validate_arguments "$@"
  local branch="$1" name="$2" headline="$3" path response parent=""
  path="$(formula_path "${name}")"
  if [[ ! -f "${TAP_DIR}/${path}" ]]
  then
    log "${TAP_DIR}/${path} does not exist"
    exit 1
  fi
  if [[ $# -eq 4 ]]
  then
    expect_head "${branch}" "$4"
  else
    create_branch "${branch}"
  fi
  response="$(build_request "${REPO}" "${branch}" "${parent}" "${headline}" "${path}" "${TAP_DIR}/${path}" |
    gh api graphql --input -)"
  log "committed ${path} to ${branch}: ${headline}"
  created_oid "${response}"
}

main "$@"
