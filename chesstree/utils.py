from __future__ import annotations

import hashlib
import re

import chess
import chess.pgn
from chess.pgn import (
    NAG_BLUNDER,
    NAG_BRILLIANT_MOVE,
    NAG_DUBIOUS_MOVE,
    NAG_GOOD_MOVE,
    NAG_MISTAKE,
    NAG_SPECULATIVE_MOVE,
    NAG_FORCED_MOVE,
    NAG_DRAWISH_POSITION,
    NAG_UNCLEAR_POSITION,
    NAG_WHITE_SLIGHT_ADVANTAGE,
    NAG_BLACK_SLIGHT_ADVANTAGE,
    NAG_WHITE_MODERATE_ADVANTAGE,
    NAG_BLACK_MODERATE_ADVANTAGE,
    NAG_WHITE_DECISIVE_ADVANTAGE,
    NAG_BLACK_DECISIVE_ADVANTAGE,
    NAG_WHITE_ZUGZWANG,
    NAG_BLACK_ZUGZWANG,
    NAG_WHITE_MODERATE_COUNTERPLAY,
    NAG_BLACK_MODERATE_COUNTERPLAY,
    NAG_WHITE_DECISIVE_COUNTERPLAY,
    NAG_BLACK_DECISIVE_COUNTERPLAY,
    NAG_WHITE_MODERATE_TIME_PRESSURE,
    NAG_BLACK_MODERATE_TIME_PRESSURE,
    NAG_WHITE_SEVERE_TIME_PRESSURE,
    NAG_BLACK_SEVERE_TIME_PRESSURE,
    NAG_NOVELTY,
)

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


# ── NAG string mapping ───────────────────────────────────────────────────

NAG_TO_PGN_STRING = {
    # Move assessment ($1–$6) — inline PGN symbols
    NAG_GOOD_MOVE: "!",
    NAG_MISTAKE: "?",
    NAG_BRILLIANT_MOVE: "!!",
    NAG_BLUNDER: "??",
    NAG_SPECULATIVE_MOVE: "!?",
    NAG_DUBIOUS_MOVE: "?!",
    # $7: forced/only move; $8 and $9 have no standard symbol
    NAG_FORCED_MOVE: "□",
    # Position assessment ($10–$19)
    # $11 (quiet) and $12 (active) have no standard symbol in the PGN spec
    NAG_DRAWISH_POSITION: "=",       # $10
    NAG_UNCLEAR_POSITION: "∞",       # $13
    NAG_WHITE_SLIGHT_ADVANTAGE: "⩲", # $14
    NAG_BLACK_SLIGHT_ADVANTAGE: "⩱", # $15
    NAG_WHITE_MODERATE_ADVANTAGE: "±", # $16
    NAG_BLACK_MODERATE_ADVANTAGE: "∓", # $17
    NAG_WHITE_DECISIVE_ADVANTAGE: "+-", # $18
    NAG_BLACK_DECISIVE_ADVANTAGE: "-+", # $19
    # Zugzwang ($22–$23)
    NAG_WHITE_ZUGZWANG: "⨀",         # $22
    NAG_BLACK_ZUGZWANG: "⨀",         # $23
    # Counterplay ($132–$135): ⇆ explicitly defined for $132; extended to all
    NAG_WHITE_MODERATE_COUNTERPLAY: "⇆",  # $132
    NAG_BLACK_MODERATE_COUNTERPLAY: "⇆",  # $133
    NAG_WHITE_DECISIVE_COUNTERPLAY: "⇆",  # $134
    NAG_BLACK_DECISIVE_COUNTERPLAY: "⇆",  # $135
    # Time pressure ($136–$139): ⨁ explicitly defined for $138; extended to all
    NAG_WHITE_MODERATE_TIME_PRESSURE: "⨁", # $136
    NAG_BLACK_MODERATE_TIME_PRESSURE: "⨁", # $137
    NAG_WHITE_SEVERE_TIME_PRESSURE: "⨁",   # $138
    NAG_BLACK_SEVERE_TIME_PRESSURE: "⨁",   # $139
    # Novelty
    NAG_NOVELTY: "N",                # $146
}


# ── Shared NAG helpers ────────────────────────────────────────────────────

# Assessment NAGs ordered by priority: most severe first.
# When a move has multiple NAGs, the most severe wins for coloring.
_ASSESSMENT_NAGS_PRIORITY = [
    NAG_BLUNDER,
    NAG_MISTAKE,
    NAG_DUBIOUS_MOVE,
    NAG_SPECULATIVE_MOVE,
    NAG_GOOD_MOVE,
    NAG_BRILLIANT_MOVE,
]


def _nag_symbol(node: chess.pgn.ChildNode) -> str:
    """Return the PGN symbol for the most significant assessment NAG on this node."""
    for nag in _ASSESSMENT_NAGS_PRIORITY:
        if nag in node.nags:
            return NAG_TO_PGN_STRING[nag]
    return ""


# ── Shared node ID ────────────────────────────────────────────────────────

def _node_id(fen: str) -> str:
    """Generate a stable node ID from a FEN string."""
    return "n" + hashlib.md5(fen.encode()).hexdigest()[:8]


# ── Last-move highlighting ────────────────────────────────────────────────

_LAST_MOVE_HIGHLIGHT_COLOR = "#d4d46a"


def _last_move_fill(move: chess.Move) -> dict[chess.Square, str]:
    """Return a fill dict highlighting the from/to squares of a move."""
    return {move.from_square: _LAST_MOVE_HIGHLIGHT_COLOR, move.to_square: _LAST_MOVE_HIGHLIGHT_COLOR}
