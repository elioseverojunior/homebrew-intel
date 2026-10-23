#!/usr/bin/env bash
# shellcheck disable=SC2154 # TAP_DIR, core_commit, force_args and out_dir are run.sh globals

# Sourced by run.sh: renders the tap at the run's core commit, plans the builds
# and records each changed formula outside the plan as render-only. Uses
# run.sh's TAP_DIR, core_commit, force_args, out_dir and manifest(); sets plan.
# Must stay compatible with macOS /bin/bash 3.2.

# Prints the Formula/*.rb paths the render added or modified (deletions are
# left alone).
changed_formulae() {
  local line path porcelain
  porcelain="$(git -C "${TAP_DIR}" status --porcelain --untracked-files=all -- Formula)" || return
  while IFS= read -r line
  do
    path="${line:3}"
    [[ -n "${line}" && "${line:0:2}" != *D* && "${path}" == *.rb ]] || continue
    printf '%s\n' "${path}"
  done <<<"${porcelain}"
}

# True when a tracked file differs from HEAD only in line 1, the generated
# header naming the core commit. A failed read makes the sides differ, so the
# change is kept: the predicate's safe answer, not an error to abort on.
# shellcheck disable=SC2312
header_only_change() {
  git -C "${TAP_DIR}" cat-file -e "HEAD:$1" 2>/dev/null || return 1
  cmp -s <(git -C "${TAP_DIR}" show "HEAD:$1" | tail -n +2) <(tail -n +2 "${TAP_DIR}/$1")
}

# Renders, then plans. A planned formula goes in with its bottle, so a failed
# version bump never lands; it keeps the render's header, since verify checks
# every published formula against the run's core commit. Outside the plan, a
# header-only change is reverted and any other change is recorded as
# render-only.
render_and_classify() {
  local path name changed
  python3 "${TAP_DIR}/scripts/tap/render.py" --core-commit "${core_commit}"
  plan="$(planned_builds)"
  changed="$(changed_formulae)"
  while IFS= read -r path <&3
  do
    [[ -n "${path}" ]] || continue
    name="$(basename "${path}" .rb)"
    # shellcheck disable=SC2310 # header_only_change and planned are pure predicates
    if planned "${name}"
    then
      continue
    elif header_only_change "${path}"
    then
      git -C "${TAP_DIR}" checkout --quiet -- "${path}"
    else
      manifest render-only "${out_dir}" "${TAP_DIR}" "${name}"
    fi
  done 3<<<"${changed}"
}

planned_builds() {
  python3 "${TAP_DIR}/scripts/tap/plan.py" builds ${force_args[@]+"${force_args[@]}"}
}

# True when <name> starts a line of the plan.
planned() {
  local first rest
  while read -r first rest
  do
    [[ "${first}" = "$1" ]] && return 0
  done <<<"${plan}"
  return 1
}
