{
  description = "wwn-zsh: Wawona's bundled zsh fork, cross-compiled for Apple platforms (App-Store-compliant in-process Mach-O inside zsh.framework) and Android, plus the Wawona iOS RootFS.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    rust-overlay.url = "github:oxalica/rust-overlay";
    rust-overlay.inputs.nixpkgs.follows = "nixpkgs";
    wwn-toolchain.url = "github:Wawona/wwn-toolchain";
    wwn-toolchain.inputs.nixpkgs.follows = "nixpkgs";
    wwn-toolchain.inputs.rust-overlay.follows = "rust-overlay";
  };

  outputs = { self, nixpkgs, rust-overlay, wwn-toolchain, ... }:
    let
      darwinSystems = [ "x86_64-darwin" "aarch64-darwin" ];
      linuxSystems = [ "x86_64-linux" "aarch64-linux" ];
      allSystems = darwinSystems ++ linuxSystems;
      forAll = nixpkgs.lib.genAttrs allSystems;
      inherit (wwn-toolchain.lib) withPlatformVariants baseRegistry mkToolchains;

      pkgsFor = system: import nixpkgs {
        inherit system;
        overlays = [ (import rust-overlay) ];
        config = { allowUnfree = true; allowUnsupportedSystem = true; android_sdk.accept_license = true; };
      };

      zshDir = ./dependencies/libs/zsh;
    in
    {
      registryFragment = {
        zsh = withPlatformVariants {
          android = zshDir + "/android.nix";
          ios = zshDir + "/ios.nix";
          ipados = zshDir + "/ios.nix";
          tvos = zshDir + "/ios.nix";
          visionos = zshDir + "/ios.nix";
          watchos = zshDir + "/ios.nix";
          macos = null;
        };
        "zsh-framework" = withPlatformVariants {
          android = null;
          ios = zshDir + "/ios-framework.nix";
          ipados = zshDir + "/ios-framework.nix";
          tvos = zshDir + "/ios-framework.nix";
          visionos = zshDir + "/ios-framework.nix";
          watchos = zshDir + "/ios-framework.nix";
          macos = null;
        };
        "wawona-rootfs" = withPlatformVariants {
          android = null;
          ios = ./dependencies/wawona/ios-rootfs.nix;
          ipados = ./dependencies/wawona/ios-rootfs.nix;
          tvos = ./dependencies/wawona/ios-rootfs.nix;
          visionos = ./dependencies/wawona/ios-rootfs.nix;
          watchos = ./dependencies/wawona/ios-rootfs.nix;
          macos = null;
        };
      };

      packages = forAll (system:
        let
          pkgs = pkgsFor system;
          tc = mkToolchains { inherit pkgs; registry = baseRegistry // self.registryFragment; };
          isDarwin = builtins.elem system darwinSystems;
        in
        (if isDarwin then {
          zsh-ios = tc.buildForIOS "zsh" { };
          zsh-framework-ios = tc.buildForIOS "zsh-framework" { };
          wawona-rootfs-ios = tc.buildForIOS "wawona-rootfs" { };
        } else { }));

      formatter = forAll (system: (pkgsFor system).nixfmt-rfc-style);
    };
}
