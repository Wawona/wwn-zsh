#!/usr/bin/env python3
"""Patch zsh Src/exec.c so external commands in the in-process safe subset run
WITHOUT fork/exec on the Apple sandbox (App Store compliant).

Strategy (mirrors how zsh already runs builtins in-process):
  1. At the fork-decision point in execcmd_exec(), if the command is a plain
     external simple command whose argv[0] basename is dispatchable
     (wawona_dispatch_can_handle), set a local flag `wwn_inproc`.
  2. Guard the fork so `wwn_inproc` commands do NOT fork, and add an else-if so
     they do NOT take the fake-exec (entersubsh + execve-replace) path either.
  3. Let zsh apply io redirections into its `save` table as usual, then at the
     point it would call execute() (which execve's), instead call
     wawona_dispatch_inprocess(), restore fds via fixfds(save), and `goto done`
     exactly like the builtin path.

The patch is anchor-based and idempotent. If an anchor is missing (upstream zsh
drift), it exits non-zero so the build fails loudly. Pinned against zsh 5.9.1.
"""
import sys
from pathlib import Path

EXEC_C = "Src/exec.c"
INIT_C = "Src/init.c"


def fail(msg: str):
    sys.stderr.write("patch-zsh-exec.py: " + msg + "\n")
    sys.exit(1)


def patch_ios_init_io(src: str) -> str:
    if "wwn_pty_ios_note_init_io();" in src:
        return src
    anchor = """    /* We will only use zle if shell is interactive, *
     * SHTTY != -1, and shout != 0                   */
    if (interact) {
	init_shout();
	if(!SHTTY || !shout)
	    opts[USEZLE] = 0;
    } else
	opts[USEZLE] = 0;

    /* If interactive, make sure the shell is in the foreground and is the
     * process group leader.
     */"""
    patch = """    /* We will only use zle if shell is interactive, *
     * SHTTY != -1, and shout != 0                   */
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH)
    if (interact) {
	/*
	 * wawona-pty: stdout is the weston display socket; keyboard bytes are
	 * injected into a separate stdin pipe.  Stock init_io() often sets SHTTY
	 * from stdout (stdin is read-only so rdwrtty(0) fails); ZLE then poll(2)s
	 * the display socket and never sees injected input.  Route tty I/O through
	 * stdin (read) + stdout (write); Zle/zle_main.c also reads WWN_ZLE_INFD.
	 */
	if (SHTTY != -1 && SHTTY != 0)
	    zclose(SHTTY);
	SHTTY = movefd(dup(0));
	zsfree(ttystrname);
	ttystrname = ztrdup("wwn-pty");
	if (shout && shout != stderr && shout != stdout)
	    fclose(shout);
	shout = stdout;
	setvbuf(stdout, NULL, _IONBF, 0);
	if (SHTTY == -1 || !shout)
	    opts[USEZLE] = 0;
	else {
	    gettyinfo(&shttyinfo);
	    opts[USEZLE] = 1;
	}
	wwn_pty_ios_note_init_io();
    } else
	opts[USEZLE] = 0;
#else
    if (interact) {
	init_shout();
	if(!SHTTY || !shout)
	    opts[USEZLE] = 0;
    } else
	opts[USEZLE] = 0;
#endif

    /* If interactive, make sure the shell is in the foreground and is the
     * process group leader.
     */"""
    if anchor not in src:
        fail("init_io() tail anchor missing in init.c")
    return src.replace(anchor, patch, 1)


def patch_ios_init_prologue(src: str) -> str:
    if "wwn_pty_ios_note_init_io(void)" in src:
        return src
    anchor = '#include "zsh.mdh"\n\n'
    if anchor not in src:
        fail("init.c include anchor missing")
    prologue = anchor + """#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH)
extern void wwn_pty_ios_note_init_io(void);
extern void wwn_pty_ios_shell_init_done(void);
#endif

"""
    return src.replace(anchor, prologue, 1)


def patch_ios_zle_input(src: str, path_name: str) -> str:
    if "WWN_ZLE_INFD" in src:
        return src
    anchor = '#include "zle.mdh"\n'
    if anchor not in src:
        fail(f"{path_name} zle.mdh anchor missing")
    hdr = anchor + """#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH)
#define WWN_ZLE_INFD 0
#else
#define WWN_ZLE_INFD SHTTY
#endif

"""
    src = src.replace(anchor, hdr, 1)
    src = src.replace("read(SHTTY, cptr", "read(WWN_ZLE_INFD, cptr")
    src = src.replace("fds[0].fd = SHTTY", "fds[0].fd = WWN_ZLE_INFD")
    src = src.replace("pfd.fd = SHTTY", "pfd.fd = WWN_ZLE_INFD")
    src = src.replace("ioctl(SHTTY, FIONREAD", "ioctl(WWN_ZLE_INFD, FIONREAD")
    return src


def patch_ios_zle_files() -> None:
    for rel in ("Src/Zle/zle_main.c", "Src/Zle/zle_utils.c"):
        p = Path(rel)
        if not p.is_file():
            fail(f"{rel} not found (run from the zsh source root)")
        p.write_text(patch_ios_zle_input(p.read_text(), rel))
    print("patch-zsh-exec.py: applied iOS ZLE stdin routing (WWN_ZLE_INFD)")


def patch_ios_init_done() -> None:
    p = Path(INIT_C)
    if not p.is_file():
        fail(f"{INIT_C} not found (run from the zsh source root)")
    src = p.read_text()
    changed = False

    src = patch_ios_init_prologue(src)
    if "wwn_pty_ios_note_init_io(void)" in src:
        changed = True

    src = patch_ios_init_io(src)
    if "wwn_pty_ios_note_init_io();" in src:
        changed = True

    if "wwn_pty_ios_shell_init_done();" not in src:
        hook_anchor = "    run_init_scripts();\n    setupshin(runscript);"
        if hook_anchor not in src:
            fail("run_init_scripts hook anchor missing in init.c")
        hook = """    run_init_scripts();
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH)
    wwn_pty_ios_shell_init_done();
#endif
    setupshin(runscript);"""
        src = src.replace(hook_anchor, hook, 1)
        changed = True

    newuser_old = """	    if (interact) {
		/*
		 * Always attempt to load the newuser module to perform
		 * checks for new zsh users.  Don't care if we can't load it.
		 */
		if (!load_module("zsh/newuser", NULL, 1)) {
		    /* Unload it immediately. */
		    unload_named_module("zsh/newuser", "zsh", 1);
		}
	    }"""
    newuser_new = """	    if (interact) {
#if !(defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH))
		/*
		 * Always attempt to load the newuser module to perform
		 * checks for new zsh users.  Don't care if we can't load it.
		 */
		if (!load_module("zsh/newuser", NULL, 1)) {
		    /* Unload it immediately. */
		    unload_named_module("zsh/newuser", "zsh", 1);
		}
#endif
	    }"""
    if "#if !(defined(__APPLE__)" in src and "zsh/newuser" in src:
        pass
    elif newuser_old in src:
        src = src.replace(newuser_old, newuser_new, 1)
        changed = True
    elif newuser_old not in src:
        fail("newuser module anchor missing in init.c")

    if (not changed and "wwn_pty_ios_shell_init_done();" in src
            and "wwn_pty_ios_note_init_io();" in src):
        print("patch-zsh-exec.py: iOS init.c hooks already applied")
        return

    p.write_text(src)
    print("patch-zsh-exec.py: applied iOS init.c hooks (init_io SHTTY + shell-init-done)")


def patch_ios_compinit_guard(src: str) -> str:
    if "WAWONA_ENABLE_COMPINIT" in src:
        return src
    anchor = """getfpfunc(char *s, int *ksh, char **fdir, char **alt_path, int test_only)
{
    char **pp, buf[PATH_MAX+1];"""
    guard = """getfpfunc(char *s, int *ksh, char **fdir, char **alt_path, int test_only)
{
#ifdef WWN_INPROC_DISPATCH
    /* Parsing Completion/compinit faults on in-process iOS; require opt-in. */
    if (s && strcmp(s, "compinit") == 0 && getenv("WAWONA_ENABLE_COMPINIT") == NULL)
	return test_only ? NULL : &dummy_eprog;
#endif
    char **pp, buf[PATH_MAX+1];"""
    if anchor not in src:
        fail("getfpfunc anchor missing in exec.c")
    return src.replace(anchor, guard, 1)


def main():
    p = Path(EXEC_C)
    if not p.is_file():
        fail(f"{EXEC_C} not found (run from the zsh source root)")
    src = p.read_text()

    if "WWN_INPROC_DISPATCH" not in src:
        # 1) FFI declarations + feature macro, right after the exec.c prototypes.
        anchor_inc = '#include "exec.pro"'
        if anchor_inc not in src:
            fail('anchor `#include "exec.pro"` missing in exec.c')
        ffi = anchor_inc + """

#if defined(__APPLE__)
#include <TargetConditionals.h>
#endif
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH)
/* In-process external-command dispatch (no fork/exec). See wwn_pty.h.
 *
 * Implementations live in libwwn-pty.a (force_load'd at app link).  Do NOT
 * define weak fallbacks here: xcode-prebuild privatises libwawona-zsh.a via
 * ld -r + nmedit, which would turn weak stubs into local symbols and trap all
 * in-process exec inside the zsh archive (dispatch always NOT_HANDLED).
 * The throwaway `make -C Src zsh` link during the Nix build links libwwn-pty.a
 * so this translation unit only needs extern declarations. */
#define WWN_INPROC_DISPATCH 1
#define WWN_DISPATCH_NOT_HANDLED (-1)
extern char **environ;
extern int wawona_dispatch_can_handle(const char *argv0);
extern int wawona_dispatch_inprocess(const char *path,
                                    char *const argv[],
                                    char *const envp[]);
extern void wwn_pty_ios_shell_init_done(void);
extern void wwn_pty_ios_note_init_io(void);
#endif
"""
        src = src.replace(anchor_inc, ffi, 1)

        # 2) Local flag in execcmd_exec().
        anchor_decl = "    int is_shfunc = 0, is_builtin = 0, is_exec = 0, use_defpath = 0;"
        if anchor_decl not in src:
            fail("execcmd_exec local-decl anchor missing")
        src = src.replace(
            anchor_decl,
            anchor_decl + "\n#ifdef WWN_INPROC_DISPATCH\n    int wwn_inproc = 0;\n#endif",
            1,
        )

        # 3) Decide wwn_inproc right after is_cursh is computed.
        anchor_cursh = (
            "    /* This is nonzero if the command is a current shell procedure? */\n"
            "    is_cursh = (is_builtin || is_shfunc || nullexec || type >= WC_CURSH);"
        )
        if anchor_cursh not in src:
            fail("is_cursh anchor missing")
        src = src.replace(
            anchor_cursh,
            anchor_cursh
            + """
#ifdef WWN_INPROC_DISPATCH
    /* Apple sandbox: never fork external simple commands — either run the
     * in-process dispatcher or report command-not-found. */
    if (!is_cursh && !do_exec && type == WC_SIMPLE && args && firstnode(args))
	wwn_inproc = 1;
#endif""",
            1,
        )

        # 4) Don't fork when wwn_inproc.
        anchor_fork = (
            "	if (!do_exec &&\n"
            "	    (((is_builtin || is_shfunc) && output) ||\n"
            "	     (!is_cursh && (last1 != 1 || nsigtrapped || havefiles() ||\n"
            "			    fdtable_flocks)))) {"
        )
        if anchor_fork not in src:
            fail("fork-decision anchor missing")
        src = src.replace(
            anchor_fork,
            "	if (!do_exec &&\n"
            "#ifdef WWN_INPROC_DISPATCH\n"
            "	    !wwn_inproc &&\n"
            "#endif\n"
            "	    (((is_builtin || is_shfunc) && output) ||\n"
            "	     (!is_cursh && (last1 != 1 || nsigtrapped || havefiles() ||\n"
            "			    fdtable_flocks)))) {",
            1,
        )

        # 5) Don't fake-exec when wwn_inproc: add an else-if before the external else.
        anchor_else = (
            "	} else {\n"
            "	    /* This is an exec (real or fake) for an external command.    *\n"
            "	     * Note that any form of exec means that the subshell is fake *"
        )
        if anchor_else not in src:
            fail("external-exec else anchor missing")
        src = src.replace(
            anchor_else,
            "#ifdef WWN_INPROC_DISPATCH\n"
            "	} else if (wwn_inproc) {\n"
            "	    /* in-process external command: neither fork nor exec */\n"
            "#endif\n"
            "	} else {\n"
            "	    /* This is an exec (real or fake) for an external command.    *\n"
            "	     * Note that any form of exec means that the subshell is fake *",
            1,
        )

        # 6) Run in-process instead of execute() at the WC_SIMPLE exec site.
        anchor_exec = (
            "	    if (type == WC_SIMPLE || type == WC_TYPESET) {\n"
            "		if (varspc) {\n"
            "		    int addflags = ADDVAR_EXPORT|ADDVAR_RESTRICT;\n"
            "		    if (forked)\n"
            "			addflags |= ADDVAR_RESTORE;\n"
            "		    addvars(state, varspc, addflags);\n"
            "		    if (errflag)\n"
            "			_exit(1);\n"
            "		}\n"
            "		closem(FDT_INTERNAL, 0);"
        )
        if anchor_exec not in src:
            fail("WC_SIMPLE execute() anchor missing")
        src = src.replace(
            anchor_exec,
            "	    if (type == WC_SIMPLE || type == WC_TYPESET) {\n"
            "		if (varspc) {\n"
            "		    int addflags = ADDVAR_EXPORT|ADDVAR_RESTRICT;\n"
            "		    if (forked)\n"
            "			addflags |= ADDVAR_RESTORE;\n"
            "		    addvars(state, varspc, addflags);\n"
            "		    if (errflag)\n"
            "			_exit(1);\n"
            "		}\n"
            "#ifdef WWN_INPROC_DISPATCH\n"
            "		if (wwn_inproc) {\n"
            "		    char **wwn_argv = makecline(args);\n"
            "		    char **wwn_pp;\n"
            "		    int wwn_rc;\n"
            "		    for (wwn_pp = wwn_argv; wwn_pp && *wwn_pp; wwn_pp++)\n"
            "			unmetafy(*wwn_pp, NULL);\n"
            "		    wwn_rc = wawona_dispatch_inprocess(\n"
            "			wwn_argv ? wwn_argv[0] : NULL, wwn_argv, environ);\n"
            "		    if (wwn_rc == WWN_DISPATCH_NOT_HANDLED) {\n"
            "			char *wwn_cmd = wwn_argv ? wwn_argv[0] : NULL;\n"
            "			if (wwn_cmd)\n"
            "			    fprintf(stdout, \"wawona: command not found: %s (no builtin or bundled in-process tool; external binaries can't run in the iOS sandbox).\\n\", wwn_cmd);\n"
            "			else\n"
            "			    fprintf(stdout, \"wawona: command not found.\\n\");\n"
            "			lastval = 127;\n"
            "		    } else\n"
            "			lastval = (wwn_rc < 0) ? 1 : (wwn_rc & 0xff);\n"
            "		    fflush(stdout);\n"
            "		    fflush(stderr);\n"
            "		    fixfds(save);\n"
            "		    goto done;\n"
            "		}\n"
            "#endif\n"
            "		closem(FDT_INTERNAL, 0);",
            1,
        )

        p.write_text(src)
        print("patch-zsh-exec.py: applied in-process external-command dispatch hook")
    else:
        print("patch-zsh-exec.py: exec dispatch already applied")
        src = p.read_text()

    src = patch_ios_compinit_guard(src)
    p.write_text(src)

    patch_ios_init_done()
    patch_ios_zle_files()


if __name__ == "__main__":
    main()
