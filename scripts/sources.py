#!/usr/bin/env python3
"""Source-agnostic acquisition layer for merge_openings.py.

Defines the source contract (SourceGame, SourceSpec) and the per-source
generator interface (iter_games).  Lichess and Chess.com adapters are
implemented; a local-directory source can be added the same way.
"""
from __future__ import annotations

import calendar
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

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
    opening: dict | None          # {"eco": "B12", "name": "…"} from Lichess; None otherwise


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
    since: str | None = None,
    until: str | None = None,
) -> Iterator[SourceGame]:
    """Yield :class:`SourceGame` objects for every valid game in *spec*.

    *since* and *until* are ``'YYYY-MM'`` strings (inclusive of the whole named
    month on both sources).  Each adapter converts them to whatever it needs:
    epoch milliseconds for Lichess, month selection for Chess.com.
    """
    if spec.source == "lichess":
        since_ms = _month_to_ms_start(since) if since else None
        until_ms = _month_to_ms_end(until) if until else None
        yield from _iter_lichess_games(
            spec, color=color, since_ms=since_ms, until_ms=until_ms
        )
    elif spec.source == "chesscom":
        yield from _iter_chesscom_games(spec, color=color, since=since, until=until)
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
    opening = game_dict.get("opening") or None

    return SourceGame(
        game=game,
        boards=boards,
        opponent=opponent,
        url=url,
        source="lichess",
        game_id=game_id,
        has_inline_eval=has_inline_eval,
        opening=opening,
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


# ── Date helpers (used by the Lichess adapter via iter_games) ─────────────────


def _month_to_ms_start(ym: str) -> int:
    """``'YYYY-MM'`` → first millisecond of that month, UTC (epoch ms)."""
    year, month = int(ym[:4]), int(ym[5:7])
    dt = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000)


def _month_to_ms_end(ym: str) -> int:
    """``'YYYY-MM'`` → last millisecond of that month, UTC (epoch ms).

    Inclusive: the whole named month is included in the query range.
    """
    year, month = int(ym[:4]), int(ym[5:7])
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime.datetime(year, month, last_day, 23, 59, 59, tzinfo=datetime.timezone.utc)
    return int(dt.timestamp() * 1000) + 999


# ── Chess.com adapter ─────────────────────────────────────────────────────────

_CHESSCOM_USER_AGENT = (
    "chesstree/merge_openings (https://github.com/benedekfazekas/chesstree)"
)
_CHESSCOM_MAX_RETRIES = 5
_CHESSCOM_RETRY_BASE_SLEEP = 2.0  # seconds; injectable for tests


def _chesscom_request(
    url: str,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    _is_archives_index: bool = False,
) -> dict:
    """Fetch *url* from the Chess.com API; return the parsed JSON dict.

    On ``HTTPError 404`` for the archives index: raise ``ValueError`` reporting
    "no such Chess.com user or no public games".  For a monthly archive, raise
    ``ValueError`` reporting the archive URL.
    On ``HTTPError 429``: sleep with exponential back-off and retry up to
    ``_CHESSCOM_MAX_RETRIES`` times, then raise ``RuntimeError``.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _CHESSCOM_USER_AGENT},
    )
    last_exc: Optional[Exception] = None
    for attempt in range(_CHESSCOM_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                if _is_archives_index:
                    raise ValueError(
                        f"Chess.com: no such user or no public games: {url}"
                    ) from exc
                raise ValueError(
                    f"Chess.com: monthly archive not found: {url}"
                ) from exc
            if exc.code == 429:
                last_exc = exc
                # Do not sleep before the very last attempt — raise immediately.
                if attempt == _CHESSCOM_MAX_RETRIES:
                    break
                wait = _CHESSCOM_RETRY_BASE_SLEEP * (2 ** attempt)
                print(
                    f"Chess.com 429 rate limit on {url}; "
                    f"sleeping {wait:.1f}s (attempt {attempt + 1}/{_CHESSCOM_MAX_RETRIES})",
                    file=sys.stderr,
                )
                sleep_fn(wait)
                continue
            raise
    raise RuntimeError(
        f"Chess.com API returned 429 after {_CHESSCOM_MAX_RETRIES} retries: {url}"
    ) from last_exc


def _iter_chesscom_games(
    spec: SourceSpec,
    *,
    color: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    _sleep_fn: Callable[[float], None] = time.sleep,
) -> Iterator[SourceGame]:
    """Yield :class:`SourceGame` objects from Chess.com, using the cache when present."""
    if spec.cache_path is not None and os.path.exists(spec.cache_path):
        print(f"Loading games from cache: {spec.cache_path}", file=sys.stderr)
        raw_games = load_cache(spec.cache_path, spec)
        print(f"Loaded {len(raw_games)} games from cache", file=sys.stderr)
        yield from _iter_chesscom_raw_games(
            raw_games, spec, color=color
        )
        return

    # Fetch archives index.
    archives_url = (
        f"https://api.chess.com/pub/player/{spec.username}/games/archives"
    )
    archives_data = _chesscom_request(archives_url, sleep_fn=_sleep_fn, _is_archives_index=True)
    all_archive_urls: list[str] = archives_data.get("archives", [])

    # Month selection: parse YYYY/MM from each URL and filter by since/until.
    def _archive_month(url: str) -> str:
        # URL ends with .../games/YYYY/MM
        parts = url.rstrip("/").rsplit("/", 2)
        return f"{parts[-2]}-{parts[-1]}"  # → "YYYY-MM"

    selected_urls = [
        u for u in all_archive_urls
        if (since is None or _archive_month(u) >= since)
        and (until is None or _archive_month(u) <= until)
    ]

    # Walk newest first.
    selected_urls = list(reversed(selected_urls))

    yielded = 0
    all_raw: list[dict] = []
    for archive_url in selected_urls:
        if spec.max_games is not None and yielded >= spec.max_games:
            break
        print(
            f"Fetching Chess.com archive: {archive_url}",
            file=sys.stderr,
        )
        archive_data = _chesscom_request(archive_url, sleep_fn=_sleep_fn)
        games_in_archive: list[dict] = archive_data.get("games", [])
        # Store in newest-first order so the cached list matches the live yield order.
        all_raw.extend(reversed(games_in_archive))

        for gd in reversed(games_in_archive):
            if spec.max_games is not None and yielded >= spec.max_games:
                break
            src = _build_chesscom_source_game(gd, spec.username)
            if src is None:
                continue
            if color is not None:
                white_username = (gd.get("white") or {}).get("username", "")
                black_username = (gd.get("black") or {}).get("username", "")
                if color == "white" and white_username.lower() != spec.username.lower():
                    continue
                if color == "black" and black_username.lower() != spec.username.lower():
                    continue
            yield src
            yielded += 1

    if spec.cache_path is not None:
        save_cache(all_raw, spec.cache_path, spec)
        print(f"Saved games to cache: {spec.cache_path}", file=sys.stderr)


def _iter_chesscom_raw_games(
    raw_games: list[dict],
    spec: SourceSpec,
    *,
    color: Optional[str] = None,
) -> Iterator[SourceGame]:
    """Yield SourceGame from a raw list of Chess.com game dicts (cache path).

    The cached list is already in newest-first yield order (accumulated that way
    during the live fetch), so no further ordering is applied here.  Month
    bounds were applied at fetch time and are not re-applied on reload.
    """
    yielded = 0
    for gd in raw_games:
        if spec.max_games is not None and yielded >= spec.max_games:
            break
        src = _build_chesscom_source_game(gd, spec.username)
        if src is None:
            continue
        if color is not None:
            white_username = (gd.get("white") or {}).get("username", "")
            black_username = (gd.get("black") or {}).get("username", "")
            if color == "white" and white_username.lower() != spec.username.lower():
                continue
            if color == "black" and black_username.lower() != spec.username.lower():
                continue
        yield src
        yielded += 1


def _build_chesscom_source_game(
    game_dict: dict,
    username: str,
) -> Optional[SourceGame]:
    """Parse one Chess.com game dict into a :class:`SourceGame`, or ``None`` to skip."""
    # Variant check.
    if game_dict.get("rules") != "chess":
        return None

    # Non-standard starting position check.
    initial_setup = game_dict.get("initial_setup")
    if initial_setup is not None:
        if normalize_fen(initial_setup) != normalize_fen(chess.STARTING_FEN):
            return None

    # PGN presence and parsability.
    pgn_str = game_dict.get("pgn")
    game_url = game_dict.get("url", "")
    game_id = game_dict.get("uuid") or game_url or "?"

    if not pgn_str:
        print(
            f"Warning: Chess.com game {game_id} has no pgn field, skipping",
            file=sys.stderr,
        )
        return None

    game = chess.pgn.read_game(io.StringIO(pgn_str))
    if game is None:
        print(
            f"Warning: could not parse pgn for Chess.com game {game_id}, skipping",
            file=sys.stderr,
        )
        return None

    boards = _boards_from_game(game)
    if len(boards) <= 1:
        print(
            f"Warning: Chess.com game {game_id} has no moves, skipping",
            file=sys.stderr,
        )
        return None

    # Opponent resolution — case-insensitive.
    white_obj = game_dict.get("white") or {}
    black_obj = game_dict.get("black") or {}
    white_username = white_obj.get("username", "?")
    black_username = black_obj.get("username", "?")

    if white_username.lower() == username.lower():
        opponent = black_username
    else:
        opponent = white_username

    has_inline_eval = bool(_EVAL_RE.search(pgn_str))

    return SourceGame(
        game=game,
        boards=boards,
        opponent=opponent,
        url=game_url,
        source="chesscom",
        game_id=game_id,
        has_inline_eval=has_inline_eval,
        opening=None,
    )
