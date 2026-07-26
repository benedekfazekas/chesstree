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
        """Label from create_slice is base only (no eval); eval added later by apply_leaf_evals."""
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
        assert label == "vs [Kasparov](https://lichess.org/evalgame)"

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

    def test_division_not_requested_in_url(self) -> None:
        """division=true must NOT appear in the Lichess API URL after local cutoff migration."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.__iter__ = lambda s: iter([])

        captured_url: list[str] = []

        def fake_urlopen(req: urllib.request.Request) -> MagicMock:
            captured_url.append(req.full_url)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            merge_openings.fetch_lichess_games("testuser")

        assert captured_url, "urlopen was not called"
        assert "division" not in captured_url[0]



# ── local cutoff path ─────────────────────────────────────────────────────────

class TestLocalCutoffPath:
    """Prove opening_end_ply is computed locally via chesstree.opening_divider."""

    def test_boards_from_moves_includes_initial(self) -> None:
        boards = merge_openings._boards_from_moves("e4 e5 Nf3")
        assert boards is not None
        assert len(boards) == 4  # initial + 3 moves
        assert boards[0].fen() == chess.Board().fen()

    def test_boards_from_moves_single_move(self) -> None:
        boards = merge_openings._boards_from_moves("e4")
        assert boards is not None
        assert len(boards) == 2

    def test_boards_from_moves_illegal_san_returns_none(self) -> None:
        assert merge_openings._boards_from_moves("e4 Xe9") is None

    def test_divider_returns_none_for_short_game(self) -> None:
        """A very short game stays in the opening — divider returns None."""
        from chesstree import opening_divider
        boards = merge_openings._boards_from_moves("e4 e5 Nf3")
        assert boards is not None
        assert opening_divider.opening_end_ply(boards) is None

    def test_main_uses_divider_not_division_middle(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """main() uses the local divider cutoff; division.middle in the game dict is ignored.

        The game dict has division.middle=1 (would cut after 1 ply under the old code).
        The divider returns None for a 3-move game, so the fallback is full-length (3 plies).
        The output PGN must contain all 3 moves (proving division.middle=1 was ignored).
        """
        moves = ["e4", "e5", "Nf3"]
        pgn = _pgn_str(moves)
        game_data = {
            "id": "localtest",
            "variant": "standard",
            "moves": " ".join(moves),
            "pgn": pgn,
            "division": {"middle": 1},  # old code would cut here — must be ignored
        }
        initial_fen = chess.Board().fen()
        with patch.object(merge_openings, "fetch_lichess_games", return_value=[game_data]):
            with patch.object(
                merge_openings.leaf_evaluator,
                "make_engine_provider",
                side_effect=merge_openings.leaf_evaluator.EngineUnavailable("no engine in CI"),
            ):
                with patch("sys.argv", ["merge_openings", "--username", "test", "--fen", initial_fen]):
                    merge_openings.main()
        captured = capsys.readouterr()
        # Divider returns None → fallback = 3 plies → all 3 moves in output
        assert "Nf3" in captured.out
        assert "[%opening_end]" in captured.out

    def test_main_uses_divider_computed_cutoff_matches_expectation(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """The local divider cutoff equals the expected ply for a known move sequence."""
        from chesstree import opening_divider
        # Use the lisperer sample from test fixtures — known divider output = 27
        import pathlib
        sample = pathlib.Path(__file__).parent / "sample_pgns" / "lisperer_vs_verenitach.pgn"
        import chess.pgn as pgn_mod
        with open(sample) as f:
            game = pgn_mod.read_game(f)
        assert game is not None
        from chesstree.opening_divider import boards_from_game
        boards = boards_from_game(game)
        assert opening_divider.opening_end_ply(boards) == 27


# ── apply_leaf_evals ──────────────────────────────────────────────────────────

class TestApplyLeafEvals:
    """Unit tests for apply_leaf_evals using stub providers — no real engine."""

    def _merged_with_lichess_eval(self, eval_str: str = "0.43") -> chess.pgn.Game:
        """Build a simple merged game whose leaf already has a Lichess [%eval]."""
        sliced, label = _make_slice(["e4", "e5"], "vs [Opp](https://lichess.org/g1)")
        sliced.end().comment = f"[%eval {eval_str}] [%opening_end]"
        merged = merge_openings.merge_game_slices([(sliced, label)])
        return merged

    def test_local_eval_takes_precedence_over_lichess(self) -> None:
        """Stub provider returns Cp(43); leaf label gets ': **0.43**' from local eval."""
        from chess.engine import PovScore, Cp
        merged = self._merged_with_lichess_eval("9.99")  # Lichess eval differs

        stub_score = PovScore(Cp(43), chess.WHITE)
        stub_provider = lambda board: stub_score

        merge_openings.apply_leaf_evals(merged, stub_provider)

        leaf_comment = merged.end().comment
        assert ": **0.43**" in leaf_comment
        assert "9.99" not in leaf_comment  # stale Lichess tag + value fully removed
        # Machine-readable tag present and consistent with the displayed value.
        assert "[%eval 0.43]" in leaf_comment
        assert merge_openings.extract_eval(leaf_comment) == "0.43"

    def test_fallback_to_lichess_when_provider_returns_none(self) -> None:
        """Provider returns None; leaf falls back to Lichess [%eval]."""
        merged = self._merged_with_lichess_eval("1.20")
        none_provider = lambda board: None

        merge_openings.apply_leaf_evals(merged, none_provider)

        leaf_comment = merged.end().comment
        assert ": **1.20**" in leaf_comment
        assert "[%eval 1.20]" in leaf_comment

    def test_no_eval_appended_when_both_unavailable(self) -> None:
        """No provider, no Lichess eval → no ': **...**' suffix."""
        sliced, label = _make_slice(["e4", "e5"], "vs [Opp](https://lichess.org/g1)")
        sliced.end().comment = "[%opening_end]"  # no [%eval]
        merged = merge_openings.merge_game_slices([(sliced, label)])

        merge_openings.apply_leaf_evals(merged, None)

        assert ": **" not in merged.end().comment

    def test_provider_none_uses_lichess_fallback(self) -> None:
        """provider=None means engine unavailable; Lichess [%eval] used for all leaves."""
        merged = self._merged_with_lichess_eval("0.55")

        merge_openings.apply_leaf_evals(merged, None)

        assert ": **0.55**" in merged.end().comment

    def test_dedup_provider_called_once_per_unique_fen(self) -> None:
        """Two branches reaching the same position → provider called only once."""
        from chess.engine import PovScore, Cp

        call_count = [0]

        def counting_provider(board: chess.Board) -> PovScore:
            call_count[0] += 1
            return PovScore(Cp(10), chess.WHITE)

        # Two slices with identical move sequences → same leaf FEN.
        s1 = _make_slice(["e4", "e5"], "vs [Opp1](https://lichess.org/g1)")
        s2 = _make_slice(["e4", "e5"], "vs [Opp2](https://lichess.org/g2)")
        merged = merge_openings.merge_game_slices([s1, s2])

        # Merged tree has one unique leaf.
        merge_openings.apply_leaf_evals(merged, counting_provider)

        assert call_count[0] == 1

    def test_diverging_leaves_each_get_eval(self) -> None:
        """Different leaf positions → provider called once per unique leaf."""
        from chess.engine import PovScore, Cp

        call_count = [0]

        def counting_provider(board: chess.Board) -> PovScore:
            call_count[0] += 1
            return PovScore(Cp(5), chess.WHITE)

        s1 = _make_slice(["e4", "e5"], "vs [Opp1](https://lichess.org/g1)")
        s2 = _make_slice(["e4", "c5"], "vs [Opp2](https://lichess.org/g2)")
        merged = merge_openings.merge_game_slices([s1, s2])

        merge_openings.apply_leaf_evals(merged, counting_provider)

        assert call_count[0] == 2
        # Both leaves should have the eval appended.
        leaves = []
        stack = list(merged.variations)
        while stack:
            node = stack.pop()
            if not node.variations:
                leaves.append(node)
            else:
                stack.extend(node.variations)
        assert all(": **0.05**" in leaf.comment for leaf in leaves)

    def test_mate_eval_formatted_correctly(self) -> None:
        """Mate score is formatted as #n."""
        from chess.engine import PovScore, Mate

        merged = self._merged_with_lichess_eval("0.00")
        stub_provider = lambda board: PovScore(Mate(3), chess.WHITE)

        merge_openings.apply_leaf_evals(merged, stub_provider)

        assert ": **#3**" in merged.end().comment
        assert "[%eval #3]" in merged.end().comment

    def test_local_eval_emits_machine_readable_tag_without_lichess(self) -> None:
        """Regression: a leaf with NO Lichess [%eval] but a local engine eval must
        still get a machine-readable [%eval ...] tag (not just markdown), so
        chesstree colors it and includes it in the variation summary.

        Mirrors the real 'unf2' game where Lichess had no eval.
        """
        from chess.engine import PovScore, Cp

        sliced, label = _make_slice(["e4", "e5"], "vs [unf2](https://lichess.org/yiNT31TP)")
        sliced.end().comment = "[%opening_end]"  # no [%eval] from Lichess
        merged = merge_openings.merge_game_slices([(sliced, label)])

        stub_provider = lambda board: PovScore(Cp(-425), chess.WHITE)
        merge_openings.apply_leaf_evals(merged, stub_provider)

        leaf_comment = merged.end().comment
        assert ": **-4.25**" in leaf_comment          # human label
        assert "[%eval -4.25]" in leaf_comment          # machine-readable tag
        assert merge_openings.extract_eval(leaf_comment) == "-4.25"

    def test_single_eval_tag_after_annotation(self) -> None:
        """Exactly one [%eval ...] remains even when the source carried a stale one."""
        from chess.engine import PovScore, Cp

        merged = self._merged_with_lichess_eval("9.99")
        stub_provider = lambda board: PovScore(Cp(43), chess.WHITE)
        merge_openings.apply_leaf_evals(merged, stub_provider)

        assert merged.end().comment.count("[%eval") == 1


# ── engine-unavailable path in main() ─────────────────────────────────────────

class TestEngineUnavailableInMain:
    def test_engine_unavailable_logs_warning_and_uses_lichess(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """EngineUnavailable → warning logged once; output still uses Lichess eval."""
        game = _build_game(["e4", "e5"])
        game.end().comment = "[%eval 0.77]"
        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        pgn = game.accept(exporter)
        players = {"white": {"user": {"name": "testuser"}}, "black": {"user": {"name": "Opp"}}}
        game_data = {
            "id": "eng_unavail",
            "variant": "standard",
            "moves": "e4 e5",
            "pgn": pgn,
            "players": players,
        }
        initial_fen = chess.Board().fen()
        with patch.object(merge_openings, "fetch_lichess_games", return_value=[game_data]):
            with patch.object(
                merge_openings.leaf_evaluator,
                "make_engine_provider",
                side_effect=merge_openings.leaf_evaluator.EngineUnavailable("binary missing"),
            ):
                with patch("sys.argv", ["merge_openings", "--username", "testuser", "--fen", initial_fen]):
                    merge_openings.main()

        captured = capsys.readouterr()
        assert "engine unavailable" in captured.err.lower()
        # Lichess fallback eval should appear in the PGN output.
        assert "0.77" in captured.out


# ── normalize_fen re-export ───────────────────────────────────────────────────

class TestNormalizeFenReexport:
    """merge_openings.normalize_fen must resolve (re-exported from chesstree.utils)."""

    def test_reexport_identity(self) -> None:
        from chesstree.utils import normalize_fen as utils_normalize
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        assert merge_openings.normalize_fen(fen) == utils_normalize(fen)


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
