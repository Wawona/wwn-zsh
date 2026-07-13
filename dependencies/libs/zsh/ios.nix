{
  lib,
  pkgs,
  buildPackages,
  iosToolchain,
  simulator ? false,
  # Injected by wwn-toolchain: its source tree, used to import
  # apple-mobile-platform.nix (was ../../toolchains/apple-mobile-platform.nix).
  toolchainSrc ? null,
}:

let
  platformInfo = import "${toolchainSrc}/dependencies/toolchains/apple-mobile-platform.nix";
  mobile = platformInfo { inherit iosToolchain simulator; };
  src = pkgs.zsh.src;
in
pkgs.stdenv.mkDerivation {
  name = "zsh-ios${if simulator then "-sim" else ""}";
  inherit src;

  __noChroot = true;

  nativeBuildInputs = with buildPackages; [
    autoconf
    automake
    python3
  ];

  preConfigure = ''
    ${iosToolchain.mkIOSBuildEnv { inherit simulator; minVersion = mobile.minVersion; }}
    unset MACOSX_DEPLOYMENT_TARGET IPHONEOS_DEPLOYMENT_TARGET
    export NIX_CFLAGS_COMPILE=""
    export NIX_LDFLAGS=""
    cp ${./termcap-stub.h} termcap-stub.h
    export CC="$CC"
    export CXX="$CXX"
    export CFLAGS="-arch arm64 -isysroot $SDKROOT ${mobile.minVerFlag} -fPIC -O2"
    export LDFLAGS="-arch arm64 -isysroot $SDKROOT ${mobile.minVerFlag}"
  '';

  configurePhase = ''
    runHook preConfigure
    AR="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/ar"
    cp ${./termcap-stub.c} termcap-stub.c
    $CC -c termcap-stub.c $CFLAGS -o termcap-stub.o
    $AR rcs libtermcap.a termcap-stub.o
    cp libtermcap.a libcurses.a
    export LDFLAGS="-L$PWD $LDFLAGS"
    export LIBS="-L$PWD $LIBS"
    export ac_cv_search_tigetstr=-lcurses
    export ac_cv_search_tigetflag=-lcurses
    export ac_cv_search_tgetent=-lcurses
    ./configure \
      --host=aarch64-apple-darwin \
      --build=${buildPackages.stdenv.hostPlatform.config} \
      --prefix=$out \
      --enable-static \
      --disable-dynamic \
      --disable-nls \
      --disable-gdbm \
      --disable-pcre \
      --disable-cap \
      --disable-etcdir \
      --disable-ldconfig \
      --with-tcset=termios \
      ac_cv_func_getpwuid=no \
      ac_cv_func_getpwnam=no \
      ac_cv_func_getgrgid=no \
      ac_cv_func_getgrnam=no \
      zsh_cv_sys_dev_fd=no \
      zsh_cv_sys_dev_fd_63=no
    runHook postConfigure
    echo '#define TGOTO_PROTO_MISSING 1' >> config.h
  '';

  buildPhase = ''
    runHook preBuild
    # App Store compliant in-process external-command dispatch: rewrite the
    # external-command path in Src/exec.c to call wawona_dispatch_inprocess
    # (resolved at final app link from libwwn-pty.a) instead of fork/exec.
    # Runs after ./configure (exec.c is static source) and before make.
    python3 ${./patches/patch-zsh-exec.py}
    # Permanent link-collision renames (xkbcommon/neovim/openssh symbol overlap).
    python3 ${./patches/patch-zsh-link-collisions.py}
    cat >> config.h <<'EOF'
#define parse_string wwn_zsh_parse_string
#define source wwn_zsh_source
#define pattern_match wwn_zsh_pattern_match
EOF
    $CC -c ${./wawona-dispatch-link-stubs.c} $CFLAGS -o "$PWD/wawona-dispatch-link-stubs.o"
    make -C Src -j''${NIX_BUILD_CORES:-4} LIBS="$LIBS $PWD/wawona-dispatch-link-stubs.o -L$PWD -lcurses -liconv" zsh
    cd Src
    AR="$DEVELOPER_DIR/Toolchains/XcodeDefault.xctoolchain/usr/bin/ar"
    echo '#define main wawona_zsh_main' > ../main_rename.h
    $CC -include ../main_rename.h -c main.c $CFLAGS -o main_wwn.o
    modobjs=$(cat stamp-modobjs | sed 's/\<main\.o\>/main_wwn.o/g')
    $AR rcs ../libwawona-zsh.a ../termcap-stub.o main_wwn.o $modobjs
    cd ..
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/lib $out/share/zsh
    cp libwawona-zsh.a $out/lib/
    # Autoloadable shell + completion functions for fpath. Completion holds
    # compinit and the _* completers; Functions holds prompts/zle/etc. These
    # are source-tree dirs (present regardless of `make zsh`). .zshenv adds
    # every directory under here to fpath, so the exact layout is not critical.
    for subdir in Functions Completion Misc; do
      if [ -d "./$subdir" ]; then
        cp -R "./$subdir" $out/share/zsh/
      fi
    done
    if [ -d "./Etc" ]; then
      cp -R "./Etc" $out/share/zsh/
    fi
    runHook postInstall
  '';
}
