from __future__ import annotations

import re

# Matches any PGN command annotation embedded in a comment, e.g. [%clk 0:05:00],
# [%emt 0:00:03], [%eval 0.5], [%csl Gd4], [%cal Ge2e4].
_PGN_COMMAND_ANNOTATION_RE = re.compile(r"\[%[^\]]+\]")


def has_real_comment(comment: str) -> bool:
    """Return True if the comment contains human-readable text.

    PGN command annotations such as ``[%clk ...]``, ``[%emt ...]``,
    ``[%eval ...]``, ``[%csl ...]``, and ``[%cal ...]`` are stripped before
    checking, because they are machine-generated metadata embedded inside PGN
    comment braces, not actual commentary.
    """
    stripped = _PGN_COMMAND_ANNOTATION_RE.sub("", comment).strip()
    return bool(stripped)
