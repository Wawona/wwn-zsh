/* Minimal termcap/curses stubs for iOS — enough ANSI for zsh ZLE redraw. */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

static const char *
cap_seq(const char *name)
{
	static const struct {
		const char *name;
		const char *seq;
	} table[] = {
		{ "cuu1", "\033[A" },
		{ "cud1", "\033[B" },
		{ "cuf1", "\033[C" },
		{ "cub1", "\033[D" },
		{ "ind", "\033[D" },
		{ "indn", "\033[D" },
		{ "kcuu1", "\033[A" },
		{ "kcud1", "\033[B" },
		{ "kcuf1", "\033[C" },
		{ "kcub1", "\033[D" },
		{ "cr", "\r" },
		{ "ce", "\033[K" },
		{ "el", "\033[K" },
		{ "cleol", "\033[K" },
		{ "ed", "\033[J" },
		{ "cd", "\033[J" },
		{ "cl", "\033[H\033[2J" },
		{ "clear", "\033[H\033[2J" },
		{ "vi", "\033[?25h" },
		{ "vs", "\033[?25h" },
		{ "ve", "\033[?25h" },
		{ "vi", "\033[?25h" },
		{ "nd", "\033[C" },
		{ "up", "\033[A" },
		{ "do", "\033[B" },
		{ "le", "\033[D" },
		{ "ri", "\033M" },
		{ "sf", "\033[S" },
		{ "sr", "\033[T" },
		{ "al", "\033[L" },
		{ "dl", "\033[M" },
		{ "dc", "\033[P" },
		{ "ic", "\033[@" },
		{ "so", "\033[7m" },
		{ "se", "\033[m" },
		{ "us", "\033[4m" },
		{ "ue", "\033[24m" },
		{ "mb", "\033[5m" },
		{ "md", "\033[1m" },
		{ "mr", "\033[7m" },
		{ "me", "\033[m" },
		{ "cm", "\033[%i%iH" },
		{ NULL, NULL },
	};
	size_t i;

	for (i = 0; table[i].name != NULL; i++) {
		if (strcmp(table[i].name, name) == 0)
			return table[i].seq;
	}
	return NULL;
}

char *
tgoto(const char *cap, int col, int row)
{
	static char buf[32];

	(void)cap;
	snprintf(buf, sizeof buf, "\033[%d;%dH", row + 1, col + 1);
	return buf;
}

int
tputs(const char *str, int affcnt, int (*outc)(int))
{
	int count = 0;

	(void)affcnt;
	if (str == NULL || outc == NULL)
		return 0;
	while (*str != '\0') {
		if (outc((unsigned char)*str++) != 0)
			break;
		count++;
	}
	return count;
}

int
tgetent(char *bp, const char *name)
{
	(void)bp;
	(void)name;
	return 1;
}

char *
tigetstr(const char *name)
{
	return (char *)cap_seq(name);
}

int
tigetflag(const char *name)
{
	(void)name;
	return 0;
}

int
tigetnum(const char *name)
{
	if (name != NULL && strcmp(name, "cols") == 0)
		return 80;
	if (name != NULL && strcmp(name, "lines") == 0)
		return 24;
	return -1;
}

char *
tgetstr(const char *id, char **area)
{
	const char *seq = cap_seq(id);

	(void)area;
	return seq != NULL ? (char *)seq : NULL;
}

int
tgetnum(const char *id)
{
	return tigetnum(id);
}

int
tgetflag(const char *id)
{
	(void)id;
	return 0;
}
