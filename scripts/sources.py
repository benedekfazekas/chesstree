#!/usr/bin/env python3
"""Source-agnostic acquisition layer for merge_openings.py.

Defines the source contract (SourceGame, SourceSpec) and the per-source
generator interface (iter_games).  The Lichess adapter is the only
implementation in Part 1; Part 2 adds Chess.com purely additively.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import chess
import chess.pgn

from chesstree.utils import normalize_fen

_EVAL_RE = re.compile(r"\[%eval\s+[^\]]+\]")

# ── Contract dataclasses ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourceGame:
    """A single game from any source, normalised to a source-agnostic shape.

    ``boards`` is derived once from the parsed PGN main line and reused by
    both the FEN filter and ``opening_divider.opening_end_ply`` — the
    Lichess-only ``moves`` SAN string is not carried.
    """

    game: chess.pgn.Game          # parsed source game
    boards: list[chess.Board]     # [initial, after ply 1, …]; main line only
    opponent: str                 # display name of the non-requesting player
    url: str                      # canonical game URL for the leaf label
    source: str                   # "lichess" | "chesscom" | "local"
    game_id: str                  # for warning messages
    has_inline_eval: bool         # True when the PGN carries [%eval …]


@dataclass(frozen=True)
class SourceSpec:
    """Per-source acquisition parameters, built from CLI flags in ``main``."""

    source: str                   # "lichess" | "chesscom" | "local"
    username: str                 # per-platform username (or directory, for local)
    max_games: int | None
    cache_path: Path | None


# ── Router ────────────────────────────────────────────────────────────────────


def iter_games(
    spec: SourceSpec,
    *,
    color: str | None = None,
    since_ms: int | None = None,
    until_ms: int | None = None,
) -> Iterator[SourceGame]:
    """Yield :class:`SourceGame` objects for every valid game in *spec*.

    Shared query parameters (*color*, *since_ms*, *until_ms*) are forwarded
    to the adapter that knows how to apply them — server-side for Lichess,
    client-side for Chess.com (Part 2).
    """
    if spec.source == "lichess":
        yield from _iter_lichess_games(
            spec, color=color, since_ms=since_ms, until_ms=until_ms
        )
    else:
        raise ValueError(f"Unknown source: {spec.source!r}")


# ── Lichess adapter ───────────────────────────────────────────────────────────


def get_opponent_name(game_dict: dict, username: str) -> str:
    """Return the opponent's display name for *username* (Lichess payload format).

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


def _boards_from_game(game: chess.pgn.Game) -> list[chess.Board]:
    """Return ``[initial, after_ply_1, …]`` from the main line of *game*."""
    board = game.board()
    boards: list[chess.Board] = [board.copy()]
    node = game.next()
    while node is not None:
        board.push(node.move)
        boards.append(board.copy())
        node = node.next()
    return boards


def _build_lichess_source_game(
    game_dict: dict,
    username: str,
) -> Optional[SourceGame]:
    """Parse one Lichess game dict into a :class:`SourceGame`, or ``None`` to skip."""
    game_id = game_dict.get("id", "?")

    if game_dict.get("variant", "standard") != "standard":
        return None

    pgn_str = game_dict.get("pgn")
    if not pgn_str:
        print(
            f"Warning: game {game_id} has no pgn field, skipping", file=sys.stderr
        )
        return None

    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        print(
            f"Warning: could not parse pgn for game {game_id}, skipping",
            file=sys.stderr,
        )
        return None

    boards = _boards_from_game(game)
    if len(boards) <= 1:
        print(
            f"Warning: game {game_id} has no moves, skipping", file=sys.stderr
        )
        return None

    opponent = get_opponent_name(game_dict, username)
    url = f"https://lichess.org/{game_id}"
    has_inline_eval = bool(_EVAL_RE.search(pgn_str))

    return SourceGame(
        game=game,
        boards=boards,
        opponent=opponent,
        url=url,
        source="lichess",
        game_id=game_id,
        has_inline_eval=has_inline_eval,
    )


def fetch_lichess_games(
    username: str,
    max_games: Optional[int] = None,
    color: Optional[str] = None,
    since_ms: Optional[int] = None,
    until_ms: Optional[int] = None,
) -> list[dict]:
    """Fetch games from the Lichess API as NDJSON and return as a list of dicts.

    Requests: moves, evals, opening, pgnInJson, tags.
    ``since_ms`` / ``until_ms`` are epoch milliseconds (UTC); both are optional.
    """
    params = "moves=true&evals=true&opening=true&pgnInJson=true&tags=true"
    if max_games is not None:
        params += f"&max={max_games}"
    if color is not None:
        params += f"&color={color}"
    if since_ms is not None:
        params += f"&since={since_ms}"
    if until_ms is not None:
        params += f"&until={until_ms}"
    url = f"https://lichess.org/api/games/user/{username}?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/x-ndjson",
            "User-Agent": (
                "chesstree/merge_openings"
                " (https://github.com/benedekfazekas/chesstree)"
            ),
        },
    )
    games: list[dict] = []
    with urllib.request.urlopen(req) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if line:
                games.append(json.loads(line))
    return games


def load_cache(path: Path, spec: SourceSpec) -> list[dict]:
    """Load games from *path*, validating that it matches *spec*.

    Raises :class:`ValueError` when the source or username tag mismatches, or
    when the file is a legacy bare-list cache (delete and refetch).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        raise ValueError(
            f"Cache file {path} is in legacy format (bare JSON list). "
            "Delete it and refetch."
        )
    if data.get("source") != spec.source:
        raise ValueError(
            f"Cache file {path} was written for source {data.get('source')!r}, "
            f"expected {spec.source!r}. Delete it and refetch."
        )
    if data.get("username") != spec.username:
        raise ValueError(
            f"Cache file {path} was written for username {data.get('username')!r}, "
            f"expected {spec.username!r}. Delete it and refetch."
        )
    return data["games"]


def save_cache(games: list[dict], path: Path, spec: SourceSpec) -> None:
    """Save *games* to *path* tagged with *spec*.source and *spec*.username."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"source": spec.source, "username": spec.username, "games": games}, f
        )


def _iter_lichess_games(
    spec: SourceSpec,
    *,
    color: Optional[str] = None,
    since_ms: Optional[int] = None,
    until_ms: Optional[int] = None,
) -> Iterator[SourceGame]:
    """Yield :class:`SourceGame` objects from Lichess, using the cache when present."""
    if spec.cache_path is not None and os.path.exists(spec.cache_path):
        print(f"Loading games from cache: {spec.cache_path}", file=sys.stderr)
        raw_games = load_cache(spec.cache_path, spec)
        print(f"Loaded {len(raw_games)} games from cache", file=sys.stderr)
    else:
        limit_msg = (
            f"up to {spec.max_games}" if spec.max_games is not None else "all"
        )
        print(
            f"Fetching {limit_msg} games for {spec.username} from lichess...",
            file=sys.stderr,
        )
        raw_games = fetch_lichess_games(
            spec.username,
            max_games=spec.max_games,
            color=color,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        print(f"Fetched {len(raw_games)} games", file=sys.stderr)
        if spec.cache_path is not None:
            save_cache(raw_games, spec.cache_path, spec)
            print(f"Saved games to cache: {spec.cache_path}", file=sys.stderr)

    for gd in raw_games:
        src = _build_lichess_source_game(gd, spec.username)
        if src is not None:
            yield src
