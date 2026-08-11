"""Opening-end divider — faithful port of scalachess Divider.scala (opening/middlegame boundary only).

Computes the first ply at which a game transitions from opening to middlegame.
The endgame boundary (majorsAndMinors <= 6) is out of scope for this module.

Reference: https://github.com/lichess-org/scalachess/blob/master/core/src/main/scala/Divider.scala
"""
from __future__ import annotations

from collections.abc import Sequence

import chess
import chess.pgn

# ── Thresholds (cited from Divider.scala) ─────────────────────────────────────

# majorsAndMinors <= MIDDLEGAME_PIECE_THRESHOLD → middlegame detected
MIDDLEGAME_PIECE_THRESHOLD: int = 10

# mixedness() > MIXEDNESS_THRESHOLD → middlegame detected
MIXEDNESS_THRESHOLD: int = 150

# back-rank piece count < BACKRANK_MIN on either side → backrankSparse
BACKRANK_MIN: int = 4

# ── Precomputed 2×2 region masks (49 total) ───────────────────────────────────

def _compute_regions() -> tuple[int, ...]:
    """Precompute the 49 overlapping 2×2 board region masks used by mixedness.

    smallSquare = 0x0303 (squares a1,b1,a2,b2).
    Regions: for y in 0..6, for x in 0..6: mask = smallSquare << (x + 8*y).
    """
    small = 0x0303
    regions: list[int] = []
    for y in range(7):
        for x in range(7):
            regions.append(small << (x + 8 * y))
    return tuple(regions)


_MIXEDNESS_REGIONS: tuple[int, ...] = _compute_regions()


# ── Heuristics ────────────────────────────────────────────────────────────────

def _majors_and_minors(board: chess.Board) -> int:
    """Count queens, rooks, bishops, knights on the board (both colors)."""
    return chess.popcount(board.occupied & ~(board.kings | board.pawns))


def _backrank_sparse(board: chess.Board) -> bool:
    """True when either side has fewer than BACKRANK_MIN pieces on its back rank."""
    white_back = chess.popcount(chess.BB_RANK_1 & board.occupied_co[chess.WHITE])
    black_back = chess.popcount(chess.BB_RANK_8 & board.occupied_co[chess.BLACK])
    return white_back < BACKRANK_MIN or black_back < BACKRANK_MIN


def _mixedness_score(y: int, white: int, black: int) -> int:
    """Verbatim port of the score(y, white, black) match table from Divider.scala."""
    if white == 0:
        if black == 1:
            return 1 + y
        elif black == 2:
            return (2 + (6 - y)) if y < 6 else 0
        elif black == 3:
            return (3 + (7 - y)) if y < 7 else 0
        elif black == 4:
            return (3 + (7 - y)) if y < 7 else 0
        else:
            return 0
    elif white == 1:
        if black == 0:
            return 1 + (8 - y)
        elif black == 1:
            return 5 + abs(4 - y)
        elif black == 2:
            return 4 + (7 - y)
        elif black == 3:
            return 5 + (7 - y)
        else:
            return 0
    elif white == 2:
        if black == 0:
            return (2 + (y - 2)) if y > 2 else 0
        elif black == 1:
            return 4 + (y - 1)
        elif black == 2:
            return 7
        else:
            return 0
    elif white == 3:
        if black == 0:
            return (3 + (y - 1)) if y > 1 else 0
        elif black == 1:
            return 5 + (y - 1)
        else:
            return 0
    elif white == 4:
        if black == 0:
            return (3 + (y - 1)) if y > 1 else 0
        else:
            return 0
    else:
        return 0


def _mixedness(board: chess.Board) -> int:
    """Sum the per-region mixedness scores over all 49 2×2 regions."""
    white = board.occupied_co[chess.WHITE]
    black = board.occupied_co[chess.BLACK]
    acc = 0
    for i, region in enumerate(_MIXEDNESS_REGIONS):
        y = i // 7 + 1  # y ranges 1..7
        wc = chess.popcount(white & region)
        bc = chess.popcount(black & region)
        acc += _mixedness_score(y, wc, bc)
    return acc


def _is_middlegame(board: chess.Board) -> bool:
    """Return True when any middlegame heuristic fires for this board position."""
    return (
        _majors_and_minors(board) <= MIDDLEGAME_PIECE_THRESHOLD
        or _backrank_sparse(board)
        or _mixedness(board) > MIXEDNESS_THRESHOLD
    )


# ── Public API ────────────────────────────────────────────────────────────────

def boards_from_game(game: chess.pgn.Game) -> list[chess.Board]:
    """Return [initial, after_move_1, after_move_2, ...] for the main line."""
    boards: list[chess.Board] = []
    node: chess.pgn.GameNode = game
    while True:
        boards.append(node.board())
        if node.is_end():
            break
        node = node.variations[0]
    return boards


def opening_end_ply(
    game_or_boards: chess.pgn.Game | Sequence[chess.Board],
) -> int | None:
    """Return the 0-based ply at which the opening ends, or None if it never does.

    Accepts either a chess.pgn.Game (main line is used) or a sequence of chess.Board
    objects where index 0 is the initial position.
    """
    if isinstance(game_or_boards, chess.pgn.Game):
        boards: Sequence[chess.Board] = boards_from_game(game_or_boards)
    else:
        boards = game_or_boards

    for i, board in enumerate(boards):
        if _is_middlegame(board):
            return i
    return None


def annotate_opening_end(game: chess.pgn.Game, ply: int) -> None:
    """Append [%opening_end] to the comment of the node at the given ply.

    Walks ply main-line nodes from the root (ply=0 annotates the root/initial
    position node). Preserves existing comment text. Does not duplicate if the
    annotation is already present.
    """
    node: chess.pgn.GameNode = game
    for _ in range(ply):
        if node.is_end():
            return
        node = node.variations[0]

    existing = node.comment.strip()
    if "[%opening_end]" not in existing:
        node.comment = (existing + " [%opening_end]").strip()
