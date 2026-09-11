#!/usr/bin/env python3
"""Patch zsh Src/exec.c so external commands in the in-process safe subset run
WITHOUT fork/exec on the Apple sandbox (App Store compliant).

Strategy (mirrors how zsh already runs builtins in-process):
  1. At the fork-decision point in execcmd_exec(), if the command is a plain
     external simple command, set a local flag `wwn_inproc`.
  2. Guard the fork so `wwn_inproc` commands do NOT fork, and add an else-if so
     they do NOT take the fake-exec (entersubsh + execve-replace) path either.
  3. Let zsh apply io redirections into its `save` table as usual, then at the
     point it would call execute() (which execve's), instead call
     wawona_dispatch_inprocess(), restore fds via fixfds(save), and `goto done`
     exactly like the builtin path.
  4. If dispatch returns NOT_HANDLED, interpret user shell scripts in-process
     (`source` / `sh -c` / `./file.sh`). Mach-O and ELF stay refused (2.5.2).
     Scripts are data for the signed zsh interpreter, same class as Pulley wasm.

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
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION)
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
    prologue = anchor + """#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION)
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
    hdr = anchor + """#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION)
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
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION)
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
#if !(defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION))
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


def patch_interpreter_placeholder_guard(src: str) -> str:
    """Upgrade already-patched exec.c so PATH zsh/sh stubs are never sourced."""
    if "wwn_is_interpreter_placeholder" in src:
        return src
    old = """static int
wwn_try_run_shell_script(char **argv)
{
    const char *base;

    if (argv == NULL || argv[0] == NULL)
	return 0;
    base = wwn_exec_basename(argv[0]);
    if (wwn_basename_is_shell(base) && argv[1] != NULL)
	return wwn_run_as_shell(argv);
    if (strchr(argv[0], '/') != NULL)
	return wwn_run_script_file(argv[0], argv);
    if (wwn_basename_is_shell(base))
	return wwn_run_as_shell(argv);
    if (wwn_name_looks_like_shell_script(base))
	return wwn_run_script_file(argv[0], argv);
    return 0;
}
"""
    new = """static int
wwn_is_interpreter_placeholder(const char *path)
{
    const char *base;
    char line[128];
    FILE *fp;

    if (path == NULL || path[0] == '\\0')
	return 0;
    base = wwn_exec_basename(path);
    if (!wwn_basename_is_shell(base))
	return 0;
    if (strcmp(path, "/usr/bin/zsh") == 0 || strcmp(path, "/bin/zsh") == 0 ||
	strcmp(path, "/usr/bin/sh") == 0 || strcmp(path, "/bin/sh") == 0 ||
	strcmp(path, "/usr/bin/bash") == 0 || strcmp(path, "/bin/bash") == 0 ||
	strcmp(path, "/usr/bin/dash") == 0 || strcmp(path, "/bin/dash") == 0)
	return 1;
    fp = fopen(path, "r");
    if (fp == NULL)
	return 0;
    if (fgets(line, sizeof line, fp) != NULL &&
	(strncmp(line, "# Wawona iOS:", 13) == 0 ||
	 strncmp(line, "# Wawona in-process:", 20) == 0)) {
	fclose(fp);
	return 1;
    }
    fclose(fp);
    return 0;
}

static int
wwn_try_run_shell_script(char **argv)
{
    const char *base;

    if (argv == NULL || argv[0] == NULL)
	return 0;
    base = wwn_exec_basename(argv[0]);
    if (wwn_basename_is_shell(base) || wwn_is_interpreter_placeholder(argv[0]))
	return wwn_run_as_shell(argv);
    {
	size_t wn = base ? strlen(base) : 0;
	if (wn >= 5 && strcmp(base + wn - 5, ".wasm") == 0)
	    return 0;
    }
    if (strchr(argv[0], '/') != NULL)
	return wwn_run_script_file(argv[0], argv);
    if (wwn_name_looks_like_shell_script(base))
	return wwn_run_script_file(argv[0], argv);
    return 0;
}
"""
    if old not in src:
        if "wwn_try_run_shell_script" in src:
            fail("wwn_try_run_shell_script present but placeholder guard cannot upgrade")
        return src
    return src.replace(old, new, 1)


_RUNNABLE_HELPER = """
#ifdef WWN_INPROC_DISPATCH
/* PATH / hashcmd: a regular file we can interpret is a command, like a
 * +x binary on macOS zsh. Unix X_OK is optional. Mach-O/ELF stay hidden. */
static int
wwn_inproc_runnable_path(const char *path)
{
    const char *base;
    struct stat st;
    unsigned char mag[4];
    int fd, foreign = 0;
    ssize_t nread;
    size_t n;

    if (path == NULL || path[0] == '\\0')
	return 0;
    if (stat(path, &st) != 0 || !S_ISREG(st.st_mode))
	return 0;
    if (wwn_file_magic_is_native(path))
	return 0;
    base = wwn_exec_basename(path);
    if (wwn_basename_is_shell(base))
	return 1;
    if (wwn_name_looks_like_shell_script(base))
	return 1;
    n = base ? strlen(base) : 0;
    if (n >= 5 && strcmp(base + n - 5, ".wasm") == 0)
	return 1;
    fd = open(path, O_RDONLY);
    if (fd >= 0) {
	nread = read(fd, mag, 4);
	close(fd);
	if (nread == 4 && mag[0] == 0x00 && mag[1] == 'a' &&
	    mag[2] == 's' && mag[3] == 'm')
	    return 1;
    }
    if (wwn_shebang_is_shell(path, &foreign))
	return 1;
    return 0;
}
#endif
"""


def patch_isreallyexe_inproc_shells(src: str) -> str:
    """PATH lookup: scripts and wasm are commands without Unix X_OK."""
    if "WWN_INPROC_DISPATCH" not in src:
        return src
    if "wwn_inproc_runnable_path" in src:
        return src

    old_helper = """
#ifdef WWN_INPROC_DISPATCH
static int
wwn_inproc_shell_path_ok(const char *path)
{
    const char *base;
    struct stat st;

    base = wwn_exec_basename(path);
    if (!wwn_basename_is_shell(base))
	return 0;
    if (stat(path, &st) != 0)
	return 0;
    return S_ISREG(st.st_mode);
}
#endif
"""
    if old_helper in src:
        src = src.replace(old_helper, _RUNNABLE_HELPER, 1)
        src = src.replace("wwn_inproc_shell_path_ok(", "wwn_inproc_runnable_path(")
        return src

    marker = "static int\nwwn_try_run_shell_script(char **argv)\n"
    if marker in src and "wwn_basename_is_shell" in src:
        src = src.replace(marker, _RUNNABLE_HELPER + marker, 1)
    else:
        fail("cannot insert wwn_inproc_runnable_path (script hook missing)")
    # zsh 5.9.1: iscom() is what hashcmd / command -v use (not isreallyexe).
    iscom_old = """    return (access(us, X_OK) == 0 && stat(us, &statbuf) >= 0 &&
	    S_ISREG(statbuf.st_mode));
"""
    iscom_new = """    return ((access(us, X_OK) == 0
#ifdef WWN_INPROC_DISPATCH
	     || wwn_inproc_runnable_path(us)
#endif
	    ) && stat(us, &statbuf) >= 0 &&
	    S_ISREG(statbuf.st_mode));
"""
    if iscom_old in src:
        return src.replace(iscom_old, iscom_new, 1)
    old = """    if (access(s, X_OK) == 0 && stat(s, &sbuf) >= 0)"""
    new = """    if ((access(s, X_OK) == 0
#ifdef WWN_INPROC_DISPATCH
	 || wwn_inproc_runnable_path(s)
#endif
	) && stat(s, &sbuf) >= 0)"""
    if old in src:
        return src.replace(old, new, 1)
    old2 = """	if (access(cmdbuf, X_OK) == 0)"""
    new2 = """	if (access(cmdbuf, X_OK) == 0
#ifdef WWN_INPROC_DISPATCH
	    || wwn_inproc_runnable_path(cmdbuf)
#endif
	    )"""
    if old2 in src:
        return src.replace(old2, new2, 1)
    # zsh 5.9.1 isreallyexe often uses access(X_OK) then stat.
    old3 = """	if (access(s, X_OK) < 0)"""
    new3 = """	if (access(s, X_OK) < 0
#ifdef WWN_INPROC_DISPATCH
	    && !wwn_inproc_runnable_path(s)
#endif
	    )"""
    if old3 in src:
        return src.replace(old3, new3, 1)
    print("patch-zsh-exec.py: WARN no isreallyexe/X_OK anchor; rely on 755 stubs")
    return src


def patch_path_commands_skip_wasm_source(src: str) -> str:
    """Already-patched exec.c: do not source .wasm; hashcmd uses runnable_path."""
    try_old = """    if (wwn_basename_is_shell(base) || wwn_is_interpreter_placeholder(argv[0]))
	return wwn_run_as_shell(argv);
    if (strchr(argv[0], '/') != NULL)
	return wwn_run_script_file(argv[0], argv);
"""
    try_new = """    if (wwn_basename_is_shell(base) || wwn_is_interpreter_placeholder(argv[0]))
	return wwn_run_as_shell(argv);
    {
	size_t wn = base ? strlen(base) : 0;
	if (wn >= 5 && strcmp(base + wn - 5, ".wasm") == 0)
	    return 0;
    }
    if (strchr(argv[0], '/') != NULL)
	return wwn_run_script_file(argv[0], argv);
"""
    if try_old in src:
        src = src.replace(try_old, try_new, 1)
    run_old = """    if (path == NULL || path[0] == '\\0')
	return 0;
    if (strchr(path, '/') == NULL) {
"""
    run_new = """    if (path == NULL || path[0] == '\\0')
	return 0;
    {
	const char *wb = wwn_exec_basename(path);
	size_t wn = wb ? strlen(wb) : 0;
	if (wn >= 5 && strcmp(wb + wn - 5, ".wasm") == 0)
	    return 0;
    }
    if (strchr(path, '/') == NULL) {
"""
    if run_old in src and "strcmp(wb + wn - 5, \".wasm\")" not in src:
        src = src.replace(run_old, run_new, 1)
    old_msg = (
        "Shell scripts: ./file.sh or sh file.sh. Native binaries cannot "
        "run in the iOS sandbox"
    )
    new_msg = (
        "Run ./file.sh, file.sh, ./file.wasm, or a full path. "
        "Native binaries cannot run in the iOS sandbox"
    )
    if old_msg in src:
        src = src.replace(old_msg, new_msg, 1)
    return src


def patch_ios_compinit_guard(src: str) -> str:
    if "WAWONA_ENABLE_COMPINIT" in src:
        return src
    # Anchor only on the (stable) function signature + opening brace, NOT the
    # first local declaration: zsh 5.9.1 used `buf[PATH_MAX+1]` while 5.9.2 uses
    # `buf[PATH_MAX]`, and keying on that line makes the patch brittle across
    # point releases. The guard is inserted right after `{`, before the first
    # declaration — legal under -std=gnu23 (mixed decls/statements), which is how
    # this build compiles zsh.
    anchor = """getfpfunc(char *s, int *ksh, char **fdir, char **alt_path, int test_only)
{"""
    guard = anchor + """
#ifdef WWN_INPROC_DISPATCH
    /* Parsing Completion/compinit faults on in-process iOS; require opt-in. */
    if (s && strcmp(s, "compinit") == 0 && getenv("WAWONA_ENABLE_COMPINIT") == NULL)
	return test_only ? NULL : &dummy_eprog;
#endif"""
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
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION)
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
/*
 * tvOS/watchOS SDKs mark fork/execve unavailable (hard error even in
 * unreachable branches). iPhoneOS still compiles those symbols. Stub them
 * out so shared ios.nix recipes can build under buildForTVOS/WatchOS.
 */
#if TARGET_OS_TV || TARGET_OS_WATCH
#include <errno.h>
#undef fork
#undef execve
#define fork() (errno = ENOSYS, (pid_t)-1)
#define execve(path, argv, envp) (errno = ENOSYS, -1)
#endif
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>

static int
wwn_basename_is_shell(const char *name)
{
    return name && (
	strcmp(name, "sh") == 0 ||
	strcmp(name, "zsh") == 0 ||
	strcmp(name, "bash") == 0 ||
	strcmp(name, "dash") == 0 ||
	strcmp(name, "ksh") == 0 ||
	strcmp(name, "ash") == 0);
}

static const char *
wwn_exec_basename(const char *path)
{
    const char *base;

    if (path == NULL || path[0] == '\\0')
	return NULL;
    base = strrchr(path, '/');
    return base != NULL ? base + 1 : path;
}

static int
wwn_file_magic_is_native(const char *path)
{
    unsigned char mag[4];
    int fd;
    ssize_t n;

    if (path == NULL || path[0] == '\\0')
	return 0;
    fd = open(path, O_RDONLY);
    if (fd < 0)
	return 0;
    n = read(fd, mag, 4);
    close(fd);
    if (n != 4)
	return 0;
    /* Mach-O thin/fat (any endian) and ELF. Guideline 2.5.2: refuse. */
    if ((mag[0] == 0xcf && mag[1] == 0xfa && mag[2] == 0xed && mag[3] == 0xfe) ||
	(mag[0] == 0xfe && mag[1] == 0xed && mag[2] == 0xfa && mag[3] == 0xcf) ||
	(mag[0] == 0xce && mag[1] == 0xfa && mag[2] == 0xed && mag[3] == 0xfe) ||
	(mag[0] == 0xfe && mag[1] == 0xed && mag[2] == 0xfa && mag[3] == 0xce) ||
	(mag[0] == 0xca && mag[1] == 0xfe && mag[2] == 0xba && mag[3] == 0xbe) ||
	(mag[0] == 0xbe && mag[1] == 0xba && mag[2] == 0xfe && mag[3] == 0xca) ||
	(mag[0] == 0xca && mag[1] == 0xfe && mag[2] == 0xba && mag[3] == 0xbf) ||
	(mag[0] == 0x7f && mag[1] == 'E' && mag[2] == 'L' && mag[3] == 'F'))
	return 1;
    return 0;
}

static int
wwn_looks_like_text(const char *path)
{
    unsigned char buf[256];
    int fd;
    ssize_t n, i;

    fd = open(path, O_RDONLY);
    if (fd < 0)
	return 0;
    n = read(fd, buf, sizeof buf);
    close(fd);
    if (n <= 0)
	return 1;
    for (i = 0; i < n; i++) {
	if (buf[i] == 0)
	    return 0;
    }
    return 1;
}

static int
wwn_shebang_is_shell(const char *path, int *known_foreign)
{
    char line[512];
    FILE *fp;
    char *p, *tok;
    const char *base;

    if (known_foreign)
	*known_foreign = 0;
    fp = fopen(path, "r");
    if (fp == NULL)
	return 0;
    if (fgets(line, sizeof line, fp) == NULL) {
	fclose(fp);
	return 0;
    }
    fclose(fp);
    if (line[0] != '#' || line[1] != '!')
	return 0;
    p = line + 2;
    while (*p == ' ' || *p == '\\t')
	p++;
    tok = p;
    while (*p && *p != ' ' && *p != '\\t' && *p != '\\n' && *p != '\\r')
	p++;
    if (*p)
	*p++ = '\\0';
    while (*p == ' ' || *p == '\\t')
	p++;
    base = wwn_exec_basename(tok);
    if (base && strcmp(base, "env") == 0) {
	while (*p == '-') {
	    while (*p && *p != ' ' && *p != '\\t')
		p++;
	    while (*p == ' ' || *p == '\\t')
		p++;
	}
	tok = p;
	while (*p && *p != ' ' && *p != '\\t' && *p != '\\n' && *p != '\\r')
	    p++;
	*p = '\\0';
	base = wwn_exec_basename(tok);
    }
    if (wwn_basename_is_shell(base))
	return 1;
    if (base && base[0] && known_foreign)
	*known_foreign = 1;
    return 0;
}

static int
wwn_name_looks_like_shell_script(const char *name)
{
    size_t n;

    if (name == NULL)
	return 0;
    n = strlen(name);
    return (n >= 3 && strcmp(name + n - 3, ".sh") == 0) ||
	(n >= 4 && strcmp(name + n - 4, ".zsh") == 0) ||
	(n >= 5 && strcmp(name + n - 5, ".bash") == 0);
}

static int
wwn_run_script_file(char *path, char **argv_incl_path)
{
    char **oldpp;
    char *old0;
    char **rest;
    char *resolved;
    char tmp[4096];
    int ret;
    struct stat st;

    if (path == NULL || path[0] == '\\0')
	return 0;
    {
	const char *wb = wwn_exec_basename(path);
	size_t wn = wb ? strlen(wb) : 0;
	if (wn >= 5 && strcmp(wb + wn - 5, ".wasm") == 0)
	    return 0;
    }
    if (strchr(path, '/') == NULL) {
	snprintf(tmp, sizeof tmp, "./%s", path);
	if (stat(tmp, &st) == 0)
	    path = tmp;
    }
    if (stat(path, &st) != 0) {
	fprintf(stdout, "wawona: %s: %s\\n", path, strerror(errno));
	lastval = 127;
	return 1;
    }
    if (!S_ISREG(st.st_mode)) {
	fprintf(stdout, "wawona: %s: not a regular file\\n", path);
	lastval = 126;
	return 1;
    }
    if (wwn_file_magic_is_native(path)) {
	fprintf(stdout,
		"wawona: '%s' is a native binary. App Store builds cannot exec Mach-O or ELF; use a shell script or wasm.\\n",
		path);
	lastval = 126;
	return 1;
    }
    {
	int foreign = 0;
	if (wwn_shebang_is_shell(path, &foreign))
	    ;
	else if (foreign) {
	    fprintf(stdout,
		    "wawona: '%s' needs an interpreter that is not bundled (shell scripts and wasm only).\\n",
		    path);
	    lastval = 126;
	    return 1;
	} else if (!wwn_looks_like_text(path)) {
	    fprintf(stdout,
		    "wawona: '%s' cannot be executed (not a shell script; native binaries cannot run in the iOS sandbox).\\n",
		    path);
	    lastval = 126;
	    return 1;
	}
    }
    resolved = ztrdup(path);
    oldpp = pparams;
    old0 = argzero;
    rest = (argv_incl_path && argv_incl_path[0] && argv_incl_path[1])
	? zarrdup(argv_incl_path + 1) : NULL;
    argzero = ztrdup(resolved);
    if (rest)
	pparams = rest;
    ret = source(resolved);
    zsfree(argzero);
    argzero = old0;
    if (rest) {
	freearray(pparams);
	pparams = oldpp;
    }
    zsfree(resolved);
    lastval = ret;
    return 1;
}

static int
wwn_run_as_shell(char **argv)
{
    int i = 1;

    while (argv[i] && argv[i][0] == '-' && argv[i][1] != '\\0') {
	if (strcmp(argv[i], "--") == 0) {
	    i++;
	    break;
	}
	if (argv[i][1] == '-') {
	    i++;
	    continue;
	}
	if (strcmp(argv[i], "-c") == 0 || strchr(argv[i] + 1, 'c') != NULL) {
	    char *cmd = argv[i + 1];
	    if (cmd == NULL) {
		fprintf(stdout, "wawona: sh: -c requires an argument\\n");
		lastval = 2;
		return 1;
	    }
	    execstring(cmd, 1, 0, "sh -c");
	    return 1;
	}
	i++;
    }
    if (argv[i] == NULL) {
	fprintf(stdout,
		"wawona: already running in-process zsh. Nested shells are the same interpreter.\\n");
	lastval = 0;
	return 1;
    }
    return wwn_run_script_file(argv[i], argv + i);
}

static int
wwn_is_interpreter_placeholder(const char *path)
{
    const char *base;
    char line[128];
    FILE *fp;

    if (path == NULL || path[0] == '\\0')
	return 0;
    base = wwn_exec_basename(path);
    if (!wwn_basename_is_shell(base))
	return 0;
    if (strcmp(path, "/usr/bin/zsh") == 0 || strcmp(path, "/bin/zsh") == 0 ||
	strcmp(path, "/usr/bin/sh") == 0 || strcmp(path, "/bin/sh") == 0 ||
	strcmp(path, "/usr/bin/bash") == 0 || strcmp(path, "/bin/bash") == 0 ||
	strcmp(path, "/usr/bin/dash") == 0 || strcmp(path, "/bin/dash") == 0)
	return 1;
    fp = fopen(path, "r");
    if (fp == NULL)
	return 0;
    if (fgets(line, sizeof line, fp) != NULL &&
	(strncmp(line, "# Wawona iOS:", 13) == 0 ||
	 strncmp(line, "# Wawona in-process:", 20) == 0)) {
	fclose(fp);
	return 1;
    }
    fclose(fp);
    return 0;
}

static int
wwn_try_run_shell_script(char **argv)
{
    const char *base;

    if (argv == NULL || argv[0] == NULL)
	return 0;
    base = wwn_exec_basename(argv[0]);
    /* PATH stubs (/usr/bin/zsh) are comment files. Never source them. */
    if (wwn_basename_is_shell(base) || wwn_is_interpreter_placeholder(argv[0]))
	return wwn_run_as_shell(argv);
    {
	size_t wn = base ? strlen(base) : 0;
	if (wn >= 5 && strcmp(base + wn - 5, ".wasm") == 0)
	    return 0;
    }
    if (strchr(argv[0], '/') != NULL)
	return wwn_run_script_file(argv[0], argv);
    if (wwn_name_looks_like_shell_script(base))
	return wwn_run_script_file(argv[0], argv);
    return 0;
}
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
            "			if (!wwn_try_run_shell_script(wwn_argv)) {\n"
            "			    char *wwn_cmd = wwn_argv ? wwn_argv[0] : NULL;\n"
            "			    if (wwn_cmd)\n"
            "				fprintf(stdout, \"wawona: command not found: %s (type help. Run ./file.sh, file.sh, ./file.wasm, or a full path. Native binaries cannot run in the iOS sandbox).\\n\", wwn_cmd);\n"
            "			    else\n"
            "				fprintf(stdout, \"wawona: command not found.\\n\");\n"
            "			    lastval = 127;\n"
            "			}\n"
            "		    } else {\n"
            "			lastval = (wwn_rc < 0) ? 1 : (wwn_rc & 0xff);\n"
            "			if (lastval == 130)\n"
            "				errflag = 1;\n"
            "		    }\n"
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
    src = patch_interpreter_placeholder_guard(src)
    src = patch_isreallyexe_inproc_shells(src)
    src = patch_path_commands_skip_wasm_source(src)
    p.write_text(src)

    patch_ios_init_done()
    patch_ios_zle_files()


if __name__ == "__main__":
    main()
