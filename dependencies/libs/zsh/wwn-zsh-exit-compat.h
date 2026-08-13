/*
 * In-process zsh on Apple mobile must never call libc exit()/_exit() —
 * that tears down the whole Wawona host (nested Weston mid-pixman → SIGSEGV).
 * Force-included while compiling zsh; soft exit longjmps back to wwn_pty.
 */
#ifndef WWN_ZSH_EXIT_COMPAT_H
#define WWN_ZSH_EXIT_COMPAT_H

#if defined(__APPLE__)
#include <TargetConditionals.h>
#endif

#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH)

/*
 * Parse real libc prototypes BEFORE installing exit macros. Force-include
 * runs ahead of every .c unit; defining exit/_exit first mangles unistd.h
 * mid-parse (declarations of chdir/access/getpid never appear).
 */
#include <stdlib.h>
#include <unistd.h>

#ifdef __cplusplus
extern "C" {
#endif
void wwn_zsh_soft_exit(int status) __attribute__((__noreturn__));
#ifdef __cplusplus
}
#endif

#undef exit
#undef _exit
#undef _Exit
#define exit(status) wwn_zsh_soft_exit((int)(status))
#define _exit(status) wwn_zsh_soft_exit((int)(status))
#define _Exit(status) wwn_zsh_soft_exit((int)(status))

#endif /* Apple mobile */

#endif /* WWN_ZSH_EXIT_COMPAT_H */
