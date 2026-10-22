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

Target: Intel macOS Sequoia 15 and Tahoe 26 (bottles are built on Sequoia).
Design: `docs/superpowers/specs/2026-10-21-intel-bottles-design.md`.

## Conventions

- Formulae in `Formula/<letter>/<name>.rb` are **generated** from
  homebrew-core by `scripts/tap/render.py` (`mise run render`). Never
  hand-edit a Formula file or its `bottle do` block: `brew pr-pull` writes
  the bottle block after the permanent marker line
  `# bottle block: written by brew pr-pull`.
- Each rendered file starts with a two-line header naming the core commit it
  came from. The drift check re-renders from that commit.
- Enabling a formula means adding an entry to `enabled.toml`
  (`kind = "generated"`, or `kind = "patched"` plus a 40-character `base`
  core commit), then running `mise run render`.
- A patched formula (core removed, disabled or arm64-gated it, or it fails on
  Intel): edit the rendered file, then run
  `mise run render -- --make-patch <name>` to write `patches/<name>.patch`.
  Commit the patch and the render. A patch may only remove Intel gates,
  revive a removed formula, or fix an Intel build failure.
- Same name as core. Users must install fully qualified
  (`brew install elioseverojunior/intel/<name>`), or core's version wins. Say
  so in README and caveats; never rename to dodge the collision.
- Dependencies that are also in this tap are rewritten to
  `elioseverojunior/intel/<dep>` by the render; the rest stay plain names.
- Casks are out of scope.

## Verification

Before any commit that touches a formula or `enabled.toml`:

```bash
mise run render
mise run drift
mise run lint
mise run test
brew style elioseverojunior/intel/<name>
brew audit --strict --online --tap=elioseverojunior/intel
brew install --build-from-source elioseverojunior/intel/<name>
brew test elioseverojunior/intel/<name>
```

- `mise run drift` must pass.
- The local machine is Intel (`/usr/local` prefix). Bottles must be built
  under `/usr/local`, or relocation breaks them.
- The tap is symlinked to this checkout, so `brew style
  elioseverojunior/intel` also scans the gitignored `actions-runner/` and
  reports hundreds of unrelated offenses. Locally, run `brew style` on
  specific formulae (`brew style elioseverojunior/intel/<name>`); CI
  checkouts do not have that directory.
- `brew audit` errors inherited from core are accepted. For example, lz4
  reports an HTTP-mirror error that core's lz4 also has.

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

- Public CI (`.github/workflows/tests.yml`) runs on hosted runners only:
  `lint-and-test`, `tap-syntax` and `drift` on Ubuntu, and `pour-test` on
  `macos-15-intel`. Never run a job from this repository on the iMac.
- The only GitHub-hosted Intel runner is `macos-15-intel`. It is the last
  Intel image and is expected to retire around August 2027. Don't add hosted
  labels such as `macos-13` (retired) or `macos-26-intel` (doesn't exist).
- Bottles are built by the private builder
  `elioseverojunior/homebrew-intel-private` on a self-hosted runner labelled
  `iMacPro`, and published with `brew pr-pull`. Only Sequoia bottles are
  built; they also pour on Tahoe.
- For now the runner runs natively on the owner's host from the gitignored
  `actions-runner/` directory, started by hand with `./run.sh`. Safeguards:
  never `brew test-bot --cleanup`, `brew cleanup` or `brew autoremove`; set
  `HOMEBREW_NO_AUTO_UPDATE=1` and `HOMEBREW_NO_INSTALL_CLEANUP=1`; one job at
  a time. A Sequoia VM remains the target.
- Never hand-edit `bottle do` blocks; `pr-pull` writes them.

## Git

- Commits are GPG-signed (`git commit -S`) and never carry
  `Co-Authored-By` trailers.
- Commit subjects follow homebrew-core style: `<name> <version> (new formula)`,
  `<name>: <change>`.
