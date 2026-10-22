#!/usr/bin/env bash

# Sourced helper. `gh_lookup <gh api args...>` prints the call's stdout on
# success and prints nothing (status 0) when GitHub answers 404. Any other
# failure prints gh's stderr and returns its status. On an error gh also prints
# the raw error body to stdout, so stdout is only trusted on success.
gh_lookup() {
  local output errors status=0
  errors="$(mktemp)"
  output="$(gh api "$@" 2>"${errors}")" || status=$?
  if [[ "${status}" -eq 0 ]]; then
    printf '%s\n' "${output}"
  elif ! grep -q "HTTP 404" "${errors}"; then
    cat "${errors}" >&2
  else
    status=0
  fi
  rm -f "${errors}"
  return "${status}"
}
