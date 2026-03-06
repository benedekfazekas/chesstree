from __future__ import annotations

import json
from typing import List, Optional, TextIO

import chess
import chess.pgn


def _process_moves(game_node: chess.pgn.GameNode, moves: List[dict]) -> None:
    """
    Recursively build a chess.pgn game tree from a JSON moves list.

    Each entry is either:
      - A move dict: {"san": ..., "comments": [...], "nags": [...], ...}
      - A variation dict: {"variation": [<moves list>]}

    A variation entry represents an alternative to the preceding move in the
    current list, branching from the parent of the node built for that move.
    This mirrors the visitor call order produced by chess.pgn: variations are
    emitted after the main-line move they shadow, at whatever nesting depth
    they occur in the game tree.
    """
    current_node = game_node
    for entry in moves:
        if "variation" in entry:
            # Variation branches from the parent of the last move we built.
            # current_node.parent is None only for the game root, which can
            # never be preceded by a move, so this guard is purely defensive.
            if current_node.parent is not None:
                _process_moves(current_node.parent, entry["variation"])
        else:
            board = current_node.board()
            move = board.parse_san(entry["san"])
            child_node = current_node.add_variation(move)

            comments = entry.get("comments", [])
            if comments:
                # chess.pgn stores a single comment string; join multiple entries
                child_node.comment = " ".join(comments)

            for nag_entry in entry.get("nags", []):
                # JSON round-trip turns integer keys into strings ("2" not 2)
                nag_key = int(list(nag_entry.keys())[0])
                child_node.nags.add(nag_key)

            current_node = child_node


def parse_json(json_data: dict) -> chess.pgn.Game:
    """
    Parse a JSON dict (as produced by JsonExporter) into a chess.pgn.Game.

    Board images (board_img_before / board_img_after) are ignored.
    EDN input is not supported; pass a Python dict parsed from JSON.
    """
    game = chess.pgn.Game()

    # Replace chess.pgn's default headers with those stored in the JSON.
    for key in list(game.headers.keys()):
        del game.headers[key]
    for key, value in json_data.get("headers", {}).items():
        game.headers[key] = value

    # Fall back to the top-level "result" field when headers were not exported.
    if "Result" not in game.headers:
        result = json_data.get("result")
        if result:
            game.headers["Result"] = result

    _process_moves(game, json_data.get("moves", []))

    return game


def read_json(source: TextIO) -> chess.pgn.Game:
    """Read JSON from a file-like object and return a chess.pgn.Game."""
    return parse_json(json.load(source))
