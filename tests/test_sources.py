"""Tests for scripts/sources.py — skip-path coverage for _build_lichess_source_game."""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import chess
import chess.pgn
import pytest

# Make scripts/ importable without installing it as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import sources
from sources import SourceGame, SourceSpec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pgn_for(moves: list[str], end_comment: str = "") -> str:
    game = chess.pgn.Game()
    cursor: chess.pgn.GameNode = game
    for san in moves:
        cursor = cursor.add_variation(cursor.board().parse_san(san))
    if end_comment:
        cursor.comment = end_comment  # type: ignore[union-attr]
    exp = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exp)


def _chesscom_game(
    *,
    white: str = "Alice",
    black: str = "Bob",
    moves: list[str] | None = None,
    rules: str = "chess",
    initial_setup: str | None = None,
    uuid: str = "uuid-001",
    url: str = "https://www.chess.com/game/live/001",
    pgn: str | None = None,
) -> dict:
    if moves is None:
        moves = ["e4", "e5"]
    if pgn is None:
        pgn = _pgn_for(moves)
    gd: dict = {
        "white": {"username": white},
        "black": {"username": black},
        "rules": rules,
        "uuid": uuid,
        "url": url,
        "pgn": pgn,
        "end_time": 1700000000,
    }
    if initial_setup is not None:
        gd["initial_setup"] = initial_setup
    return gd


def _mock_urlopen(responses: dict[str, dict]) -> MagicMock:
    """Return a side_effect function that serves JSON responses keyed by URL."""
    def side_effect(req: urllib.request.Request) -> MagicMock:
        url = req.full_url
        if url not in responses:
            raise ValueError(f"Unexpected URL in test: {url!r}")
        payload = json.dumps(responses[url]).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read = lambda: payload
        return mock_resp
    return MagicMock(side_effect=side_effect)


def _archives_payload(months: list[str]) -> dict:
    """Build an archives-index response for the given ``'YYYY-MM'`` months."""
    return {
        "archives": [
            f"https://api.chess.com/pub/player/alice/games/{m[:4]}/{m[5:]}"
            for m in months
        ]
    }


def _archive_payload(games: list[dict]) -> dict:
    return {"games": games}


# ── _build_lichess_source_game skip paths ─────────────────────────────────────


class TestBuildLichessSourceGameSkipPaths:
    """Each guard in _build_lichess_source_game returns None.

    Non-standard variants are skipped silently; the malformed-input guards
    (missing pgn, unparseable pgn, no moves) also warn on stderr.
    """

    def test_non_standard_variant_skipped_silently(self, capsys: pytest.CaptureFixture) -> None:
        """Non-standard variant (e.g. chess960) is skipped without any warning."""
        game_dict = {
            "id": "skip_variant",
            "variant": "chess960",
            "moves": "e4 e5",
            "pgn": "1. e4 e5 *",
            "players": {
                "white": {"user": {"name": "alice"}},
                "black": {"user": {"name": "bob"}},
            },
        }
        result = sources._build_lichess_source_game(game_dict, "alice")
        assert result is None
        # No warning is expected for variant skip — it is a silent filter.
        out, err = capsys.readouterr()
        assert "skip_variant" not in err

    def test_missing_pgn_field_returns_none_with_warning(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """Game dict with no 'pgn' key → returns None and prints a warning."""
        game_dict = {
            "id": "no_pgn_game",
            "variant": "standard",
            "moves": "e4 e5",
            # No 'pgn' field
            "players": {
                "white": {"user": {"name": "alice"}},
                "black": {"user": {"name": "bob"}},
            },
        }
        result = sources._build_lichess_source_game(game_dict, "alice")
        assert result is None
        err = capsys.readouterr().err
        assert "no_pgn_game" in err
        assert "no pgn" in err.lower()

    def test_unparseable_pgn_returns_none_with_warning(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """A PGN string that chess.pgn.read_game cannot parse → returns None with warning.

        A whitespace-only string is truthy so it passes the 'no pgn field' guard, but
        chess.pgn.read_game returns None for it, triggering the parse-failure path.
        """
        game_dict = {
            "id": "bad_pgn_game",
            "variant": "standard",
            "moves": "e4 e5",
            "pgn": "   ",  # truthy but unparseable
            "players": {
                "white": {"user": {"name": "alice"}},
                "black": {"user": {"name": "bob"}},
            },
        }
        result = sources._build_lichess_source_game(game_dict, "alice")
        assert result is None
        err = capsys.readouterr().err
        assert "bad_pgn_game" in err
        assert "parse" in err.lower()

    def test_no_moves_pgn_returns_none_with_warning(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """A valid PGN with zero moves (empty game) → returns None with warning."""
        game_dict = {
            "id": "empty_moves_game",
            "variant": "standard",
            "moves": "",
            "pgn": "*",
            "players": {
                "white": {"user": {"name": "alice"}},
                "black": {"user": {"name": "bob"}},
            },
        }
        result = sources._build_lichess_source_game(game_dict, "alice")
        assert result is None
        err = capsys.readouterr().err
        assert "empty_moves_game" in err
        assert "no moves" in err.lower()


# ── _build_chesscom_source_game ───────────────────────────────────────────────


class TestBuildChesscomSourceGame:
    """Unit tests for _build_chesscom_source_game."""

    def test_happy_path_white_player(self) -> None:
        """Standard game where Alice is white → opponent is Bob."""
        gd = _chesscom_game(white="Alice", black="Bob", moves=["e4", "e5"])
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        assert src.source == "chesscom"
        assert src.opponent == "Bob"
        assert src.url == gd["url"]
        assert src.game_id == gd["uuid"]
        assert src.has_inline_eval is False
        # boards: initial + 2 moves
        assert len(src.boards) == 3

    def test_happy_path_black_player(self) -> None:
        """Standard game where Alice is black → opponent is Bob (white)."""
        gd = _chesscom_game(white="Bob", black="Alice", moves=["d4", "d5"])
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        assert src.opponent == "Bob"

    def test_opponent_case_insensitive(self) -> None:
        """Username match is case-insensitive."""
        gd = _chesscom_game(white="ALICE", black="Bob")
        src = sources._build_chesscom_source_game(gd, "alice")
        assert src is not None
        assert src.opponent == "Bob"

    def test_same_shape_as_lichess(self) -> None:
        """SourceGame from Chess.com has the same fields a Lichess one does."""
        gd = _chesscom_game(white="Alice", black="Bob", moves=["e4", "e5"])
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        # Downstream only cares about these fields
        for field in ("game", "boards", "opponent", "url", "source", "game_id", "has_inline_eval"):
            assert hasattr(src, field)

    def test_variant_rejection_rules_not_chess(self) -> None:
        """rules != 'chess' → skipped silently."""
        gd = _chesscom_game(rules="chess960")
        assert sources._build_chesscom_source_game(gd, "Alice") is None

    def test_variant_rejection_nonstandard_initial_setup(self) -> None:
        """Non-standard initial_setup → skipped."""
        gd = _chesscom_game(
            initial_setup="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB1R w KQkq - 0 1"
        )
        assert sources._build_chesscom_source_game(gd, "Alice") is None

    def test_standard_starting_fen_initial_setup_accepted(self) -> None:
        """initial_setup == STARTING_FEN is accepted (after normalize_fen)."""
        gd = _chesscom_game(initial_setup=chess.STARTING_FEN)
        assert sources._build_chesscom_source_game(gd, "Alice") is not None

    def test_missing_pgn_skipped_with_warning(self, capsys: pytest.CaptureFixture) -> None:
        gd = _chesscom_game()
        del gd["pgn"]
        assert sources._build_chesscom_source_game(gd, "Alice") is None
        assert "no pgn" in capsys.readouterr().err.lower()

    def test_unparseable_pgn_skipped_with_warning(self, capsys: pytest.CaptureFixture) -> None:
        gd = _chesscom_game(pgn="   ")
        assert sources._build_chesscom_source_game(gd, "Alice") is None
        assert "parse" in capsys.readouterr().err.lower()

    def test_has_inline_eval_false_normally(self) -> None:
        """Chess.com games never carry [%eval]; has_inline_eval must be False."""
        gd = _chesscom_game(moves=["e4", "e5"])
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        assert src.has_inline_eval is False

    def test_has_inline_eval_true_when_present(self) -> None:
        """If PGN somehow carries [%eval ...], has_inline_eval is True (honest compute)."""
        pgn = _pgn_for(["e4", "e5"], end_comment="[%eval 0.50]")
        gd = _chesscom_game(pgn=pgn)
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        assert src.has_inline_eval is True

    def test_uuid_used_as_game_id(self) -> None:
        gd = _chesscom_game(uuid="my-uuid-999")
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        assert src.game_id == "my-uuid-999"

    def test_url_fallback_for_game_id(self) -> None:
        """When uuid is absent, url is used as game_id."""
        gd = _chesscom_game(url="https://www.chess.com/game/live/007")
        del gd["uuid"]
        src = sources._build_chesscom_source_game(gd, "Alice")
        assert src is not None
        assert src.game_id == "https://www.chess.com/game/live/007"


# ── Date helpers (moved from merge_openings) ─────────────────────────────────


class TestMonthHelpers:
    def test_start_of_month(self) -> None:
        """2024-01 starts at midnight UTC on 2024-01-01."""
        import datetime
        ms = sources._month_to_ms_start("2024-01")
        dt = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
        assert ms == int(dt.timestamp() * 1000)

    def test_end_of_month_is_last_millisecond(self) -> None:
        """2024-01 ends at 23:59:59.999 UTC on 2024-01-31."""
        import datetime
        ms = sources._month_to_ms_end("2024-01")
        dt = datetime.datetime(2024, 1, 31, 23, 59, 59, tzinfo=datetime.timezone.utc)
        expected = int(dt.timestamp() * 1000) + 999
        assert ms == expected

    def test_until_includes_named_month(self) -> None:
        """_month_to_ms_end must be strictly greater than _month_to_ms_start of next month
        minus one ms — i.e. the last ms of the named month is included."""
        import datetime
        # March 2024 → end is 2024-03-31T23:59:59.999Z
        ms_end = sources._month_to_ms_end("2024-03")
        # April 2024 starts at 2024-04-01T00:00:00.000Z
        dt_april = datetime.datetime(2024, 4, 1, tzinfo=datetime.timezone.utc)
        ms_april_start = int(dt_april.timestamp() * 1000)
        assert ms_end == ms_april_start - 1

    def test_end_of_february_leap_year(self) -> None:
        """2024 is a leap year; February ends on the 29th."""
        import datetime
        ms = sources._month_to_ms_end("2024-02")
        dt = datetime.datetime(2024, 2, 29, 23, 59, 59, tzinfo=datetime.timezone.utc)
        assert ms == int(dt.timestamp() * 1000) + 999

    def test_end_of_february_non_leap(self) -> None:
        """2023 is not a leap year; February ends on the 28th."""
        import datetime
        ms = sources._month_to_ms_end("2023-02")
        dt = datetime.datetime(2023, 2, 28, 23, 59, 59, tzinfo=datetime.timezone.utc)
        assert ms == int(dt.timestamp() * 1000) + 999


# ── Chess.com archive month selection ─────────────────────────────────────────


class TestChesscomArchiveMonthSelection:
    """iter_games with chesscom spec selects the right archives."""

    def _run(
        self,
        months: list[str],
        games_by_month: dict[str, list[dict]],
        *,
        since: str | None = None,
        until: str | None = None,
        max_games: int | None = None,
    ) -> tuple[list[SourceGame], list[str]]:
        """
        Run _iter_chesscom_games with a stubbed urlopen.
        Returns (list_of_source_games, list_of_fetched_archive_urls).
        """
        spec = SourceSpec(
            source="chesscom",
            username="alice",
            max_games=max_games,
            cache_path=None,
        )
        archives_url = "https://api.chess.com/pub/player/alice/games/archives"
        responses: dict[str, dict] = {
            archives_url: _archives_payload(months),
        }
        for m, games in games_by_month.items():
            year, month = m[:4], m[5:]
            arc_url = f"https://api.chess.com/pub/player/alice/games/{year}/{month}"
            responses[arc_url] = _archive_payload(games)

        fetched_urls: list[str] = []

        def side_effect(req: urllib.request.Request) -> MagicMock:
            fetched_urls.append(req.full_url)
            url = req.full_url
            if url not in responses:
                raise ValueError(f"Unexpected URL: {url!r}")
            payload = json.dumps(responses[url]).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = lambda: payload
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = list(
                sources._iter_chesscom_games(spec, since=since, until=until)
            )
        return result, fetched_urls

    def test_no_filter_returns_all_archives(self) -> None:
        months = ["2024-01", "2024-02", "2024-03"]
        games_by_month = {m: [_chesscom_game(uuid=f"g-{m}")] for m in months}
        result, urls = self._run(months, games_by_month)
        assert len(result) == 3

    def test_since_only_excludes_older_months(self) -> None:
        months = ["2024-01", "2024-02", "2024-03"]
        games_by_month = {m: [_chesscom_game(uuid=f"g-{m}")] for m in months}
        result, urls = self._run(months, games_by_month, since="2024-02")
        assert len(result) == 2
        returned_ids = {g.game_id for g in result}
        assert "g-2024-01" not in returned_ids
        assert "g-2024-02" in returned_ids
        assert "g-2024-03" in returned_ids

    def test_until_only_excludes_newer_months(self) -> None:
        months = ["2024-01", "2024-02", "2024-03"]
        games_by_month = {m: [_chesscom_game(uuid=f"g-{m}")] for m in months}
        result, urls = self._run(months, games_by_month, until="2024-02")
        assert len(result) == 2
        returned_ids = {g.game_id for g in result}
        assert "g-2024-03" not in returned_ids
        assert "g-2024-01" in returned_ids
        assert "g-2024-02" in returned_ids

    def test_since_and_until(self) -> None:
        months = ["2024-01", "2024-02", "2024-03", "2024-04"]
        games_by_month = {m: [_chesscom_game(uuid=f"g-{m}")] for m in months}
        result, urls = self._run(months, games_by_month, since="2024-02", until="2024-03")
        assert len(result) == 2

    def test_archives_walked_newest_first(self) -> None:
        """Archives are fetched in newest-first order."""
        months = ["2024-01", "2024-02", "2024-03"]
        games_by_month = {m: [_chesscom_game(uuid=f"g-{m}")] for m in months}
        result, urls = self._run(months, games_by_month)
        # Filter out the archives index URL; remaining are per-archive fetches.
        archive_urls = [u for u in urls if "/games/archives" not in u]
        # Archives go from newest to oldest: 2024/03 first
        assert "2024/03" in archive_urls[0]
        assert "2024/02" in archive_urls[1]
        assert "2024/01" in archive_urls[2]


# ── Within-archive reversed ordering (finding F2) ────────────────────────────


class TestChesscomWithinArchiveReversed:
    """Games within an archive are iterated reversed (newest first).

    Chess.com returns games ascending by end_time (oldest first).
    Without reversed(), a --max-games run would return the OLDEST games
    of the newest month — wrong. This test pins that reversal.

    To fail: remove the `reversed()` call in _iter_chesscom_games.
    """

    def test_newest_games_yielded_under_max_games(self) -> None:
        """With 5 games in archive and max_games=2, the 2 NEWEST are returned."""
        # Build 5 games with ascending end_time and distinct UUIDs.
        games_asc = [
            {**_chesscom_game(uuid=f"old{i}"), "end_time": 1700000000 + i}
            for i in range(5)
        ]
        spec = SourceSpec(source="chesscom", username="Alice", max_games=2, cache_path=None)
        archives_url = "https://api.chess.com/pub/player/Alice/games/archives"
        arc_url = "https://api.chess.com/pub/player/Alice/games/2024/01"
        responses = {
            archives_url: {"archives": [arc_url]},
            arc_url: {"games": games_asc},
        }

        def side_effect(req: urllib.request.Request) -> MagicMock:
            payload = json.dumps(responses[req.full_url]).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = lambda: payload
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = list(sources._iter_chesscom_games(spec))

        assert len(result) == 2
        ids = [g.game_id for g in result]
        # Newest game is index 4 (old4), second-newest is index 3 (old3).
        assert "old4" in ids
        assert "old3" in ids
        # Oldest games must NOT be returned.
        assert "old0" not in ids
        assert "old1" not in ids

    def test_cache_reload_yields_newest_games_under_max_games(
        self, tmp_path: Path
    ) -> None:
        """Cache round-trip preserves newest-first ordering (F-001 fix).

        Live fetch with 5 ascending-end_time games + max_games=2 yields old4/old3.
        Saving to cache and reloading must yield the same two games — old4/old3,
        not old0/old1.

        To fail: change `all_raw.extend(reversed(games_in_archive))` back to
        `all_raw.extend(games_in_archive)` — the cached list will be ascending and
        the cache reload will return old0/old1 instead.
        """
        games_asc = [
            {**_chesscom_game(uuid=f"old{i}"), "end_time": 1700000000 + i}
            for i in range(5)
        ]
        cache_file = tmp_path / "cc_cache.json"
        spec = SourceSpec(
            source="chesscom", username="Alice", max_games=2, cache_path=cache_file
        )
        archives_url = "https://api.chess.com/pub/player/Alice/games/archives"
        arc_url = "https://api.chess.com/pub/player/Alice/games/2024/01"
        responses = {
            archives_url: {"archives": [arc_url]},
            arc_url: {"games": games_asc},
        }

        def side_effect(req: urllib.request.Request) -> MagicMock:
            payload = json.dumps(responses[req.full_url]).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = lambda: payload
            return mock_resp

        # First run: live fetch, fills cache.
        with patch("urllib.request.urlopen", side_effect=side_effect):
            live_result = list(sources._iter_chesscom_games(spec))

        assert [g.game_id for g in live_result] == ["old4", "old3"]

        # Second run: cache hit — no network calls.
        cache_result = list(sources._iter_chesscom_games(spec))
        assert [g.game_id for g in cache_result] == ["old4", "old3"], (
            "Cache reload must yield the same newest-first games as the live fetch"
        )


# ── max_games early stop and no later archive fetched ────────────────────────


class TestChesscomMaxGamesEarlyStop:
    """After max_games are yielded, no further archive URLs are requested."""

    def test_later_archive_never_requested(self) -> None:
        """Once budget is exhausted on archive 2024/03, 2024/02 must not be fetched."""
        # Two archives in ascending order (index will be reversed).
        # Archive 2024/03 has 3 games; max_games=2 exhausts the budget.
        months = ["2024/02", "2024/03"]
        games_02 = [_chesscom_game(uuid=f"old-{i}") for i in range(3)]
        games_03 = [_chesscom_game(uuid=f"new-{i}") for i in range(3)]
        spec = SourceSpec(source="chesscom", username="Alice", max_games=2, cache_path=None)
        archives_url = "https://api.chess.com/pub/player/Alice/games/archives"
        arc_02 = "https://api.chess.com/pub/player/Alice/games/2024/02"
        arc_03 = "https://api.chess.com/pub/player/Alice/games/2024/03"
        responses: dict[str, dict] = {
            archives_url: {"archives": [arc_02, arc_03]},
            arc_03: {"games": games_03},
            # arc_02 should never be requested — not included to detect the call.
        }
        fetched: list[str] = []

        def side_effect(req: urllib.request.Request) -> MagicMock:
            fetched.append(req.full_url)
            if req.full_url not in responses:
                raise ValueError(f"Should not have fetched: {req.full_url!r}")
            payload = json.dumps(responses[req.full_url]).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = lambda: payload
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = list(sources._iter_chesscom_games(spec))

        assert len(result) == 2
        assert arc_02 not in fetched, "2024/02 archive must not be fetched once budget is spent"


# ── 429 retry/backoff ─────────────────────────────────────────────────────────


class TestChesscom429Retry:
    """_chesscom_request retries on 429, then raises on exhaustion."""

    def _make_429(self) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="https://api.chess.com/pub/player/alice/games/archives",
            code=429,
            msg="Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,  # type: ignore[arg-type]
        )

    def test_retries_then_succeeds(self) -> None:
        """429 on first attempt, success on second → result returned, no exception."""
        call_count = [0]
        ok_payload = json.dumps({"archives": []}).encode("utf-8")

        def side_effect(req: urllib.request.Request) -> MagicMock:
            call_count[0] += 1
            if call_count[0] < 2:
                raise self._make_429()
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = lambda: ok_payload
            return mock_resp

        slept: list[float] = []
        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = sources._chesscom_request(
                "https://api.chess.com/pub/player/alice/games/archives",
                sleep_fn=lambda s: slept.append(s),
            )

        assert result == {"archives": []}
        assert call_count[0] == 2
        assert len(slept) == 1  # slept once

    def test_bounded_retries_exhaustion_raises(self) -> None:
        """After _CHESSCOM_MAX_RETRIES exhausted, RuntimeError is raised."""
        def side_effect(req: urllib.request.Request) -> MagicMock:
            raise self._make_429()

        slept: list[float] = []
        with pytest.raises(RuntimeError, match="429"):
            with patch("urllib.request.urlopen", side_effect=side_effect):
                sources._chesscom_request(
                    "https://api.chess.com/pub/player/alice/games/archives",
                    sleep_fn=lambda s: slept.append(s),
                )
        # Must not sleep on the final attempt — immediate raise (F-005a).
        assert len(slept) == sources._CHESSCOM_MAX_RETRIES

    def test_404_on_archives_index_raises_user_not_found(self) -> None:
        """404 on the archives index → ValueError naming 'no such user'."""
        exc_404 = urllib.error.HTTPError(
            url="https://api.chess.com/pub/player/nobody/games/archives",
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="no such user"):
            with patch("urllib.request.urlopen", side_effect=exc_404):
                sources._chesscom_request(
                    "https://api.chess.com/pub/player/nobody/games/archives",
                    sleep_fn=lambda s: None,
                    _is_archives_index=True,
                )

    def test_404_on_monthly_archive_raises_archive_not_found(self) -> None:
        """404 on a monthly archive → ValueError naming the archive URL."""
        arc_url = "https://api.chess.com/pub/player/alice/games/2024/01"
        exc_404 = urllib.error.HTTPError(
            url=arc_url,
            code=404,
            msg="Not Found",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="archive not found"):
            with patch("urllib.request.urlopen", side_effect=exc_404):
                sources._chesscom_request(
                    arc_url,
                    sleep_fn=lambda s: None,
                    _is_archives_index=False,
                )


# ── Chess.com cache round-trip ────────────────────────────────────────────────


class TestChesscomCache:
    def test_chesscom_cache_roundtrip(self, tmp_path: Path) -> None:
        games = [_chesscom_game(uuid="cached-001")]
        spec = SourceSpec(source="chesscom", username="alice", max_games=None, cache_path=None)
        cache_file = tmp_path / "cc.json"
        sources.save_cache(games, cache_file, spec)
        loaded = sources.load_cache(cache_file, spec)
        assert loaded == games

    def test_chesscom_cache_source_tag(self, tmp_path: Path) -> None:
        spec = SourceSpec(source="chesscom", username="alice", max_games=None, cache_path=None)
        cache_file = tmp_path / "cc.json"
        sources.save_cache([], cache_file, spec)
        with open(cache_file) as f:
            data = json.load(f)
        assert data["source"] == "chesscom"
        assert data["username"] == "alice"

    def test_source_mismatch_raises(self, tmp_path: Path) -> None:
        spec_cc = SourceSpec(source="chesscom", username="alice", max_games=None, cache_path=None)
        cache_file = tmp_path / "cc.json"
        sources.save_cache([], cache_file, spec_cc)
        spec_li = SourceSpec(source="lichess", username="alice", max_games=None, cache_path=None)
        with pytest.raises(ValueError, match="source"):
            sources.load_cache(cache_file, spec_li)

    def test_username_mismatch_raises(self, tmp_path: Path) -> None:
        spec_a = SourceSpec(source="chesscom", username="alice", max_games=None, cache_path=None)
        cache_file = tmp_path / "cc.json"
        sources.save_cache([], cache_file, spec_a)
        spec_b = SourceSpec(source="chesscom", username="bob", max_games=None, cache_path=None)
        with pytest.raises(ValueError, match="username"):
            sources.load_cache(cache_file, spec_b)


# ── iter_games routing ────────────────────────────────────────────────────────


class TestIterGamesRouting:
    """iter_games with since/until strings routes correctly."""

    def test_unknown_source_raises(self) -> None:
        spec = SourceSpec(source="unknown", username="x", max_games=None, cache_path=None)
        with pytest.raises(ValueError, match="unknown"):
            list(sources.iter_games(spec))

    def test_lichess_since_until_converted_to_ms(self) -> None:
        """iter_games with since/until passes epoch-ms to fetch_lichess_games."""
        spec = SourceSpec(source="lichess", username="u", max_games=None, cache_path=None)
        captured: dict = {}

        def fake_fetch(username, **kwargs):
            captured.update(kwargs)
            return []

        with patch.object(sources, "fetch_lichess_games", side_effect=fake_fetch):
            list(sources.iter_games(spec, since="2024-01", until="2024-03"))

        assert captured.get("since_ms") == sources._month_to_ms_start("2024-01")
        assert captured.get("until_ms") == sources._month_to_ms_end("2024-03")

    def test_until_epoch_ms_includes_named_month(self) -> None:
        """--until YYYY-MM → epoch ms is the LAST ms of that month (month is included)."""
        import datetime
        ms = sources._month_to_ms_end("2024-03")
        # Must be ≥ the start of the last day of March 2024
        last_day_start = datetime.datetime(2024, 3, 31, tzinfo=datetime.timezone.utc)
        assert ms > int(last_day_start.timestamp() * 1000)
        # Must be < the start of April 2024
        april_start = datetime.datetime(2024, 4, 1, tzinfo=datetime.timezone.utc)
        assert ms < int(april_start.timestamp() * 1000)


# ── Colour filter client-side ─────────────────────────────────────────────────


class TestChesscomColorFilter:
    def _fetch_with_color(self, color: str | None) -> list[SourceGame]:
        games = [
            _chesscom_game(white="Alice", black="Bob", uuid="as-white"),
            _chesscom_game(white="Bob", black="Alice", uuid="as-black"),
        ]
        spec = SourceSpec(source="chesscom", username="Alice", max_games=None, cache_path=None)
        archives_url = "https://api.chess.com/pub/player/Alice/games/archives"
        arc_url = "https://api.chess.com/pub/player/Alice/games/2024/01"
        responses = {
            archives_url: {"archives": [arc_url]},
            arc_url: {"games": games},
        }

        def side_effect(req: urllib.request.Request) -> MagicMock:
            payload = json.dumps(responses[req.full_url]).encode("utf-8")
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = lambda: payload
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            return list(sources._iter_chesscom_games(spec, color=color))

    def test_no_color_filter_returns_both(self) -> None:
        result = self._fetch_with_color(None)
        assert len(result) == 2

    def test_white_filter_returns_only_white_games(self) -> None:
        result = self._fetch_with_color("white")
        assert len(result) == 1
        assert result[0].game_id == "as-white"

    def test_black_filter_returns_only_black_games(self) -> None:
        result = self._fetch_with_color("black")
        assert len(result) == 1
        assert result[0].game_id == "as-black"
