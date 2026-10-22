#!/usr/bin/env bash

set -Eeuo pipefail

# Commit one tap formula to a run branch as a GPG-signed (GitHub-verified) commit:
#   commit-formula.sh <branch> <name> <headline>
# Env: GH_TOKEN (App token), TAP_DIR (the run's tap checkout).
# The branch is created from main's head on first use; every commit then goes
# through GraphQL createCommitOnBranch with the branch's current head as
# expectedHeadOid, so later commits build on the earlier ones.

readonly REPO="elioseverojunior/homebrew-intel"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly script_dir
# shellcheck source=scripts/builder/gh-lookup.sh
source "${script_dir}/gh-lookup.sh"

log() {
  echo "commit-formula: $*" >&2
}

validate_arguments() {
  if [[ $# -ne 3 ]]
  then
    log "usage: commit-formula.sh <branch> <name> <headline>"
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
}

# Prints the branch head SHA; prints nothing when the branch does not exist.
branch_head() {
  gh_lookup "repos/${REPO}/git/ref/heads/$1" --jq .object.sha
}

create_branch() {
  local branch="$1" main_head
  main_head="$(gh api "repos/${REPO}/git/ref/heads/main" --jq .object.sha)"
  log "creating ${branch} from main ${main_head}"
  gh api "repos/${REPO}/git/refs" -f "ref=refs/heads/${branch}" -f "sha=${main_head}" >/dev/null
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

formula_path() {
  PYTHONPATH="${script_dir}/../tap" python3 -c \
    'import sys; from core_source import formula_relpath; print(formula_relpath(sys.argv[1]))' "$1"
}

main() {
  validate_arguments "$@"
  local branch="$1" name="$2" headline="$3" path head
  path="$(formula_path "${name}")"
  if [[ ! -f "${TAP_DIR}/${path}" ]]
  then
    log "${TAP_DIR}/${path} does not exist"
    exit 1
  fi
  head="$(branch_head "${branch}")"
  if [[ -z "${head}" ]]
  then
    create_branch "${branch}"
    head="$(branch_head "${branch}")"
  fi
  build_request "${REPO}" "${branch}" "${head}" "${headline}" "${path}" "${TAP_DIR}/${path}" |
    gh api graphql --input - >/dev/null
  log "committed ${path} to ${branch}: ${headline}"
}

main "$@"
