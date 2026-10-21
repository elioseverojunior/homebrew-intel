"""Markdown helpers that keep generated reports within rumdl's 80-column limit."""

import textwrap

WIDTH = 80


def bullet(text, marker="- "):
    """A list item wrapped with a hanging indent; never splits package names."""
    return textwrap.fill(
        text,
        width=WIDTH,
        initial_indent=marker,
        subsequent_indent=" " * len(marker),
        break_on_hyphens=False,
        break_long_words=False,
    )


def paragraph(text):
    """A wrapped paragraph, or a placeholder when there is nothing to list."""
    if not text:
        return "Nenhum."
    return textwrap.fill(text, width=WIDTH, break_on_hyphens=False, break_long_words=False)
