/*
 * Throwaway link stubs for `make -C Src zsh` during the iOS zsh derivation.
 * libwawona-zsh.a keeps extern-only dispatch refs; the Wawona app links the
 * real libwwn-pty.a at final link.
 */
#if defined(__APPLE__)
#include <TargetConditionals.h>
#endif
#if defined(__APPLE__) && (TARGET_OS_IPHONE || TARGET_OS_TV || TARGET_OS_WATCH || TARGET_OS_VISION)

#define WWN_DISPATCH_NOT_HANDLED (-1)

int wawona_dispatch_can_handle(const char *argv0)
{
	(void)argv0;
	return 0;
}

int wawona_dispatch_inprocess(const char *path, char *const argv[], char *const envp[])
{
	(void)path;
	(void)argv;
	(void)envp;
	return WWN_DISPATCH_NOT_HANDLED;
}

void wwn_pty_ios_shell_init_done(void) {}
void wwn_pty_ios_note_init_io(void) {}

#endif
