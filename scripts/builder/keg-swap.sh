#!/usr/bin/env bash

# Sourced helper shared by build-formula.sh and pour-formula.sh, which replace
# the installed keg of one tap formula. `start_keg_swap <name>` installs the
# EXIT trap, records the installed keg's full name in restore_name and in the
# pending-restore marker (keg.sh), and uninstalls it, since `brew install
# --build-bottle` has no reinstall form. The caller sets keg_touched=yes just
# before it installs anything. From then on, any failure or interruption
# removes the half-installed keg and reinstalls the recorded one (same full
# name, core as a fallback) before exiting non-zero, so /usr/local is never
# left without it. The caller sources keg.sh first and defines log().
# Must stay compatible with macOS /bin/bash 3.2.
# The embedded Python never starts a line with `if`: brew style's shfmt
# wrapper would take it for a shell `if` and reindent the snippet.

readonly TAP="elioseverojunior/intel"
swap_name=""
restore_name=""
keg_touched=no

# Prints the installed keg's full name (<tap>/<name>, plain <name> for core),
# or nothing when the formula is not installed.
installed_full_name() {
  local name="$1" info
  info="$(brew info --json=v2 --installed "${name}" 2>/dev/null)" || return 0
  python3 -c '
import json, sys
name = sys.argv[1]
formulae = json.loads(sys.stdin.read().strip() or "{}").get("formulae") or []
installed = [entry for entry in formulae if entry.get("name") == name and entry.get("installed")]
for formula in installed:
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
  if [[ "${status}" -eq 0 ]]
  then
    # shellcheck disable=SC2154 # pending_restore comes from keg.sh
    [[ -z "${restore_name}" ]] || rm -f "${pending_restore}"
  else
    log "failed (exit ${status})"
    remove_half_installed_keg
    reinstall_recorded_keg
  fi
  exit "${status}"
}

remove_half_installed_keg() {
  [[ "${keg_touched}" = yes ]] || return 0
  log "removing the half-installed ${TAP}/${swap_name}"
  brew uninstall --ignore-dependencies "${swap_name}"
}

# The marker stays when nothing could be reinstalled; the next job retries.
reinstall_recorded_keg() {
  [[ -n "${restore_name}" ]] || return 0
  log "restoring ${restore_name}"
  # shellcheck disable=SC2310 # runs in the EXIT trap after set +e; a failure is handled below
  if install_keg "${restore_name}"
  then
    rm -f "${pending_restore}"
    return 0
  fi
  log "could not restore ${restore_name}; reinstall it by hand"
}

# Uninstalls the installed keg, if any, after recording it for the restore
# here and in the pending-restore marker. The marker holds one keg, so an
# earlier keg whose restore failed blocks every swap until it is back.
uninstall_previous_keg() {
  if [[ -f "${pending_restore}" ]]
  then
    # shellcheck disable=SC2312 # message only; exit 1 follows whatever cat returns
    log "refusing to build: $(cat "${pending_restore}") is still uninstalled (${pending_restore})"
    exit 1
  fi
  restore_name="$(installed_full_name "${swap_name}")"
  if [[ -n "${restore_name}" ]]
  then
    write_atomically "${pending_restore}" "${restore_name}"
    log "uninstalling ${restore_name}; it is restored if this fails"
    brew uninstall --ignore-dependencies "${swap_name}"
  fi
}

start_keg_swap() {
  swap_name="$1"
  trap restore_previous_keg EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  uninstall_previous_keg
}
