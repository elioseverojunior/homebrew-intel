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

- Formulae in `Formula/<shard>/<name>.rb` (`<shard>` is the first letter;
  `lib*` names go to `Formula/lib/`) are **generated** from homebrew-core by
  `scripts/tap/render.py` (`mise run render`). Never hand-edit a Formula file
  or its `bottle do` block. The render leaves a permanent two-space-indented
  marker line `# bottle block: written by brew pr-pull`. `brew pr-pull`
  inserts the bottle block after `livecheck`/`head`, and the next render moves
  it right after the marker line. Drift ignores the block either way.
- Each rendered file starts with a two-line header naming the core commit it
  came from. The drift check re-renders from that commit.
- Enabling a formula means adding an entry to `enabled.toml`
  (`kind = "generated"`, or `kind = "patched"` plus a 40-character `base`
  core commit), then running `mise run render`.
- A patched formula (core removed, disabled or arm64-gated it, or it fails on
  Intel): edit the rendered file, then run
  `mise run render -- --make-patch <name>` to write `patches/<name>.patch`.
  Until the patch exists, render writes the formula unpatched from `base` and
  prints a notice. Commit the patch and the render. A patch may only remove
  Intel gates, revive a removed formula, or fix an Intel build failure.
- Same name as core. Users must install fully qualified
  (`brew install elioseverojunior/intel/<name>`), or core's version wins. Say
  so in README and caveats; never rename to dodge the collision.
- Dependencies that are also in this tap are rewritten to
  `elioseverojunior/intel/<dep>` by the render; the rest stay plain names.
- Casks are out of scope.

## Verification

Before any commit that touches a formula or `enabled.toml`:

Render reads `.cache/api/formula.json`: run `scripts/audit/fetch-api.sh`
first when it is missing or stale. It needs Python 3.11+ (pinned via mise).

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
- `verify-bot-pr` (`.github/workflows/verify-bot-pr.yml`) is the auto-merge
  gate. It runs on `pull_request_target`, so the base branch's workflow and
  `scripts/ci/verify_bot_pr.py` judge every pull request; it must never check
  out or run pull request code. Human pull requests pass as skipped and need
  the owner to merge. A pull request by `elios-automator[bot]` passes only
  when it comes from a same-repository `bottle/<date>-<n>` branch into
  `main`, only touches `Formula/`, its commit and file counts match the
  event (below the API listing limits), its commits are verified bot commits,
  and its head carries a successful `bottle-builder` check run from the
  `elios-automator` App whose `head_sha` and `external_id` are that head.
  That check run is the trust anchor; any later push to the branch removes
  it and auto-merge waits.
- The only GitHub-hosted Intel runner is `macos-15-intel`. It is the last
  Intel image and is expected to retire around August 2027. Don't add hosted
  labels such as `macos-13` (retired) or `macos-26-intel` (doesn't exist).
- Bottles are built by the private builder
  `elioseverojunior/homebrew-intel-private`, which writes the bottle blocks
  with `brew bottle --merge --write` and publishes them through a bot pull
  request (not `brew pr-pull`). Only Sequoia bottles are built; they also
  pour on Tahoe.
- For now the self-hosted runner (label `iMacPro`) runs natively on the
  owner's host. Safeguards: never `brew test-bot --cleanup`, `brew cleanup` or
  `brew autoremove`; set `HOMEBREW_NO_AUTO_UPDATE=1` and
  `HOMEBREW_NO_INSTALL_CLEANUP=1`; one run at a time. A Sequoia VM remains
  the target.
- No secret ever reaches the build host: formula code runs there as the
  runner's user and can read any ancestor's environment. Its `build.yml` has
  four jobs:
  - `build` (self-hosted, no token): `scripts/builder/run.sh --build-only`
    renders, plans, builds and bottles, and uploads `.builder/out` (manifest,
    bottles, rendered formulae, logs) as the `builder-out` artifact. It and
    `pour.sh` refuse to start when a GitHub token is in the environment.
  - `verify` (hosted, no permissions): the trust boundary,
    `scripts/builder/verify_artifact.py`. The build commit must be on `main`
    and each core commit on homebrew-core's HEAD
    (`scripts/ci/fetch-core.sh`). Every formula must be, bottle block aside,
    exactly its core render, and every bottle block must parse as only the
    lines brew writes, before any formula is evaluated.
    `scripts/builder/derive-versions.sh` then reads each version with
    `brew info` from the trusted renders (never an artifact file, with no
    token in reach), and the full check requires the manifest's versions,
    root URLs, release tags, sha256 values and file names to agree with it.
  - `publish` (hosted): repeats the pure check, mints the App token only
    then, and runs `scripts/builder/publish.sh`: it uploads each bottle to the
    release `<name>-<pkg_version>`, commits each formula to
    `bottle/<date>-<run-number>` as a verified bot commit (render-only
    formulae first), attests the last commit with the `bottle-builder` check
    run, opens one pull request and one private issue per failed build.
  - `pour` (self-hosted, no token): swaps each `--build-bottle` keg for a
    pour of its released bottle, since such a keg would rebuild from source
    on `reinstall`/`upgrade`.
- What auto-merges: only the builder's own pull request, and only when
  `open-pr.sh` finds the branch head is the run's last commit, main's ruleset
  requires `verify-bot-pr`, and then with `--match-head-commit` bound to that
  head. It merges after the five required checks (`lint-and-test`,
  `tap-syntax`, `drift`, `pour-test`, `verify-bot-pr`). Each commit chains on
  the run's previous one, so a commit pushed by anyone else is never built
  upon; then the run attests nothing, leaves the pull request to the owner
  and fails. Re-running the same workflow run fails at its first commit
  because its branch already exists; dispatch a new run instead.
- Dispatch a build with `gh workflow run build.yml -R
  elioseverojunior/homebrew-intel-private -f formulae=<name>` (add
  `-f dry-run=true` to only print the plan).
- Never cancel a run while it builds or pours: the old keg is uninstalled
  first and restored on failure. If a restore cannot finish, the keg's full
  name stays in `~/Library/Caches/homebrew-intel-builder/pending-restore`
  (`$BUILDER_CACHE`); the next build or pour reinstalls it, and no keg swap
  starts until it is back.
- Never hand-edit `bottle do` blocks; the builder writes them.

## Git

- Commits are GPG-signed (`git commit -S`) and never carry
  `Co-Authored-By` trailers.
- Commit subjects follow homebrew-core style: `<name> <version> (new formula)`,
  `<name>: <change>`.
