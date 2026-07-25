"""Tests for scripts/merge_openings.py (Lichess-only POC)."""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
from typing import Optional
from unittest.mock import MagicMock, patch

import chess
import chess.pgn
import pytest

# Make scripts/ importable without installing it as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import merge_openings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_game(moves: list[str]) -> chess.pgn.Game:
    """Build a chess.pgn.Game from a list of SAN strings."""
    game = chess.pgn.Game()
    cursor: chess.pgn.GameNode = game
    for san in moves:
        cursor = cursor.add_variation(cursor.board().parse_san(san))
    return game


def _pgn_str(moves: list[str]) -> str:
    """Return a PGN string for a sequence of SAN moves."""
    game = _build_game(moves)
    exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
    return game.accept(exporter)


def _game_dict(
    moves: list[str],
    game_id: str = "abc123",
    division_middle: Optional[int] = None,
    players: Optional[dict] = None,
) -> dict:
    """Construct a minimal Lichess NDJSON game dict for testing."""
    mid = division_middle if division_middle is not None else len(moves)
    gd: dict = {
        "id": game_id,
        "variant": "standard",
        "moves": " ".join(moves),
        "pgn": _pgn_str(moves),
        "division": {"middle": mid},
    }
    if players is not None:
        gd["players"] = players
    return gd


def _make_slice(moves: list[str], label: str) -> tuple[chess.pgn.Game, str]:
    """Build a (sliced_game, label) pair with [%opening_end] on the leaf."""
    game = _build_game(moves)
    leaf = game.end()
    leaf.comment = "[%opening_end]"
    return game, label


# ── normalize_fen ─────────────────────────────────────────────────────────────

class TestNormalizeFen:
    def test_strips_halfmove_and_fullmove_counters(self) -> None:
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        assert merge_openings.normalize_fen(fen) == (
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        )

    def test_already_four_parts(self) -> None:
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"
        assert merge_openings.normalize_fen(fen) == fen

    def test_two_different_counter_values_normalize_equal(self) -> None:
        fen_a = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        fen_b = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 5 42"
        assert merge_openings.normalize_fen(fen_a) == merge_openings.normalize_fen(fen_b)


# ── find_filter_ply ───────────────────────────────────────────────────────────

class TestFindFilterPly:
    @staticmethod
    def _fen_after(moves: list[str]) -> str:
        board = chess.Board()
        for san in moves:
            board.push_san(san)
        return merge_openings.normalize_fen(board.fen())

    def test_matches_initial_position(self) -> None:
        target = merge_openings.normalize_fen(chess.Board().fen())
        gd = _game_dict(["e4", "e5", "Nf3"])
        assert merge_openings.find_filter_ply(gd, target) == 0

    def test_matches_after_first_move(self) -> None:
        target = self._fen_after(["e4"])
        gd = _game_dict(["e4", "e5", "Nf3"])
        assert merge_openings.find_filter_ply(gd, target) == 1

    def test_matches_mid_game(self) -> None:
        target = self._fen_after(["e4", "e5", "Nf3"])
        gd = _game_dict(["e4", "e5", "Nf3", "Nc6"])
        assert merge_openings.find_filter_ply(gd, target) == 3

    def test_returns_none_when_position_not_reached(self) -> None:
        target = self._fen_after(["d4", "d5", "c4"])
        gd = _game_dict(["e4", "e5", "Nf3"])
        assert merge_openings.find_filter_ply(gd, target) is None

    def test_returns_none_for_empty_moves(self) -> None:
        target = self._fen_after(["e4"])
        gd = {"id": "x", "moves": ""}
        assert merge_openings.find_filter_ply(gd, target) is None

    def test_returns_none_when_moves_field_missing(self) -> None:
        target = self._fen_after(["e4"])
        gd = {"id": "x"}
        assert merge_openings.find_filter_ply(gd, target) is None


# ── extract_eval ──────────────────────────────────────────────────────────────

class TestExtractEval:
    def test_positive_eval(self) -> None:
        assert merge_openings.extract_eval("[%eval 0.43]") == "0.43"

    def test_negative_eval(self) -> None:
        assert merge_openings.extract_eval("{ [%eval -1.23] }") == "-1.23"

    def test_mate_eval(self) -> None:
        assert merge_openings.extract_eval("[%eval #5]") == "#5"

    def test_returns_none_when_absent(self) -> None:
        assert merge_openings.extract_eval("nice move") is None

    def test_returns_none_for_empty_comment(self) -> None:
        assert merge_openings.extract_eval("") is None


# ── get_opponent_name ─────────────────────────────────────────────────────────

class TestGetOpponentName:
    def _players(self, white: str, black: str) -> dict:
        return {
            "white": {"user": {"name": white}},
            "black": {"user": {"name": black}},
        }

    def test_username_is_white_returns_black(self) -> None:
        gd = {"players": self._players("Alice", "Bob")}
        assert merge_openings.get_opponent_name(gd, "Alice") == "Bob"

    def test_username_is_black_returns_white(self) -> None:
        gd = {"players": self._players("Alice", "Bob")}
        assert merge_openings.get_opponent_name(gd, "Bob") == "Alice"

    def test_case_insensitive_match(self) -> None:
        gd = {"players": self._players("Alice", "Bob")}
        assert merge_openings.get_opponent_name(gd, "alice") == "Bob"

    def test_missing_user_falls_back_to_question_mark(self) -> None:
        gd = {"players": {"white": {}, "black": {}}}
        result = merge_openings.get_opponent_name(gd, "alice")
        assert result == "?"

    def test_missing_players_field_falls_back_to_question_mark(self) -> None:
        result = merge_openings.get_opponent_name({}, "alice")
        assert result == "?"


# ── create_slice ──────────────────────────────────────────────────────────────

class TestCreateSlice:
    def test_correct_node_count(self) -> None:
        gd = _game_dict(["e4", "e5", "Nf3", "Nc6", "Bb5"])
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=5, username="testuser")
        assert result is not None
        sliced, _ = result
        nodes = []
        node: Optional[chess.pgn.GameNode] = sliced.next()
        while node is not None:
            nodes.append(node)
            node = node.next()
        assert len(nodes) == 5

    def test_preamble_included_when_filter_ply_positive(self) -> None:
        """With filter_ply=2, ALL 5 moves (preamble + post-filter) appear in the slice."""
        gd = _game_dict(["e4", "e5", "Nf3", "Nc6", "Bb5"])
        result = merge_openings.create_slice(gd, filter_ply=2, opening_end_ply=5, username="testuser")
        assert result is not None
        sliced, _ = result
        all_nodes = []
        node: Optional[chess.pgn.GameNode] = sliced.next()
        while node is not None:
            all_nodes.append(node)
            node = node.next()
        assert len(all_nodes) == 5

    def test_opening_end_annotation_on_last_node(self) -> None:
        gd = _game_dict(["e4", "e5", "Nf3"])
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=3, username="testuser")
        assert result is not None
        sliced, _ = result
        assert "[%opening_end]" in sliced.end().comment

    def test_opening_end_annotation_preserved_with_existing_comment(self) -> None:
        # Build a game where the last node has a pre-existing comment.
        game = _build_game(["e4", "e5"])
        game.end().comment = "[%eval 0.12]"
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        pgn = game.accept(exporter)
        gd = {
            "id": "test",
            "variant": "standard",
            "moves": "e4 e5",
            "pgn": pgn,
            "division": {"middle": 2},
        }
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=2, username="testuser")
        assert result is not None
        sliced, _ = result
        leaf_comment = sliced.end().comment
        assert "[%eval 0.12]" in leaf_comment
        assert "[%opening_end]" in leaf_comment

    def test_label_format_without_eval(self) -> None:
        """Label without eval: 'vs [Opponent](url)' — no colon/bold suffix."""
        players = {"white": {"user": {"name": "testuser"}}, "black": {"user": {"name": "Opponent"}}}
        gd = _game_dict(["e4", "e5"], game_id="xyz999", players=players)
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=2, username="testuser")
        assert result is not None
        _, label = result
        assert label == "vs [Opponent](https://lichess.org/xyz999)"

    def test_label_format_with_eval(self) -> None:
        """Label with eval: 'vs [Opponent](url): **0.43**'."""
        game = _build_game(["e4", "e5"])
        game.end().comment = "[%eval 0.43]"
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        pgn = game.accept(exporter)
        players = {"white": {"user": {"name": "testuser"}}, "black": {"user": {"name": "Kasparov"}}}
        gd = {
            "id": "evalgame",
            "variant": "standard",
            "moves": "e4 e5",
            "pgn": pgn,
            "division": {"middle": 2},
            "players": players,
        }
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=2, username="testuser")
        assert result is not None
        _, label = result
        assert label == "vs [Kasparov](https://lichess.org/evalgame): **0.43**"

    def test_label_url_contains_game_id(self) -> None:
        gd = _game_dict(["e4", "e5"], game_id="xyz999")
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=2, username="testuser")
        assert result is not None
        _, label = result
        assert "https://lichess.org/xyz999" in label

    def test_skips_game_with_missing_pgn(self) -> None:
        gd = {"id": "nopgn", "variant": "standard", "moves": "e4 e5"}
        assert merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=2, username="testuser") is None

    def test_skips_game_too_short(self) -> None:
        gd = _game_dict(["e4", "e5"], game_id="short")
        # opening_end_ply beyond game length
        assert merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=5, username="testuser") is None

    def test_zero_opening_end_ply_returns_none(self) -> None:
        gd = _game_dict(["e4", "e5"])
        assert merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=0, username="testuser") is None

    def test_full_game_used_when_no_division_middle(self) -> None:
        """Game with no division.middle: opening_end_ply falls back to full game length."""
        moves = ["e4", "e5", "Nf3"]
        gd = {
            "id": "nodiv",
            "variant": "standard",
            "moves": " ".join(moves),
            "pgn": _pgn_str(moves),
            # division field absent entirely
        }
        # Caller computes opening_end_ply = len(moves) and passes it to create_slice.
        opening_end_ply = len(moves)
        result = merge_openings.create_slice(gd, filter_ply=0, opening_end_ply=opening_end_ply, username="testuser")
        assert result is not None
        sliced, label = result
        # Slice should contain all moves.
        node: Optional[chess.pgn.GameNode] = sliced.next()
        count = 0
        while node is not None:
            count += 1
            node = node.next()
        assert count == len(moves)
        # Last node must carry [%opening_end].
        assert "[%opening_end]" in sliced.end().comment
        assert "https://lichess.org/nodiv" in label


# ── merge_game_slices ─────────────────────────────────────────────────────────

class TestMergeGameSlices:
    def test_identical_games_produce_single_leaf_with_both_labels(self) -> None:
        moves = ["e4", "e5", "Nf3"]
        s1 = _make_slice(moves, "https://lichess.org/game1")
        s2 = _make_slice(moves, "https://lichess.org/game2")
        merged = merge_openings.merge_game_slices([s1, s2])
        leaf = merged.end()
        assert "https://lichess.org/game1" in leaf.comment
        assert "https://lichess.org/game2" in leaf.comment

    def test_identical_games_single_leaf(self) -> None:
        """Identical games → only one leaf node in the tree."""
        moves = ["e4", "e5", "Nf3"]
        s1 = _make_slice(moves, "https://lichess.org/game1")
        s2 = _make_slice(moves, "https://lichess.org/game2")
        merged = merge_openings.merge_game_slices([s1, s2])
        # Walk the tree; there should be exactly one leaf.
        leaves = []
        stack = list(merged.variations)
        while stack:
            node = stack.pop()
            if not node.variations:
                leaves.append(node)
            else:
                stack.extend(node.variations)
        assert len(leaves) == 1

    def test_diverging_games_branch_at_correct_point(self) -> None:
        """Games that share only 1. e4 should branch at the second move."""
        s1 = _make_slice(["e4", "e5", "Nf3"], "https://lichess.org/game1")
        s2 = _make_slice(["e4", "c5", "Nf3"], "https://lichess.org/game2")
        merged = merge_openings.merge_game_slices([s1, s2])
        e4_node = merged.next()
        assert e4_node is not None
        assert len(e4_node.variations) == 2

    def test_diverging_games_labels_on_correct_leaves(self) -> None:
        s1 = _make_slice(["e4", "e5"], "https://lichess.org/game1")
        s2 = _make_slice(["e4", "c5"], "https://lichess.org/game2")
        merged = merge_openings.merge_game_slices([s1, s2])
        e4_node = merged.next()
        assert e4_node is not None
        leaves = {var.end().comment for var in e4_node.variations}
        assert any("game1" in c for c in leaves)
        assert any("game2" in c for c in leaves)

    def test_three_games_correct_tree_shape(self) -> None:
        """Two share the first move only; one is a full duplicate of another."""
        s1 = _make_slice(["e4", "e5", "Nf3"], "https://lichess.org/game1")
        s2 = _make_slice(["e4", "e5", "Bc4"], "https://lichess.org/game2")
        s3 = _make_slice(["e4", "c5", "Nf3"], "https://lichess.org/game3")
        merged = merge_openings.merge_game_slices([s1, s2, s3])
        e4_node = merged.next()
        assert e4_node is not None
        # After e4: e5 and c5
        assert len(e4_node.variations) == 2

    def test_sources_comment_accumulates_correctly(self) -> None:
        moves = ["e4", "e5"]
        s1 = _make_slice(moves, "https://lichess.org/AAA")
        s2 = _make_slice(moves, "https://lichess.org/BBB")
        s3 = _make_slice(moves, "https://lichess.org/CCC")
        merged = merge_openings.merge_game_slices([s1, s2, s3])
        leaf_comment = merged.end().comment
        assert "https://lichess.org/AAA" in leaf_comment
        assert "https://lichess.org/BBB" in leaf_comment
        assert "https://lichess.org/CCC" in leaf_comment


# ── fetch_lichess_games ───────────────────────────────────────────────────────

class TestFetchLichessGames:
    def test_parses_ndjson_into_list(self) -> None:
        game1 = {"id": "abc", "moves": "e4 e5", "division": {"middle": 10}}
        game2 = {"id": "def", "moves": "d4 d5", "division": {"middle": 12}}
        lines = [
            json.dumps(game1).encode() + b"\n",
            b"\n",  # blank line should be ignored
            json.dumps(game2).encode() + b"\n",
        ]

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.__iter__ = lambda s: iter(lines)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = merge_openings.fetch_lichess_games("testuser", max_games=100)

        assert len(result) == 2
        assert result[0]["id"] == "abc"
        assert result[1]["id"] == "def"

    def test_max_games_none_omits_max_param(self) -> None:
        """When max_games is None the URL must not contain a max= parameter."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.__iter__ = lambda s: iter([])

        captured_url: list[str] = []

        def fake_urlopen(req: urllib.request.Request) -> MagicMock:
            captured_url.append(req.full_url)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            merge_openings.fetch_lichess_games("testuser", max_games=None)

        assert captured_url, "urlopen was not called"
        assert "max=" not in captured_url[0]

    def test_color_param_included_when_specified(self) -> None:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.__iter__ = lambda s: iter([])

        captured_url: list[str] = []

        def fake_urlopen(req: urllib.request.Request) -> MagicMock:
            captured_url.append(req.full_url)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            merge_openings.fetch_lichess_games("testuser", color="white")

        assert "color=white" in captured_url[0]

    def test_color_param_omitted_when_none(self) -> None:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.__iter__ = lambda s: iter([])

        captured_url: list[str] = []

        def fake_urlopen(req: urllib.request.Request) -> MagicMock:
            captured_url.append(req.full_url)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            merge_openings.fetch_lichess_games("testuser", color=None)

        assert "color=" not in captured_url[0]


# ── cache helpers ─────────────────────────────────────────────────────────────

class TestCacheHelpers:
    def test_save_and_load_roundtrip(self, tmp_path: "pytest.TempPathFactory") -> None:
        games = [{"id": "aaa", "moves": "e4 e5"}, {"id": "bbb", "moves": "d4 d5"}]
        cache_file = str(tmp_path / "games.json")
        merge_openings.save_games_to_cache(games, cache_file)
        loaded = merge_openings.load_games_from_cache(cache_file)
        assert loaded == games

    def test_saved_file_is_valid_json(self, tmp_path: "pytest.TempPathFactory") -> None:
        games = [{"id": "xyz"}]
        cache_file = str(tmp_path / "games.json")
        merge_openings.save_games_to_cache(games, cache_file)
        with open(cache_file, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed == games
