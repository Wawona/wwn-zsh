# zsh for iOS (Wawona)

Static, cross-compiled zsh for iPhone/iPad. Linked into the main app binary
as `libwawona-zsh.a` and started in-process via pthread from `wawona-pty`
(`wawona_zsh_main`), not `posix_spawn` or a nested framework bundle.

## Nix outputs

| Flake output | Artifact |
|---|---|
| `.#zsh-ios` | `lib/libwawona-zsh.a`, `share/zsh/` |
| `.#zsh-ios-sim` | Simulator build |

Legacy `.#zsh-framework-ios` still builds a framework layout for experiments;
**Wawona no longer embeds it** — iOS installd rejects third-party nested
frameworks even with a valid Info.plist.

## Build flags

- **Static archive** — all zsh objects archived as `libwawona-zsh.a`; `main` renamed to `wawona_zsh_main`
- **termios** terminal driver — works with `wawona-pty` pipe fallback on iOS
- **Fake TTY shim** — when `posix_openpt` is blocked, socketpair + `WAWONA_PTY_FAKE_TTY` interposes `isatty`/`tcgetattr` so interactive zsh works
- No `/etc`, no PAM, no getpwuid — sandbox-friendly

## Runtime

`WWNRootfsManager` sets `WAWONA_ZSH_IN_PROCESS=1` and `WAWONA_SHELL=/usr/bin/zsh`.
Share files live under `wawona-rootfs/usr/share/zsh/` in the app bundle.

Only in-process zsh is allowed in `wawona-pty` on Apple mobile when
`WAWONA_ZSH_IN_PROCESS` is set.
