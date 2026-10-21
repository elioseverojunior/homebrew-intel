---
name: port-formula
description: Port a formula or cask that homebrew-core/cask dropped, disabled, or restricted to arm64 into this Intel tap, then verify it builds and passes audit on Intel macOS. Use when adding a formula or cask to the tap.
disable-model-invocation: true
---

# Port formula

Port `$ARGUMENTS` into the `elioseverojunior/intel` tap.

1. **Locate the source.**
   - Present in core: `$(brew --repo homebrew/core)/Formula/<letter>/<name>.rb`
     (casks: `$(brew --repo homebrew/cask)/Casks/<letter>/<name>.rb`).
   - Removed from core: `brew extract <name> elioseverojunior/intel`
     (add `--version=` to pick a version). For casks, find the last revision
     with `git -C "$(brew --repo homebrew/cask)" log --all -- '**/<name>.rb'`.
   - Report why it is not usable on Intel (arch gate, `disable!`, removal
     commit) before changing anything.
2. **Copy it to** `Formula/<name>.rb` or `Casks/<name>.rb`, keeping the same
   name.
3. **Minimal edits only.** Remove `depends_on arch: :arm64`, arm64-only
   `on_arm`-exclusive logic, and `disable!`/`deprecate!` that were added for
   Intel. Delete the `bottle do` block. Keep the URL, sha256, license and test.
4. **Verify on this Intel machine:**

   ```bash
   brew style elioseverojunior/intel/<name>
   brew audit --strict --online elioseverojunior/intel/<name>
   brew install --build-from-source elioseverojunior/intel/<name>
   brew test elioseverojunior/intel/<name>
   ```

   For casks, run `brew install --cask elioseverojunior/intel/<name>` and
   `brew audit --cask --strict --online elioseverojunior/intel/<name>`.
   If the build fails, report the error and stop. Don't patch upstream
   source without asking.
5. **Commit** on a branch named `<name>`, signed (`git commit -S`), with no
   co-author trailer, using the subject `<name> <version> (new formula)` or
   `(new cask)`. Ask before pushing or opening a PR.
