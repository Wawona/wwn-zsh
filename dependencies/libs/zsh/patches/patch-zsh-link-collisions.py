#!/usr/bin/env python3
"""Rename zsh globals that collide with xkbcommon, neovim, and openssh at app link."""
from __future__ import annotations

import re
import sys
from pathlib import Path

# (path, [(old, new), ...]) — word-boundary renames on C identifiers only.
RENAMES: list[tuple[str, list[tuple[str, str]]]] = [
    ("Src/compmatch.c", [("pattern_match", "wwn_zsh_pattern_match")]),
    ("Src/exec.c", [("parse_string", "wwn_zsh_parse_string")]),
    ("Src/init.c", [("source", "wwn_zsh_source")]),
]


def rename_identifiers(text: str, pairs: list[tuple[str, str]]) -> str:
    for old, new in pairs:
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def main() -> int:
    root = Path.cwd()
    changed = 0
    for rel, pairs in RENAMES:
        path = root / rel
        if not path.is_file():
            print(f"warning: {rel} missing; skipping link-collision renames", file=sys.stderr)
            continue
        original = path.read_text(encoding="utf-8")
        patched = rename_identifiers(original, pairs)
        if patched != original:
            path.write_text(patched, encoding="utf-8")
            changed += 1
            print(f"patched {rel} for link-collision-safe symbols", file=sys.stderr)
    if changed == 0:
        print("no zsh link-collision patches applied", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
