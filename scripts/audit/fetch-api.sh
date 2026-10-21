#!/usr/bin/env bash

set -Eeuo pipefail

# Downloads the public Homebrew API snapshot the audit scripts read. The
# per-tag internal payloads are what `brew` itself evaluates on each platform,
# so comparing the Intel and ARM ones shows Intel-only pins and disables.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
data_dir="${HOMEBREW_INTEL_DATA:-$repo_root/.cache/api}"
base_url="https://formulae.brew.sh/api"

files=(
  formula.json
  cask.json
  analytics/install-on-request/90d.json:analytics-formula.json
  analytics/cask-install/90d.json:analytics-cask.json
  internal/packages.sequoia.jws.json
  internal/packages.tahoe.jws.json
  internal/packages.arm64_sequoia.jws.json
  internal/packages.arm64_tahoe.jws.json
)

mkdir -p "$data_dir"
for entry in "${files[@]}"; do
  remote="${entry%%:*}"
  local_name="${entry#*:}"
  [ "$local_name" = "$entry" ] && local_name="$(basename "$remote")"
  curl -fsSL --retry 3 --retry-delay 2 -o "$data_dir/$local_name" "$base_url/$remote"
  [ "${VERBOSE:-0}" = 1 ] && echo "fetched $remote -> $data_dir/$local_name"
done
echo "API snapshot in $data_dir"
