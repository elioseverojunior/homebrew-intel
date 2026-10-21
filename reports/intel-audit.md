# Auditoria de suporte macOS Intel

## Fórmulas (homebrew-core)

- `OLD_INTEL_BOTTLE`: 3914
- `NO_INTEL_BOTTLE`: 3433
- `OK`: 1123
- `DISABLED`: 154
- `ARM_ONLY`: 27
- `NO_BOTTLE_ANY_PLATFORM`: 8
- `BLOCKED_BY_ARM_DEPENDENCY`: 5

### ARM_ONLY

`apfel`, `asitop`, `baguette`, `batt`, `container`, `container-compose`,
`devcockpit`, `graalvm`, `lazycontainer`, `leaf`, `lume`, `m1ddc`, `macmon`,
`mactop`, `mlx`, `mlx-c`, `openlore`, `pget`, `podman`, `pomerium`, `reg`,
`socktainer`, `speech`, `sse2neon`, `syswatch`, `terraform-lsp`,
`whisperkit-cli`

### BLOCKED_BY_ARM_DEPENDENCY

`astro`, `mlx-lm`, `ollama`, `podman-compose`, `rapid-mlx`

### Versão congelada no Intel

Nenhum.

### NO_INTEL_BOTTLE — 40 mais instaladas

`gh`, `node`, `uv`, `awscli`, `ffmpeg`, `cmake`, `go`, `pkgconf`, `git`, `pipx`,
`coreutils`, `python@3.14`, `poppler`, `mise`, `openssl@3`, `imagemagick`, `yq`,
`pnpm`, `tmux`, `docker`, `fzf`, `python@3.12`, `hello`, `pyenv`, `mole`,
`yt-dlp`, `pandoc`, `protobuf`, `just`, `gnupg`, `kubernetes-cli`, `xz`,
`neovim`, `python@3.13`, `glab`, `ninja`, `opencode`, `helm`, `ccache`,
`cloudflared`

Lista completa: [formulae-no-intel-bottle.md](formulae-no-intel-bottle.md).

### OLD_INTEL_BOTTLE — 40 mais instaladas

`jq`, `xcbeautify`, `ripgrep`, `xcodegen`, `shellcheck`, `kubeconform`, `htop`,
`zsh`, `xclogparser`, `fd`, `actionlint`, `mint`, `mkcert`, `colima`, `tree`,
`gitleaks`, `zoxide`, `eza`, `xctesthtmlreport`, `bat`, `lua`, `k9s`, `jsonnet`,
`xcresultparser`, `cliclick`, `boost`, `k3d`, `p7zip`, `btop`, `watch`, `glow`,
`gnu-sed`, `binutils`, `fnm`, `openjdk@11`, `libffi`, `gnutls`, `telnet`,
`glfw`, `unar`

Lista completa: [formulae-old-intel-bottle.md](formulae-old-intel-bottle.md).

## Casks (homebrew-cask)

### UNAVAILABLE_ON_INTEL (170)

- `vorssaint`: depends_on arch: :arm64
- `raycast`: depends_on arch: :arm64
- `lm-studio`: depends_on arch: :arm64
- `whisky`: depends_on arch: :arm64
- `google-gemini`: depends_on arch: :arm64
- `comfy`: depends_on arch: :arm64
- `anaconda`: disabled on Intel: {':date': '2026-12-10', ':because':
  ':discontinued'}; deprecated on Intel: {':date': '2025-12-10', ':because':
  ':discontinued'}; Intel pinned to 2025.06-1 (ARM 2026.07-1)
- `sonarqube-cli`: depends_on arch: :arm64
- `opensuperwhisper`: depends_on arch: :arm64
- `onyx`: Intel requires macOS [':big_sur', ':monterey', ':ventura', ':sonoma',
  ':sequoia', ':tahoe', ':golden_gate']
- `kde-connect`: depends_on arch: :arm64
- `chatgpt-classic`: depends_on arch: :arm64
- `thaw@beta`: no Intel macOS in supported_platforms; Intel requires macOS
  :golden_gate
- `deepseek-harness`: depends_on arch: :arm64
- `lm-studio-bionic`: depends_on arch: :arm64
- `thebrowsercompany-dia`: depends_on arch: :arm64
- `omniwm`: depends_on arch: :arm64
- `parallels`: depends_on arch: :arm64
- `darktable`: depends_on arch: :arm64
- `playcover-community`: depends_on arch: :arm64
- `llama-app`: depends_on arch: :arm64
- `exo`: depends_on arch: :arm64
- `unsloth`: depends_on arch: :arm64
- `battery`: depends_on arch: :arm64
- `kimi`: depends_on arch: :arm64
- `bluestacks`: depends_on arch: :arm64
- `virtualbuddy`: depends_on arch: :arm64
- `bettercapture`: depends_on arch: :arm64
- `osaurus`: depends_on arch: :arm64
- `macparakeet`: depends_on arch: :arm64
- `neodisk`: depends_on arch: :arm64
- `highball`: depends_on arch: :arm64
- `headroom`: depends_on arch: :arm64
- `blender@lts`: depends_on arch: :arm64
- `gamehub`: depends_on arch: :arm64
- `muesli`: depends_on arch: :arm64
- `meetily`: depends_on arch: :arm64
- `kitlangton-hex`: depends_on arch: :arm64
- `vicinae`: depends_on arch: :arm64
- `mumuplayer`: depends_on arch: :arm64
- `siliconscope`: depends_on arch: :arm64
- `airstats`: depends_on arch: :arm64
- `davit`: depends_on arch: :arm64
- `mac-performance-monitor`: depends_on arch: :arm64
- `chatgpt-atlas`: depends_on arch: :arm64
- `paper-design`: depends_on arch: :arm64
- `bb`: depends_on arch: :arm64
- `vmlx`: depends_on arch: :arm64
- `nativ`: depends_on arch: :arm64
- `ghostex`: depends_on arch: :arm64
- `batfi`: depends_on arch: :arm64
- `mdhero`: depends_on arch: :arm64
- `brewy`: depends_on arch: :arm64
- `mythic`: depends_on arch: :arm64
- `zed-delta`: depends_on arch: :arm64
- `lemonade-server`: depends_on arch: :arm64
- `palmier-pro`: depends_on arch: :arm64
- `swiftcord`: depends_on arch: :arm64
- `mirai`: depends_on arch: :arm64
- `canario`: depends_on arch: :arm64
- `manus`: depends_on arch: :arm64
- `koharu`: depends_on arch: :arm64
- `raycast-glaze`: depends_on arch: :arm64
- `crest-browser`: depends_on arch: :arm64
- `adrive`: disabled on Intel: {':date': '2026-09-01', ':because':
  ':fails_gatekeeper_check'}
- `spatial`: depends_on arch: :arm64
- `claudoscope`: depends_on arch: :arm64
- `julia-app`: no Intel macOS in supported_platforms; Intel requires macOS
  :golden_gate
- `gopher64`: depends_on arch: :arm64
- `pulse`: depends_on arch: :arm64
- `arcbox`: depends_on arch: :arm64
- `reolink`: depends_on arch: :arm64
- `silentknight`: depends_on arch: :arm64
- `feedflow`: depends_on arch: :arm64
- `gloomberb`: depends_on arch: :arm64
- `screenkite`: depends_on arch: :arm64
- `biscotti`: depends_on arch: :arm64
- `jasp`: disabled on Intel: {':date': '2026-09-01', ':because':
  ':fails_gatekeeper_check'}
- `deeper`: Intel requires macOS [':big_sur', ':monterey', ':ventura',
  ':sonoma', ':sequoia', ':tahoe', ':golden_gate']
- `ltx-desktop`: depends_on arch: :arm64
- `koe`: depends_on arch: :arm64
- `stability-matrix`: depends_on arch: :arm64
- `pencil2d`: disabled on Intel: {':date': '2026-09-01', ':because':
  ':fails_gatekeeper_check'}; Intel pinned to 0.7.0 (ARM 0.7.2)
- `orbit`: depends_on arch: :arm64
- `tcp-viewer`: depends_on arch: :arm64
- `mochi-diffusion`: depends_on arch: :arm64
- `contour`: disabled on Intel: {':date': '2026-09-01', ':because':
  ':fails_gatekeeper_check'}; Intel pinned to 0.6.1.7494 (ARM 0.7.0.8982)
- `maintenance`: Intel requires macOS [':big_sur', ':monterey', ':ventura',
  ':sonoma', ':sequoia', ':tahoe', ':golden_gate']
- `vibetunnel`: depends_on arch: :arm64
- `waku`: depends_on arch: :arm64
- `ghostpepper`: depends_on arch: :arm64
- `virtualbuddy@beta`: depends_on arch: :arm64
- `fido2-manage`: depends_on arch: :arm64
- `onyx@beta`: no Intel macOS in supported_platforms; Intel requires macOS
  :golden_gate
- `pale-moon`: depends_on arch: :arm64
- `meetingrecorder`: depends_on arch: :arm64
- `topaz-video`: depends_on arch: :arm64
- `ghostvm`: depends_on arch: :arm64
- `stremioservice`: depends_on arch: :arm64
- `yap-app`: depends_on arch: :arm64
- `hytale`: depends_on arch: :arm64
- `manus-cue`: depends_on arch: :arm64
- `djv`: depends_on arch: :arm64
- `linqpad`: depends_on arch: :arm64
- `local-studio`: depends_on arch: :arm64
- `bettermacwidgets`: depends_on arch: :arm64
- `riverside-studio`: depends_on arch: :arm64
- `hagimimonitordirect`: depends_on arch: :arm64
- `agentiloop-agent`: depends_on arch: :arm64
- `cleeen`: depends_on arch: :arm64
- `capsomnia`: depends_on arch: :arm64
- `cmtrace-open`: depends_on arch: :arm64
- `agentide`: depends_on arch: :arm64
- `replit`: depends_on arch: :arm64
- `ds4-control`: depends_on arch: :arm64
- `kameleo`: depends_on arch: :arm64
- `monet`: depends_on arch: :arm64
- `status`: depends_on arch: :arm64
- `oclint`: depends_on arch: :arm64
- `tencent-yingyongbao`: depends_on arch: :arm64
- `tight-studio`: depends_on arch: :arm64
- `keyscreen`: depends_on arch: :arm64
- `viable`: depends_on arch: :arm64
- `nteract`: depends_on arch: :arm64
- `arm-performance-libraries`: depends_on arch: :arm64
- `codexmonitor`: depends_on arch: :arm64
- `ideashell`: depends_on arch: :arm64
- `meridiem`: depends_on arch: :arm64
- `meetmic`: depends_on arch: :arm64
- `swama`: depends_on arch: :arm64
- `trimmy`: depends_on arch: :arm64
- `subtitle-studio`: depends_on arch: :arm64
- `amethyst-nostr`: depends_on arch: :arm64
- `retrace`: depends_on arch: :arm64
- `clarify`: depends_on arch: :arm64
- `kvirc`: depends_on arch: :arm64
- `mongrel`: depends_on arch: :arm64
- `plamo-translate`: depends_on arch: :arm64
- `facescreen`: depends_on arch: :arm64
- `taperlabs-shadow`: depends_on arch: :arm64
- `android-performance-analyzer`: depends_on arch: :arm64
- `istatistica-core`: depends_on arch: :arm64
- `hol-guard`: depends_on arch: :arm64
- `koreader`: no Intel macOS in supported_platforms
- `minmaxcal`: depends_on arch: :arm64
- `cncjs`: depends_on arch: :arm64
- `nightshade`: depends_on arch: :arm64
- `relay`: depends_on arch: :arm64
- `wsl-manager`: depends_on arch: :arm64
- `audius`: depends_on arch: :arm64
- `focu`: depends_on arch: :arm64
- `vimy`: depends_on arch: :arm64
- `saega`: depends_on arch: :arm64
- `pimosa`: depends_on arch: :arm64
- `thedesk`: depends_on arch: :arm64
- `zeal`: no Intel macOS in supported_platforms
- `cilicon`: depends_on arch: :arm64
- `gitdifferent`: depends_on arch: :arm64
- `liviable`: depends_on arch: :arm64
- `serverbuddy`: depends_on arch: :arm64
- `vrampro`: depends_on arch: :arm64
- `bitmuse`: depends_on arch: :arm64
- `playcover-community@beta`: depends_on arch: :arm64
- `procexp`: depends_on arch: :arm64
- `todometer`: disabled on Intel: {':date': '2026-09-01', ':because':
  ':fails_gatekeeper_check'}; Intel pinned to 2.0.1 (ARM 3.0.3)
- `viables`: depends_on arch: :arm64
- `ideashell-cn`: depends_on arch: :arm64
- `jetdrive-toolbox`: depends_on arch: :arm64
- `retrospective`: depends_on arch: :arm64
- `xit`: depends_on arch: :arm64

### INTEL_DEPRECATED (3)

- `blender`: deprecated on Intel: {':date': '2027-07-01', ':because':
  ':unsupported'}; Intel pinned to 4.5.14 (ARM 5.2.2)
- `donut`: deprecated on Intel: {':date': '2026-10-15', ':because':
  ':discontinued'}; Intel pinned to 0.33.0 (ARM 0.34.0)
- `craft-agents`: deprecated on Intel: {':date': '2026-06-12', ':because':
  ':discontinued'}; Intel pinned to 0.10.1 (ARM 0.15.4)

### INTEL_VERSION_PINNED (76)

- `ngrok`: Intel pinned to 3.39.11,8QQF2ciKqxM,a (ARM 3.39.11,dy27whJwwmb,a)
- `temurin`: Intel pinned to 26.0.2.1,1 (ARM 27,35)
- `miniconda`: Intel pinned to py313_25.7.0-2 (ARM py314_26.9.3-0)
- `gcc-arm-embedded`: Intel pinned to 14.2.rel1 (ARM 15.3.rel2)
- `r-app`: Intel pinned to 4.6.1,big-sur (ARM 4.6.1,sonoma)
- `tencent-meeting`: Intel pinned to 3.47.2.407,270f990dec24a6387576fcce1f8dd2cd
  (ARM 3.47.2.407,8f792a0af699fd29e5a7f6b461a4c2ee)
- `feishu`: Intel pinned to 8.3.14,7a3dcae2 (ARM 8.3.14,5d428a73)
- `paraview`: Intel pinned to 6.2.0,MPI-OSX10.15-Python3.12 (ARM
  6.2.0,MPI-OSX11.0-Python3.12)
- `yandex`: Intel pinned to 26.8.3.1020,117474 (ARM 26.8.3.1016,117434)
- `conductor`: Intel pinned to 0.91.2,01M5AXS91BW6TN49P8GS6EE3WH (ARM
  0.91.2,01M5AXSJPPGXRRABBQ1AFXNYQ8)
- `cap`: Intel pinned to 0.6.1,01M5CGZ8TYVSNPKH5JGHQW73T6 (ARM
  0.6.1,01M5CGZ4SP1284TJD3KQZNZ67M)
- `stolendata-mpv`: Intel pinned to 0.39.0 (ARM 0.40.0)
- `horos`: Intel pinned to 4.0.0 (ARM 4.0.1)
- `gog-galaxy`: Intel pinned to 2.0.100.1 (ARM 2.1.10.56)
- `lark`: Intel pinned to 8.3.14,dbad7f44 (ARM 8.3.14,bca1e6e3)
- `wechatwork`: Intel pinned to 5.0.12.91300 (ARM 5.0.12.95037)
- `sapmachine-jdk`: Intel pinned to 24.0.2 (ARM 27.0.1)
- `keybase`: Intel pinned to 6.6.3,20260603140308,f60f2ff97e (ARM
  6.6.3,20260603142618,f60f2ff97e)
- `permute`: Intel pinned to 3.14.8,4018 (ARM 4.1,4173)
- `fing`: Intel pinned to 3.10.1 (ARM 4.0.3)
- `es-de`: Intel pinned to 3.5.0,357717755 (ARM 3.5.0,357717468)
- `ghdl`: Intel pinned to 5.1.1 (ARM 6.0.0)
- `graalvm-jdk@25`: Intel pinned to 25.0.1,8 (ARM 25.0.4,7)
- `chef-workstation`: Intel pinned to 25.9.1094,12 (ARM 25.14.2,14)
- `graalvm-jdk`: Intel pinned to 25.0.1 (ARM 25.0.4)
- `graalvm-jdk@21`: Intel pinned to 21.0.9,7 (ARM 21.0.12,7)
- `brave-browser@nightly`: Intel pinned to 1.99.35.0 (ARM 1.99.41.0)
- `multiviewer`: Intel pinned to 2.11.0,5akm1YQaEJuXqBa1YijUQl6jUPBCR58Q (ARM
  2.11.0,z9pfn5AVGH5-xWDQm4tWd-_d5qYMFSE0)
- `ovito`: Intel pinned to 3.12.0 (ARM 3.17.0)
- `texmaker`: Intel pinned to 5.1.4 (ARM 6.0.2)
- `gcc-aarch64-embedded`: Intel pinned to 14.2.rel1 (ARM 15.3.rel2)
- `voov-meeting`: Intel pinned to 3.43.0.510,09ec308a02c61e0ede83ffac486e5cea
  (ARM 3.43.0.510,676602c370071da9c30765f945f41b83)
- `atuin-desktop`: Intel pinned to 0.2.17 (ARM 0.2.20)
- `zspace`: Intel pinned to 2.45.2026082601,1789110734,082620 (ARM
  2.45.2026082601,1789110817,082619)
- `ibm-aspera-connect`: Intel pinned to 4.2.19.956-HEAD (ARM 4.2.13.820)
- `monarch`: Intel pinned to 0.7.14 (ARM 0.9.53)
- `monolingual`: Intel pinned to 1.8.2 (ARM 2.0.2)
- `taobao`: Intel pinned to 2.5.1 (ARM 2.1.0)
- `xtool-studio`: Intel pinned to
  1.2.11,110,86dfe506-dfa2-46d7-952f-126e743ab28b (ARM
  1.2.11,121,c518d71e-2d6a-4494-851f-8e61b8a76949)
- `codelite`: Intel pinned to 17.6.0 (ARM 18.4.0)
- `vlc@nightly`: Intel pinned to 4.0.0,20260831-0411,5dd4aebd (ARM
  4.0.0,20260831-0413,5dd4aebd)
- `coq-platform`: Intel pinned to 2023.11.0,8.18.2023.11 (ARM
  2025.01.0,8.20.2025.01)
- `java@beta`: Intel pinned to 27,22 (ARM 28,20)
- `visit`: Intel pinned to 3.4.2 (ARM 3.5.0)
- `brave-origin@nightly`: Intel pinned to 1.100.6.0 (ARM 1.100.7.0)
- `itau`: Intel pinned to 2.2.2.22 (ARM 2.3.2.22)
- `miniwol`: Intel pinned to 2.1.3 (ARM 2.1.4)
- `astah-uml`: Intel pinned to 10.1.0,9ceee1 (ARM 12.0.0,4fa570)
- `bcut`: Intel pinned to 3.11.24,23369604,2b551373e850489c924c4cbcf64aec97 (ARM
  3.11.24,23369602,a97c4192d11a838429fb9600044e67c8)
- `effect-house`: Intel pinned to 5.15.0,2408,09142026,104 (ARM
  5.15.0,0687,09142026,104)
- `texworks`: Intel pinned to 0.6.11,202602100758,7951fd8 (ARM
  0.6.10,202502131353,7380941)
- `jasper-app`: Intel pinned to 1.1.2 (ARM 2.0.0)
- `ubports-installer`: Intel pinned to 0.11.2 (ARM 0.11.1)
- `dyalog`: Intel pinned to 19.0.50027 (ARM 20.0.53963)
- `carbide-create`: Intel pinned to 842 (ARM 876)
- `ossia-score`: Intel pinned to 3.8.2 (ARM 3.9.0)
- `vimcal`: Intel pinned to 1.0.47 (ARM 1.0.48)
- `astah-professional`: Intel pinned to 10.1.0,9ceee1 (ARM 12.0.0,4fa570)
- `popo`: Intel pinned to 4.36.0,1791460584673 (ARM 4.36.0,1791460833516)
- `wings3d`: Intel pinned to 2.3 (ARM 2.4.1)
- `data-science-studio`: Intel pinned to 14.0.3 (ARM 15.0.1)
- `automattic-texts`: Intel pinned to 0.84.17,a57e9370cb (ARM
  0.84.17,1306a54b77)
- `free-podcast-transcription`: Intel pinned to 0.0.4,20230417.153610 (ARM
  0.0.4,20230417.152948)
- `spaceradar`: Intel pinned to 6.0.0 (ARM 6.0.1)
- `lookingglassstudio`: Intel pinned to 1.6.0 (ARM 1.7.1)
- `ovito-pro`: Intel pinned to 3.12.0 (ARM 3.17.0)
- `tng-digital-mini-program-studio`: Intel pinned to 3.9.1048 (ARM 3.9.1047)
- `voiden@beta`: Intel pinned to 2.3.1 (ARM 2.3.3-beta.1)
- `bison-wallet`: Intel pinned to 1.0.4 (ARM 1.0.5)
- `icestudio`: Intel pinned to 0.11 (ARM 0.12)
- `quail`: Intel pinned to 2.4.0 (ARM 3.0.0)
- `whale`: Intel pinned to 2.4.0 (ARM 3.0.0)
- `x-moto`: Intel pinned to 0.6.2 (ARM 0.6.3)
- `liclipse`: Intel pinned to 12.0.1,b8h7wnjqtalkxls (ARM
  12.0.1,o9ccnc5f0ks4dgq)
- `yealink-meeting`: Intel pinned to 4.7.42,b655b57e9b9b15c70dca10ad4085a2f0
  (ARM 4.7.43,03989b48eb2ca4178a3aa1e3c9dc0ec3)
- `avast-secure-browser`: Intel pinned to 139.0.6698.68 (ARM 139.0.6697.68)

### INTEL_OLD_MACOS_ONLY (2)

- `apple-hewlett-packard-printer-drivers`: Intel only up to big_sur, monterey,
  sonoma, ventura
- `mailtrackerblocker`: Intel only up to big_sur, monterey, ventura

## Taps de terceiros

- `anomalyco/tap/hex` (anomalyco/tap): depends_on arch: :arm64
- `aws/tap/cbmc-starter-kit` (aws/tap): bottles only for ARM/Linux:
  arm64_sonoma, x86_64_linux
- `aws/tap/cbmc-viewer` (aws/tap): bottles only for ARM/Linux: arm64_sonoma,
  x86_64_linux
- `blendle/blendle/bnl` (blendle/blendle): fails to load: Error: undefined
  method 'undent' for an instance of String
- `goreleaser/tap/goreleaser-pro@2` (goreleaser/tap): disabled: the cask should
  be used now instead
- `slp/krunkit/krunkit` (slp/krunkit): depends_on arch: :arm64; bottles only for
  ARM/Linux: arm64_sequoia
- `slp/krunkit/libkrun-efi` (slp/krunkit): depends_on arch: :arm64; bottles only
  for ARM/Linux: arm64_sequoia
- `slp/krunkit/virglrenderer` (slp/krunkit): bottles only for ARM/Linux:
  arm64_sequoia

## Removidos do core/cask desde 2025-09

- 1071 arquivos removidos; quase todos por EOL/abandono, não por Intel.
- Eram arm64-only quando removidos: `tart`, `llamabarn`, `comfyui`,
  `brightintosh`, `donut@nightly`, `manymc`, `container`.
