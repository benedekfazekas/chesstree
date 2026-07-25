#!/usr/bin/env python3
"""Fetch Lichess games, filter by starting position, and merge opening slices into one PGN.

POC: uses chesstree.opening_divider to compute the opening cutoff locally and relies on
inline [%eval] annotations already embedded in the source PGN by Lichess.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
from typing import Optional

import chess
import chess.pgn

from chesstree import opening_divider


_EVAL_RE = re.compile(r"\[%eval\s+([^\]]+)\]")


def _boards_from_moves(moves_str: str) -> list[chess.Board] | None:
    """Return [initial, after_move_1, ...] from a space-separated SAN string.

    Returns None if any SAN is illegal (caller should skip the game).
    """
    board = chess.Board()
    boards: list[chess.Board] = [board.copy()]
    for san in moves_str.split():
        try:
            board.push_san(san)
        except ValueError:
            return None
        boards.append(board.copy())
    return boards


def extract_eval(comment: str) -> Optional[str]:
    """Return the numeric/mate eval string from a PGN move comment, or None.

    Example: ``'[%eval 0.43]'`` → ``'0.43'``, ``'[%eval #-3]'`` → ``'#-3'``.
    """
    m = _EVAL_RE.search(comment)
    return m.group(1).strip() if m else None


def get_opponent_name(game_dict: dict, username: str) -> str:
    """Return the opponent's display name for the requesting username.

    Falls back to ``userId`` when ``user.name`` is absent, and to ``"?"`` when
    neither field is available (e.g. anonymous or bot games).
    """
    players = game_dict.get("players") or {}
    white_info = players.get("white") or {}
    black_info = players.get("black") or {}
    white_user = white_info.get("user") or {}
    black_user = black_info.get("user") or {}
    white_name = white_user.get("name") or white_info.get("userId") or "?"
    black_name = black_user.get("name") or black_info.get("userId") or "?"

    if white_name.lower() == username.lower():
        return black_name
    if black_name.lower() == username.lower():
        return white_name
    return black_name


def normalize_fen(fen: str) -> str:
    """Return the first 4 FEN fields (board, turn, castling, en passant).

    Drops halfmove clock and fullmove counter so that position comparison
    ignores bookkeeping-only differences.
    """
    return " ".join(fen.split()[:4])


def find_filter_ply(game_dict: dict, target_fen: str) -> Optional[int]:
    """Return the first ply index where the game position matches target_fen, or None.

    Ply index is 0-based: 0 = initial position, 1 = after white's first move, etc.
    Uses the top-level ``moves`` field (space-separated SAN string) for replay.
    """
    board = chess.Board()
    if normalize_fen(board.fen()) == target_fen:
        return 0

    moves_str = game_dict.get("moves", "").strip()
    if not moves_str:
        return None

    for ply, san in enumerate(moves_str.split(), start=1):
        try:
            board.push_san(san)
        except ValueError:
            return None
        if normalize_fen(board.fen()) == target_fen:
            return ply

    return None


def fetch_lichess_games(
    username: str,
    max_games: Optional[int] = None,
    color: Optional[str] = None,
) -> list[dict]:
    """Fetch games from the Lichess API as NDJSON and return as a list of dicts.

    Requests: moves, evals, opening, pgnInJson, tags.
    When max_games is None the ``max`` parameter is omitted and Lichess returns all games.
    When color is None the ``color`` parameter is omitted and both sides are returned.
    """
    params = "moves=true&evals=true&opening=true&pgnInJson=true&tags=true"
    if max_games is not None:
        params += f"&max={max_games}"
    if color is not None:
        params += f"&color={color}"
    url = f"https://lichess.org/api/games/user/{username}?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/x-ndjson",
            "User-Agent": "chesstree/merge_openings (https://github.com/benedekfazekas/chesstree)",
        },
    )
    games: list[dict] = []
    with urllib.request.urlopen(req) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if line:
                games.append(json.loads(line))
    return games


def load_games_from_cache(path: str) -> list[dict]:
    """Load a previously saved list of Lichess game dicts from a JSON cache file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_games_to_cache(games: list[dict], path: str) -> None:
    """Save a list of Lichess game dicts to a JSON cache file for later reuse."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(games, f)


def create_slice(
    game_dict: dict,
    filter_ply: int,
    opening_end_ply: int,
    username: str,
) -> Optional[tuple[chess.pgn.Game, str]]:
    """Build a sliced game from ply 0 to opening_end_ply (inclusive).

    Copies each main-line move with its comment and NAGs from the source PGN.
    The preamble moves (0 to filter_ply) and the post-filter moves
    (filter_ply+1 to opening_end_ply) are both included so the merged game
    can show alternative move orders leading to the filter FEN as well as
    post-filter continuations.
    Appends ``[%opening_end]`` to the last node's comment.

    Returns ``(sliced_game, leaf_label)`` where ``leaf_label`` has the form
    ``"vs [Opponent](url): **eval**"`` (eval omitted when absent), or ``None``
    if the game should be skipped.
    """
    game_id = game_dict.get("id", "?")

    pgn_str = game_dict.get("pgn")
    if not pgn_str:
        print(f"Warning: game {game_id} has no pgn field, skipping", file=sys.stderr)
        return None

    source_game = chess.pgn.read_game(io.StringIO(pgn_str))
    if source_game is None:
        print(f"Warning: could not parse pgn for game {game_id}, skipping", file=sys.stderr)
        return None

    # Walk main line, collecting all opening_end_ply nodes (preamble + post-filter).
    nodes: list[chess.pgn.ChildNode] = []
    current: chess.pgn.GameNode = source_game
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

    # Append [%opening_end] to the leaf comment, preserving any existing content.
    existing = cursor.comment.strip()
    cursor.comment = (existing + " [%opening_end]").strip()

    opponent = get_opponent_name(game_dict, username)
    url = f"https://lichess.org/{game_id}"
    eval_val = extract_eval(nodes[-1].comment) if nodes else None
    label = f"vs [{opponent}]({url})"
    if eval_val is not None:
        label += f": **{eval_val}**"

    return sliced, label


def merge_game_slices(slices: list[tuple[chess.pgn.Game, str]]) -> chess.pgn.Game:
    """Merge sliced games into a single PGN game tree with variations.

    Shared move prefixes become a common trunk; diverging moves become variations.
    Each game's leaf label (``"vs [Opponent](url): **eval**"``) is appended to the
    corresponding leaf node's comment so multiple games at the same leaf accumulate
    as a space-separated list of labels.
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

        # Accumulate leaf label on the leaf node.
        existing = cursor.comment.strip()
        cursor.comment = (existing + " " + label).strip()

    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Lichess games for a user, filter by starting position FEN, "
            "and merge opening slices into one PGN."
        )
    )
    parser.add_argument("--username", required=True, help="Lichess username")
    parser.add_argument(
        "--fen",
        required=True,
        help="Filter FEN: only games that reach this position are included",
    )
    parser.add_argument("--output", help="Output PGN file (default: stdout)")
    parser.add_argument(
        "--color",
        choices=["white", "black"],
        default=None,
        help="Filter games by the side played (default: both sides)",
    )
    parser.add_argument(
        "--cache",
        metavar="FILE",
        default=None,
        help=(
            "JSON cache file. If the file exists, games are loaded from it instead of "
            "calling Lichess. If the file does not exist, games are fetched and saved there."
        ),
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        dest="max_games",
        help="Maximum number of games to fetch from Lichess (default: all games)",
    )
    args = parser.parse_args()

    import os

    target_fen = normalize_fen(args.fen)

    if args.cache and os.path.exists(args.cache):
        print(f"Loading games from cache: {args.cache}", file=sys.stderr)
        games = load_games_from_cache(args.cache)
        print(f"Loaded {len(games)} games from cache", file=sys.stderr)
    else:
        limit_msg = f"up to {args.max_games}" if args.max_games is not None else "all"
        print(f"Fetching {limit_msg} games for {args.username}...", file=sys.stderr)
        games = fetch_lichess_games(args.username, args.max_games, args.color)
        print(f"Fetched {len(games)} games", file=sys.stderr)
        if args.cache:
            save_games_to_cache(games, args.cache)
            print(f"Saved games to cache: {args.cache}", file=sys.stderr)

    slices: list[tuple[chess.pgn.Game, str]] = []
    filtered_count = 0
    skipped_count = 0

    for game_dict in games:
        if game_dict.get("variant", "standard") != "standard":
            continue

        moves_str = game_dict.get("moves", "").strip()
        if not moves_str:
            skipped_count += 1
            print(
                f"Warning: game {game_dict.get('id', '?')} has no moves, skipping",
                file=sys.stderr,
            )
            continue

        boards = _boards_from_moves(moves_str)
        if boards is None:
            skipped_count += 1
            print(
                f"Warning: game {game_dict.get('id', '?')} has illegal SAN in moves, skipping",
                file=sys.stderr,
            )
            continue

        opening_end_ply: Optional[int] = opening_divider.opening_end_ply(boards)
        if opening_end_ply is None:
            opening_end_ply = len(moves_str.split())
            print(
                f"Info: game {game_dict.get('id', '?')} opening did not end "
                f"(stayed in opening), using full game ({opening_end_ply} plies)",
                file=sys.stderr,
            )

        filter_ply = find_filter_ply(game_dict, target_fen)
        if filter_ply is None:
            continue
        filtered_count += 1

        if opening_end_ply <= filter_ply:
            skipped_count += 1
            print(
                f"Warning: game {game_dict.get('id', '?')} opening_end_ply {opening_end_ply} "
                f"<= filter_ply {filter_ply}, skipping",
                file=sys.stderr,
            )
            continue

        result = create_slice(game_dict, filter_ply, opening_end_ply, args.username)
        if result is not None:
            slices.append(result)
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

    assert slices
    merged = merge_game_slices(slices)
    merged.headers["Event"] = f"Opening repertoire ({args.username})"

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


if __name__ == "__main__":
    main()
