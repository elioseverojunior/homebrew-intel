# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Purpose

A Homebrew tap (`brew tap elioseverojunior/intel`) that keeps macOS Intel
(x86_64) usable after homebrew-core dropped it. Intel macOS is Tier 3 in core:
no new Intel bottles, and Homebrew plans to stop running on Intel in or after
September 2027 (see `$(brew --repo)/docs/Support-Tiers.md`).

The tap carries:

- formulae homebrew-core removed, disabled, or gated with
  `depends_on arch: :arm64` that still build on Intel
- Intel bottles for current core formulae that no longer get them
- casks dropped for x86_64

Target: Intel macOS Big Sur 11 through Tahoe 26.

## Conventions

- Formulae live in `Formula/`, casks in `Casks/`, using the **same name as
  core**. Users must install fully qualified
  (`brew install elioseverojunior/intel/<name>`), or core's version wins. Say
  so in README and caveats; never rename to dodge the collision.
- Port from core with `brew extract <name> elioseverojunior/intel`, or copy the
  file from `$(brew --repo homebrew/core)` (both core and cask are tapped
  locally). Keep the upstream URL, license and test block, and remove only what
  blocks Intel (arch gates, arm64-only `on_*` branches, `disable!`).
- Drop the copied `bottle do` block. CI regenerates it for this tap's `root_url`.
- Dependencies that are still in core stay as plain names. Only reference
  `elioseverojunior/intel/<dep>` when the dependency itself lives here.

## Verification

Before any commit that touches a formula or cask:

```bash
brew style elioseverojunior/intel
brew audit --strict --online --tap=elioseverojunior/intel
brew install --build-from-source elioseverojunior/intel/<name>
brew test elioseverojunior/intel/<name>
```

The local machine is Intel (`/usr/local` prefix). Bottles must be built
under `/usr/local`, or relocation breaks them.

## Audit

`scripts/audit/run.sh` (`SKIP_FETCH=1` reuses `.cache/api`, `VERBOSE=1`)
rebuilds `reports/` from a fresh API snapshot plus local git history, taps and
`~/Brewfile`. Scripts are stdlib Python. Lint with `ruff check scripts/audit`
(config in `ruff.toml`) and `shellcheck`.

- `reports/brewfile.*` stay gitignored. They list the owner's packages, and
  this repo is public.
- Always compare Intel and ARM data from the same `fetch-api.sh` run. Mixing
  in brew's own `~/Library/Caches/Homebrew/api` produced fake "Intel-pinned"
  versions.
- Run the scripts with plain `python3`, not `python3 -I`, which drops the
  script directory from `sys.path` and breaks `import brew_api`.

## CI and bottles

- Bottles are built by `brew test-bot` in GitHub Actions and published with
  `brew pr-pull` (the `brew tap-new` workflow layout).
- The only GitHub-hosted Intel runner is `macos-15-intel`. It is the last
  Intel image and is expected to retire around August 2027. Tahoe 26 and
  Big Sur–Sonoma bottles need self-hosted Intel runners; don't add hosted
  labels such as `macos-13` (retired) or `macos-26-intel` (doesn't exist).
- `brew tap-new` stopped generating Intel macOS jobs on 2026-08-02, so add
  the Intel runners to its workflow by hand.
- Never hand-edit `bottle do` blocks; `pr-pull` writes them.

## Git

- Commits are GPG-signed (`git commit -S`) and never carry
  `Co-Authored-By` trailers.
- Commit subjects follow homebrew-core style: `<name> <version> (new formula)`,
  `<name>: <change>`.
