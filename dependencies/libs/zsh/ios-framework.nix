# App Store–compliant zsh packaging for iOS: static Mach-O inside a nested
# zsh.framework (AMFI nested-code site), separate from wawona-rootfs data files.
{
  lib,
  pkgs,
  buildModule,
  simulator ? false,
}:

let
  zsh = buildModule.buildForIOS "zsh" { inherit simulator; };
  infoPlist =
    if simulator then ./framework/Info-simulator.plist else ./framework/Info.plist;
in
pkgs.runCommand "zsh-framework-ios${if simulator then "-sim" else ""}"
  {
    inherit zsh;
  }
  ''
    set -euo pipefail
    fw="$out/zsh.framework"
    mkdir -p "$fw/Resources/share/zsh"
    cp "$zsh/bin/zsh" "$fw/zsh"
    chmod 755 "$fw/zsh"
    cp ${infoPlist} "$fw/Info.plist"
    if [ -d "$zsh/share/zsh" ]; then
      cp -R "$zsh/share/zsh/." "$fw/Resources/share/zsh/"
    fi
    strip "$fw/zsh" 2>/dev/null || true
  ''
