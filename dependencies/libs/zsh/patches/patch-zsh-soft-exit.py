#!/usr/bin/env python3
"""Route zsh's committed process exit through wwn_zsh_soft_exit (Apple mobile).

Do not #define exit/_exit — those macros mangle zsh's _((...)) prototypes in
*.epro and break unistd.h when force-included before config.h. Only zexit()'s
final exit/_exit calls tear down the host from an in-process shell.
"""
from __future__ import annotations

from pathlib import Path

DECL = (
    "/* Wawona: soft-exit for in-process Apple mobile (libwwn-pty). */\n"
    "extern void wwn_zsh_soft_exit(int status) "
    "__attribute__((__noreturn__));\n"
)

OLD = """\
    if (mypid != getpid())
	_exit(exit_val);
    else
	exit(exit_val);
}
"""

NEW = """\
    if (mypid != getpid())
	wwn_zsh_soft_exit(exit_val);
    else
	wwn_zsh_soft_exit(exit_val);
}
"""


def main() -> None:
    path = Path("Src/builtin.c")
    text = path.read_text()
    if "wwn_zsh_soft_exit" in text:
        print("patch-zsh-soft-exit: already applied")
        return
    if OLD not in text:
        raise SystemExit(
            "patch-zsh-soft-exit: zexit exit/_exit tail not found in Src/builtin.c"
        )
    text = text.replace(OLD, NEW, 1)
    # Insert declaration after the first #include block near the top.
    marker = '#include "zsh.mdh"\n'
    if marker in text:
        text = text.replace(marker, marker + DECL, 1)
    else:
        text = DECL + text
    path.write_text(text)
    print("patch-zsh-soft-exit: patched Src/builtin.c zexit → wwn_zsh_soft_exit")


if __name__ == "__main__":
    main()
