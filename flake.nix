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

      mkAndroidSDK = system: pkgs:
        let
          androidConfig = import "${wwn-toolchain}/dependencies/android/sdk-config.nix" {
            inherit system;
            lib = pkgs.lib;
          };
          androidComposition = pkgs.androidenv.composeAndroidPackages {
            cmdLineToolsVersion = "latest";
            platformToolsVersion = "latest";
            buildToolsVersions = [ androidConfig.buildToolsVersion ];
            platformVersions = [ (toString androidConfig.compileSdk) ];
            abiVersions = [ androidConfig.hostEmulatorAbi ];
            systemImageTypes = [ "google_apis_playstore" ];
            includeEmulator = androidConfig.emulatorSupported;
            includeSystemImages = androidConfig.emulatorSupported;
            includeNDK = true;
            includeCmake = true;
            ndkVersions = [ androidConfig.ndkVersion ];
            cmakeVersions = [ androidConfig.cmakeVersion ];
            useGoogleAPIs = false;
          };
          sdkRoot = "${androidComposition.androidsdk}/libexec/android-sdk";
        in {
          androidsdk = androidComposition.androidsdk;
          inherit sdkRoot;
          platformTools = androidComposition.platform-tools;
          cmdlineTools = androidComposition.androidsdk;
          buildTools = "${sdkRoot}/build-tools/${androidConfig.buildToolsVersion}";
          cmake = "${sdkRoot}/cmake/${androidConfig.cmakeVersion}";
          ndk = "${sdkRoot}/ndk/${androidConfig.ndkVersion}";
          emulator =
            if androidConfig.emulatorSupported then
              androidComposition.emulator
            else
              androidComposition.androidsdk;
          systemImage =
            "${sdkRoot}/system-images/android-${toString androidConfig.compileSdk}/google_apis_playstore/${androidConfig.hostEmulatorAbi}";
          androidSdkPackages = { };
          inherit androidConfig;
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
          androidSDK = mkAndroidSDK system pkgs;
          androidAllowExperimentalFallback =
            (builtins.getEnv "WAWONA_ANDROID_EXPERIMENTAL_FALLBACK") == "1"
            || builtins.elem system [ "aarch64-darwin" "aarch64-linux" ];
          tc = mkToolchains {
            inherit pkgs androidSDK androidAllowExperimentalFallback;
            pkgsAndroid = pkgs.pkgsCross.aarch64-android;
            registry = baseRegistry // self.registryFragment;
          };
          isDarwin = builtins.elem system darwinSystems;
        in
        {
          zsh-android = tc.buildForAndroid "zsh" { };
        } // (if isDarwin then {
          zsh-ios = tc.buildForIOS "zsh" { };
          zsh-framework-ios = tc.buildForIOS "zsh-framework" { };
          wawona-rootfs-ios = tc.buildForIOS "wawona-rootfs" { };
        } else { }));

      formatter = forAll (system: (pkgsFor system).nixfmt-rfc-style);
    };
}
