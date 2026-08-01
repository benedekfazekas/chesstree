#!/usr/bin/env python3
"""Fetch games, filter by starting position, and merge opening slices into one PGN.

POC: uses chesstree.opening_divider to compute the opening cutoff locally.
Leaf evals prefer a local engine (Stockfish); fall back to inline [%eval] annotations.
Sources are wired through sources.py; Lichess and Chess.com can be merged in one run.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

import chess
import chess.engine
import chess.pgn

import sources
from sources import SourceGame, SourceSpec

from chesstree import leaf_evaluator, opening_divider
from chesstree.utils import normalize_fen


_EVAL_RE = re.compile(r"\[%eval\s+([^\]]+)\]")


# ── Leaf-label helper ─────────────────────────────────────────────────────────


def _leaf_label(opponent: str, url: str) -> str:
    """Return the leaf-label string for *opponent* and *url*.

    When *url* is non-empty the label is ``vs [opponent](url)`` (markdown link).
    When *url* is empty (e.g. future local-directory source) the label is
    ``vs opponent`` — no broken ``vs [opp]()`` link.
    """
    return f"vs [{opponent}]({url})" if url else f"vs {opponent}"


# ── Core pipeline functions ───────────────────────────────────────────────────


def extract_eval(comment: str) -> Optional[str]:
    """Return the numeric/mate eval string from a PGN move comment, or None.

    Example: ``'[%eval 0.43]'`` → ``'0.43'``, ``'[%eval #-3]'`` → ``'#-3'``.
    """
    m = _EVAL_RE.search(comment)
    return m.group(1).strip() if m else None


def find_filter_ply(boards: list[chess.Board], target_fen: str) -> Optional[int]:
    """Return the first ply index where *boards[ply]* matches *target_fen*, or None.

    Ply index is 0-based: 0 = initial position, 1 = after white's first move, etc.
    """
    for ply, board in enumerate(boards):
        if normalize_fen(board.fen()) == target_fen:
            return ply
    return None


def create_slice(
    src: SourceGame,
    filter_ply: int,
    opening_end_ply: int,
) -> Optional[tuple[chess.pgn.Game, str]]:
    """Build a sliced game from ply 0 to *opening_end_ply* (inclusive).

    Copies each main-line move with its comment and NAGs from the source PGN.
    The preamble moves (0 to filter_ply) and the post-filter moves
    (filter_ply+1 to opening_end_ply) are both included so the merged game
    can show alternative move orders leading to the filter FEN as well as
    post-filter continuations.
    Appends ``[%opening_end]`` to the last node's comment.

    Returns ``(sliced_game, leaf_label)`` or ``None`` if the game should be skipped.
    """
    game_id = src.game_id

    nodes: list[chess.pgn.ChildNode] = []
    current: chess.pgn.GameNode = src.game
    for _ in range(opening_end_ply):
        nxt = current.next()
        if nxt is None:
            print(
                f"Warning: game {game_id} ends before ply {opening_end_ply}, skipping",
                file=sys.stderr,
            )
            return None
        current = nxt
        nodes.append(current)  # type: ignore[arg-type]

    if not nodes:
        print(f"Warning: game {game_id} has empty slice, skipping", file=sys.stderr)
        return None

    sliced = chess.pgn.Game()
    cursor: chess.pgn.GameNode = sliced
    for src_node in nodes:
        child = cursor.add_variation(src_node.move)
        child.comment = src_node.comment
        child.nags = set(src_node.nags)
        cursor = child

    existing = cursor.comment.strip()
    cursor.comment = (existing + " [%opening_end]").strip()

    label = _leaf_label(src.opponent, src.url)
    return sliced, label


def merge_game_slices(slices: list[tuple[chess.pgn.Game, str]]) -> chess.pgn.Game:
    """Merge sliced games into a single PGN game tree with variations.

    Shared move prefixes become a common trunk; diverging moves become variations.
    Each game's leaf label is appended to the corresponding leaf node's comment
    so multiple games at the same leaf accumulate as a space-separated list.
    """
    merged = chess.pgn.Game()

    for slice_game, label in slices:
        cursor: chess.pgn.GameNode = merged
        src_node: Optional[chess.pgn.GameNode] = slice_game.next()

        while src_node is not None:
            move = src_node.move
            matching: Optional[chess.pgn.ChildNode] = None
            for var in cursor.variations:
                if var.move == move:
                    matching = var
                    break

            if matching is not None:
                cursor = matching
            else:
                child = cursor.add_variation(move)
                child.comment = src_node.comment
                child.nags = set(src_node.nags)
                cursor = child

            src_node = src_node.next()

        existing = cursor.comment.strip()
        cursor.comment = (existing + " " + label).strip()

    return merged


def _collect_leaves(merged: chess.pgn.Game) -> list[chess.pgn.ChildNode]:
    """Return all terminal leaf nodes in the merged game tree."""
    leaves: list[chess.pgn.ChildNode] = []
    stack: list[chess.pgn.ChildNode] = list(merged.variations)
    while stack:
        node = stack.pop()
        if not node.variations:
            leaves.append(node)
        else:
            stack.extend(node.variations)
    return leaves


def apply_leaf_evals(
    merged: chess.pgn.Game,
    provider: Optional[leaf_evaluator.EvalProvider],
) -> None:
    """Annotate each terminal leaf of the merged game tree with its evaluation.

    **Two-phase algorithm (G3 / H1 fix):**

    Phase 1 — resolve: build a ``fen → eval_str`` map.

    * Provider sub-pass: call *provider* at most once per unique normalized FEN
      (expensive engine calls are de-duplicated here).  If the provider returns
      ``None`` for a FEN, that FEN falls through to the inline-eval fallback.
    * Fallback sub-pass: for every FEN still unmapped (or mapped to ``None``),
      scan *all* leaves sharing that FEN and resolve to the **first non-``None``**
      ``extract_eval`` found.  Walking all leaves ensures that a Chess.com leaf
      visited first (no inline eval) cannot pin ``None`` and discard a Lichess
      leaf's eval — order-independent.

    Phase 2 — write: annotate every leaf from the resolved map.  Same-FEN
    leaves all receive the same eval string.

    When an eval string is found, the leaf comment gets both a machine-readable
    ``[%eval <value>]`` PGN command annotation and a human-readable
    ``: **<value>**`` markdown suffix.  Any pre-existing ``[%eval ...]`` is
    replaced so the tag stays consistent.
    """
    all_leaves = _collect_leaves(merged)

    # ── Phase 1: resolve FEN → eval_str ──────────────────────────────────────

    fen_eval_map: dict[str, Optional[str]] = {}

    # Provider sub-pass — call once per unique FEN.
    if provider is not None:
        for leaf in all_leaves:
            nfen = normalize_fen(leaf.board().fen())
            if nfen not in fen_eval_map:
                score = provider(leaf.board())
                fen_eval_map[nfen] = (
                    leaf_evaluator.format_eval(score) if score is not None else None
                )

    # Fallback sub-pass — first non-None inline eval wins for each FEN.
    for leaf in all_leaves:
        nfen = normalize_fen(leaf.board().fen())
        if fen_eval_map.get(nfen) is None:  # covers absent key AND explicit None
            inline = extract_eval(leaf.comment)
            if inline is not None:
                fen_eval_map[nfen] = inline

    # ── Phase 2: write evals to all leaves ───────────────────────────────────

    for leaf in all_leaves:
        nfen = normalize_fen(leaf.board().fen())
        cached = fen_eval_map.get(nfen)
        if cached is not None:
            base = _EVAL_RE.sub("", leaf.comment)
            base = re.sub(r"\s{2,}", " ", base).strip()
            leaf.comment = f"{base}: **{cached}** [%eval {cached}]".strip()


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch games for one or more accounts, filter by starting position FEN, "
            "and merge opening slices from all sources into one PGN."
        )
    )

    # ── Per-source flags ──────────────────────────────────────────────────────
    parser.add_argument("--lichess-username", default=None, help="Lichess username")
    parser.add_argument(
        "--lichess-max-games",
        type=int,
        default=None,
        dest="lichess_max_games",
        help="Maximum number of games to fetch from Lichess (default: all games)",
    )
    parser.add_argument(
        "--lichess-cache",
        metavar="FILE",
        default=None,
        dest="lichess_cache",
        help=(
            "Lichess JSON cache file.  If the file exists, games are loaded from it "
            "instead of calling Lichess.  If it does not exist, games are fetched and "
            "saved there."
        ),
    )
    parser.add_argument("--chesscom-username", default=None, help="Chess.com username")
    parser.add_argument(
        "--chesscom-max-games",
        type=int,
        default=None,
        dest="chesscom_max_games",
        help="Maximum number of games to fetch from Chess.com (default: all games)",
    )
    parser.add_argument(
        "--chesscom-cache",
        metavar="FILE",
        default=None,
        dest="chesscom_cache",
        help=(
            "Chess.com JSON cache file.  If the file exists, games are loaded from it "
            "instead of calling Chess.com.  If it does not exist, games are fetched and "
            "saved there."
        ),
    )

    # ── Shared flags ──────────────────────────────────────────────────────────
    parser.add_argument(
        "--fen",
        required=True,
        help="Filter FEN: only games that reach this position are included",
    )
    parser.add_argument(
        "--color",
        choices=["white", "black"],
        default=None,
        help="Filter games by the side played (default: both sides)",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM",
        default=None,
        help="Include games from this month onwards (inclusive)",
    )
    parser.add_argument(
        "--until",
        metavar="YYYY-MM",
        default=None,
        help="Include games up to and including this month (inclusive)",
    )
    parser.add_argument("--output", help="Output PGN file (default: stdout)")
    parser.add_argument(
        "--event",
        default=None,
        metavar="TITLE",
        help=(
            "Override the PGN Event header (game title).  When set, the automatic "
            "opening name/ECO resolution is skipped."
        ),
    )
    parser.add_argument(
        "--engine",
        default=leaf_evaluator.DEFAULT_ENGINE,
        help=f"UCI engine path or name (default: {leaf_evaluator.DEFAULT_ENGINE!r})",
    )
    parser.add_argument(
        "--eval-depth",
        type=int,
        default=None,
        dest="eval_depth",
        help="Engine search depth (default: engine default depth)",
    )
    parser.add_argument(
        "--eval-time",
        type=float,
        default=None,
        dest="eval_time",
        help="Engine search time in seconds; takes precedence over --eval-depth",
    )
    args = parser.parse_args()

    if not args.lichess_username and not args.chesscom_username:
        parser.error(
            "at least one source username is required "
            "(use --lichess-username or --chesscom-username)"
        )

    # ── Build source specs ────────────────────────────────────────────────────

    specs: list[SourceSpec] = []
    if args.lichess_username:
        specs.append(
            SourceSpec(
                source="lichess",
                username=args.lichess_username,
                max_games=args.lichess_max_games,
                cache_path=Path(args.lichess_cache) if args.lichess_cache else None,
            )
        )
    if args.chesscom_username:
        specs.append(
            SourceSpec(
                source="chesscom",
                username=args.chesscom_username,
                max_games=args.chesscom_max_games,
                cache_path=Path(args.chesscom_cache) if args.chesscom_cache else None,
            )
        )

    target_fen = normalize_fen(args.fen)

    # ── Acquire and filter ────────────────────────────────────────────────────

    all_source_games = [
        g
        for spec in specs
        for g in sources.iter_games(
            spec, color=args.color, since=args.since, until=args.until
        )
    ]

    slices: list[tuple[chess.pgn.Game, str]] = []
    filtered_sources: list[sources.SourceGame] = []
    filtered_count = 0
    skipped_count = 0

    for src in all_source_games:
        opening_end_ply: Optional[int] = opening_divider.opening_end_ply(src.boards)
        if opening_end_ply is None:
            # F4 fix: boards[0] is initial position, len(boards)-1 is ply count.
            opening_end_ply = len(src.boards) - 1
            print(
                f"Info: game {src.game_id} opening did not end "
                f"(stayed in opening), using full game ({opening_end_ply} plies)",
                file=sys.stderr,
            )

        filter_ply = find_filter_ply(src.boards, target_fen)
        if filter_ply is None:
            continue
        filtered_count += 1

        if opening_end_ply <= filter_ply:
            skipped_count += 1
            print(
                f"Warning: game {src.game_id} opening_end_ply {opening_end_ply} "
                f"<= filter_ply {filter_ply}, skipping",
                file=sys.stderr,
            )
            continue

        result = create_slice(src, filter_ply, opening_end_ply)
        if result is not None:
            slices.append(result)
            filtered_sources.append(src)
        else:
            skipped_count += 1

    print(
        f"Filter matched: {filtered_count} games reached the filter position",
        file=sys.stderr,
    )
    print(
        f"Skipped: {skipped_count} games (game too short, or missing pgn/moves)",
        file=sys.stderr,
    )
    print(f"Merging {len(slices)} game slices...", file=sys.stderr)

    if not slices:
        print("No matching games found.", file=sys.stderr)
        sys.exit(1)

    # ── Build engine provider ─────────────────────────────────────────────────

    provider: Optional[leaf_evaluator.EvalProvider] = None
    closer = lambda: None  # noqa: E731
    engine_unavailable_reason: Optional[str] = None
    try:
        engine_limit: Optional[chess.engine.Limit] = None
        if args.eval_time is not None:
            engine_limit = chess.engine.Limit(time=args.eval_time)
        elif args.eval_depth is not None:
            engine_limit = chess.engine.Limit(depth=args.eval_depth)
        provider, closer = leaf_evaluator.make_engine_provider(args.engine, engine_limit)
    except leaf_evaluator.EngineUnavailable as exc:
        engine_unavailable_reason = str(exc)
        print(
            f"Warning: engine unavailable, falling back to inline evals: {exc}",
            file=sys.stderr,
        )

    try:
        merged = merge_game_slices(slices)
        apply_leaf_evals(merged, provider)

        # ── Eval-coverage warning (G2 / H2) ──────────────────────────────────
        all_leaves = _collect_leaves(merged)
        uncovered = sum(
            1 for leaf in all_leaves if not _EVAL_RE.search(leaf.comment)
        )
        if uncovered > 0:
            n, m = uncovered, len(all_leaves)
            msg = (
                f"Warning: {n} of {m} leaves have no [%eval] annotation and will not be\n"
                f"         coloured or included in the variation summary."
            )
            if engine_unavailable_reason is not None:
                msg += f"\n         (no local engine: {engine_unavailable_reason})"
            print(msg, file=sys.stderr)

        # Set Event header: manual override > opening from first Lichess game > fallback.
        source_str = " ".join(f"{s.username} ({s.source})" for s in specs)
        if args.event:
            merged.headers["Event"] = args.event
        else:
            first_opening = next(
                (src.opening for src in filtered_sources if src.opening),
                None,
            )
            if first_opening:
                eco = first_opening.get("eco", "")
                name = first_opening.get("name", "")
                opening_str = f"{eco} {name}".strip()
                merged.headers["Event"] = f"{opening_str} performance for {source_str}"
            else:
                # G1 fix: replace the single-username Event header with source:username pairs.
                merged.headers["Event"] = (
                    f"Opening repertoire performance for {source_str}"
                )

        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        pgn_str = merged.accept(exporter)

        if args.output:
            with open(args.output, "w") as f:
                f.write(pgn_str)
                f.write("\n")
            print(f"Written to {args.output}", file=sys.stderr)
        else:
            sys.stdout.write(pgn_str)
            sys.stdout.write("\n")
    finally:
        closer()


if __name__ == "__main__":
    main()
