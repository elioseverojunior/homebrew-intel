# homebrew-intel

A Homebrew tap that keeps Intel (x86_64) Macs usable after homebrew-core
dropped them. Intel macOS is Tier 3 in Homebrew: no new Intel bottles are
published, and Homebrew plans to stop running on Intel in or after September
2027. This project ends then, unless a separate decision extends it.

The tap carries Intel `sequoia` bottles for an explicit, growing list of core
formulae (heaviest builds first, such as `llvm` and `rust`), so you pour them
instead of compiling. A Sequoia bottle also pours on Tahoe. It can also carry
formulae that core removed, disabled or restricted to arm64 when the software
still works on Intel; those have a small reviewed patch.

**Status:** bottles are being published. `lz4` ships an Intel Sequoia
bottle; other formulae still build from source until theirs is published. A
keg you built from source with `--build-bottle` keeps building on
`reinstall`, so switch it with `brew uninstall` and then `brew install`.

Formulae in `Formula/` are generated from homebrew-core and must not be edited
by hand. See `CLAUDE.md` for the workflow.

## Using the tap

Formulae here have the same names as core. Install them **fully qualified**,
for example `elioseverojunior/intel/llvm`. A bare name installs core's
version.

```bash
brew tap elioseverojunior/intel
brew trust elioseverojunior/intel
brew reinstall elioseverojunior/intel/llvm   # switches an installed core keg
```

Switching an installed core formula to the tap needs its tap dependencies
switched first: run `brew reinstall elioseverojunior/intel/<dep>` in
dependency order, because `brew install` refuses a name installed from
another tap.

In a Brewfile:

```ruby
tap "elioseverojunior/intel", trusted: true
brew "elioseverojunior/intel/llvm"
```

Once installed, a formula follows the tap. When core bumps it, you stay on the
tap's last published version until the new bottle is published (expected lag:
one day plus build time).

## Requirements

- Intel macOS with Homebrew in `/usr/local`. Bottles are built there.
- Sequoia 15 or Tahoe 26.

## License

BSD 2-Clause, the same as Homebrew; see [LICENSE.txt](LICENSE.txt). Formulae
are derived from homebrew-core, so its copyright notice is kept. Each formula's
`license` field still describes the upstream software it installs.
