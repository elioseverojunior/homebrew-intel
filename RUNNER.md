# Runners

This public tap runs its CI on GitHub-hosted runners only: `ubuntu-latest`
and `macos-15-intel` (see `.github/workflows/tests.yml`).

It never uses a self-hosted runner. On a public repository, a pull request
from a fork can run arbitrary code on a self-hosted machine. There is no
self-hosted fallback either: GitHub picks a runner by labels, not by which
runners are available, and falling back to a self-hosted one would expose the
same risk.

Bottles for formulae that core no longer builds for Intel come from the
private builder repository, `elioseverojunior/homebrew-intel-private`. Its
self-hosted runner, `macos-intel` (labels `self-hosted`, `macOS`, `X64`,
`iMacPro`), runs `scripts/builder/run.sh` from a checkout of this tap and
opens a pull request here. That repository's `RUNNER.md` documents the runner
and the `runner:*` mise tasks that install, configure and run it
(`runner:setup`, `runner:start`, `runner:service`, `runner:remove`,
`runner:status`).
