# wwn-zsh

Wawona's bundled `zsh` fork, cross-compiled for the full Apple ecosystem
(iOS/iPadOS/tvOS/watchOS/visionOS) and Android, plus the Wawona iOS **RootFS**.

App-Store compliance is structural: zsh is built as a static Mach-O linked
in-process and packaged inside a nested `zsh.framework` (the AMFI nested-code
site), with no `fork`/`exec` of system tools — the exec hook is redirected to
in-process uutils-coreutils. See `dependencies/libs/zsh/patches/patch-zsh-exec.py`
and `.github/scripts/verify-zsh-ios-patches.py`.

Patch-overlay model: zsh source comes from `pkgs.zsh.src` (nixpkgs) and is patched
at build time. Built with [wwn-toolchain](https://github.com/Wawona/wwn-toolchain).

## Use

```nix
inputs.wwn-zsh.url = "github:Wawona/wwn-zsh";
registry = wwn-toolchain.lib.baseRegistry // wwn-zsh.registryFragment;
```

Fragment: `zsh` (static archive), `zsh-framework` (App-Store packaging),
`wawona-rootfs` (iOS RootFS data layout). The `wawona_zsh_main` symbol is resolved
at the final Wawona app link (weak externs), so app repos do not depend on this one.

## Standalone build

```sh
nix build .#zsh-ios
nix build .#zsh-framework-ios
nix build .#wawona-rootfs-ios
```

## License

MIT for the Wawona Nix packaging / patches (see `LICENSE`). zsh itself is under the
zsh license; its source is fetched from nixpkgs at build time.
