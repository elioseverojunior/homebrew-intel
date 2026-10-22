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

In a Brewfile:

```ruby
tap "elioseverojunior/intel", trusted: true
brew "elioseverojunior/intel/llvm"
```

Once installed, a formula follows the tap. When core bumps it, you stay on the
tap's last published version until the new bottle is published (expected lag:
one day plus build time).

## Requirements

- Intel macOS with Homebrew in `/usr/local`. Bottles are built there and only
  some of them pour elsewhere.
- Sequoia 15 or Tahoe 26.

## License

See the license of each upstream project; formulae keep their upstream
`license` field.
