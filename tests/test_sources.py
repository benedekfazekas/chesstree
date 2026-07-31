"""Tests for scripts/sources.py — skip-path coverage for _build_lichess_source_game."""
from __future__ import annotations

import os
import sys

import pytest

# Make scripts/ importable without installing it as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import sources


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
