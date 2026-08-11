"""Pure, injectable core for annotating chess game positions with engine evaluations.

Provides scope-based node selection, eval formatting, and PGN comment annotation
via an injected EvalProvider — fully testable without a real engine subprocess.
"""
from __future__ import annotations

import re
from typing import Callable

import chess
import chess.engine
import chess.pgn

from chesstree.utils import normalize_fen

# ── Exception ─────────────────────────────────────────────────────────────────


class EngineUnavailable(RuntimeError):
    """Raised when the engine binary is missing or the subprocess fails to spawn."""


# ── Type alias ────────────────────────────────────────────────────────────────

EvalProvider = Callable[[chess.Board], "chess.engine.PovScore | None"]

# ── Scope constants ───────────────────────────────────────────────────────────

TERMINAL: str = "leaves"
BRANCHES: str = "branch-points"
ALL: str = "all"

# ── Engine defaults ───────────────────────────────────────────────────────────

DEFAULT_DEPTH: int = 20
DEFAULT_ENGINE: str = "stockfish"

# ── Internal regex for stripping existing [%eval ...] annotations ─────────────

_EVAL_STRIP_RE = re.compile(r"\s*\[%eval[^\]]*\]")


# ── Eval formatting ───────────────────────────────────────────────────────────

def format_eval(score: chess.engine.PovScore) -> str:
    """Format a PovScore as a white-perspective eval string for PGN annotation.

    Mate scores become ``#<n>`` (e.g. ``#3``, ``#-3``).
    Centipawn scores become decimal pawns with 2 decimal places
    (e.g. ``0.43``, ``-1.20``, ``0.00``).

    This is the exact inverse of the ``[%eval ...]`` parsing in
    ``json_exporter._extract_command_annotations`` so annotate→parse round-trips
    are stable.
    """
    white_score = score.white()
    if white_score.is_mate():
        mate_n = white_score.mate()
        return f"#{mate_n}"
    cp = white_score.score()
    assert cp is not None
    return f"{cp / 100:.2f}"


# ── Node selection ────────────────────────────────────────────────────────────

def _walk_all_nodes(node: chess.pgn.GameNode) -> list[chess.pgn.GameNode]:
    """Return every node in the game tree (root + all reachable nodes across variations)."""
    result: list[chess.pgn.GameNode] = [node]
    for child in node.variations:
        result.extend(_walk_all_nodes(child))
    return result


def _select_nodes(game: chess.pgn.Game, scope: str) -> list[chess.pgn.GameNode]:
    """Return target nodes for evaluation based on scope.

    ``"leaves"``        — every ``is_end()`` node in the full tree (all variations).
    ``"branch-points"`` — leaves PLUS nodes with more than one variation (forks).
    ``"all"``           — every node in the tree including the root game node.

    Raises ``ValueError`` for unknown scope strings.
    """
    if scope not in (TERMINAL, BRANCHES, ALL):
        raise ValueError(f"Unknown scope {scope!r}. Must be one of: {TERMINAL!r}, {BRANCHES!r}, {ALL!r}")

    all_nodes = _walk_all_nodes(game)

    if scope == ALL:
        return all_nodes

    selected: list[chess.pgn.GameNode] = []
    for node in all_nodes:
        if node.is_end():
            selected.append(node)
        elif scope == BRANCHES and len(node.variations) > 1:
            selected.append(node)
    return selected


# ── Annotation ────────────────────────────────────────────────────────────────

def annotate_evals(
    game: chess.pgn.Game,
    provider: EvalProvider,
    *,
    scope: str = BRANCHES,
    overwrite: bool = False,
) -> int:
    """Annotate target nodes in the game tree with ``[%eval ...]`` PGN annotations.

    Walks the full game tree (all variations), selects target nodes per ``scope``,
    evaluates each unique normalized FEN once via ``provider``, and appends
    ``[%eval <formatted>]`` to the node's comment.

    Args:
        game:      The game tree to annotate (mutated in place).
        provider:  Callable mapping a ``chess.Board`` to a ``PovScore`` or ``None``.
                   ``None`` means "no eval available" — that node is left unannotated.
        scope:     Which nodes to target: ``TERMINAL`` (leaves), ``BRANCHES``
                   (leaves + branch points), or ``ALL``.
        overwrite: When ``False`` (default), nodes that already carry a ``[%eval ...]``
                   annotation are skipped. When ``True``, existing evals are replaced.

    Returns:
        The count of nodes actually annotated in this call.
    """
    targets = _select_nodes(game, scope)

    # De-duplicate: map normalized FEN → PovScore | None
    fen_cache: dict[str, chess.engine.PovScore | None] = {}
    annotated = 0

    for node in targets:
        # Skip nodes with no move (root of a non-empty game is the game node itself,
        # which has no associated board position for the root unless scope=ALL)
        if isinstance(node, chess.pgn.Game) and not node.variations and scope != ALL:
            continue

        existing = node.comment
        if not overwrite and chess.pgn.EVAL_REGEX.search(existing):
            continue

        board = node.board()
        nfen = normalize_fen(board.fen())

        if nfen not in fen_cache:
            fen_cache[nfen] = provider(board)

        pov_score = fen_cache[nfen]
        if pov_score is None:
            continue

        formatted = format_eval(pov_score)
        annotation = f"[%eval {formatted}]"

        if overwrite:
            existing = _EVAL_STRIP_RE.sub("", existing)

        node.comment = (existing + " " + annotation).strip()
        annotated += 1

    return annotated


# ── Engine provider factory ───────────────────────────────────────────────────


def make_engine_provider(
    engine_path: str = DEFAULT_ENGINE,
    limit: chess.engine.Limit | None = None,
    *,
    multipv: int | None = None,
) -> tuple[EvalProvider, Callable[[], None]]:
    """Spawn a UCI engine once and return a (provider, closer) pair.

    The provider evaluates any board position by calling ``engine.analyse``
    on the long-lived subprocess; the closer shuts the engine down cleanly.

    Args:
        engine_path: Path to (or name of) the engine binary.  Defaults to
                     ``DEFAULT_ENGINE`` (``"stockfish"``).
        limit:       Search budget.  Defaults to ``Limit(depth=DEFAULT_DEPTH)``.
        multipv:     When set, passes ``multipv=multipv`` to ``engine.analyse``
                     (returns a list of InfoDicts); the best-score entry is used.

    Returns:
        ``(provider, closer)`` where:

        - ``provider(board)`` returns a ``PovScore`` or ``None`` (on engine error).
        - ``closer()`` calls ``engine.quit()``; safe to call more than once.

    Raises:
        EngineUnavailable: when the binary is missing or the subprocess fails to
            start.  Install Stockfish (https://stockfishchess.org/download/) and
            make sure it is on PATH, or pass its absolute path as *engine_path*.
    """
    if limit is None:
        limit = chess.engine.Limit(depth=DEFAULT_DEPTH)

    try:
        engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    except (FileNotFoundError, chess.engine.EngineError, chess.engine.EngineTerminatedError) as exc:
        raise EngineUnavailable(
            f"Could not start engine {engine_path!r}: {exc}. "
            "Install Stockfish (https://stockfishchess.org/download/) and ensure "
            "it is on PATH, or pass its absolute path via --engine."
        ) from exc

    _closed = False

    def provider(board: chess.Board) -> chess.engine.PovScore | None:
        try:
            if multipv is not None:
                infos: list[chess.engine.InfoDict] = engine.analyse(board, limit, multipv=multipv)
                return infos[0]["score"]
            else:
                info: chess.engine.InfoDict = engine.analyse(board, limit)
                return info["score"]
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, Exception):
            return None

    def closer() -> None:
        nonlocal _closed
        if _closed:
            return
        _closed = True
        try:
            engine.quit()
        except Exception:
            pass

    return provider, closer
