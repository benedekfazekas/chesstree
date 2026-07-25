"""Tests for chesstree/opening_divider.py."""
from __future__ import annotations

import io
import json
import pathlib

import chess
import chess.pgn
import pytest

from chesstree.opening_divider import (
    BACKRANK_MIN,
    MIDDLEGAME_PIECE_THRESHOLD,
    MIXEDNESS_THRESHOLD,
    _MIXEDNESS_REGIONS,
    _backrank_sparse,
    _is_middlegame,
    _majors_and_minors,
    _mixedness,
    _mixedness_score,
    annotate_opening_end,
    boards_from_game,
    opening_end_ply,
)

SAMPLES = pathlib.Path(__file__).parent / "sample_pgns"
REPO_ROOT = pathlib.Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load(path: pathlib.Path) -> chess.pgn.Game:
    with open(path) as f:
        game = chess.pgn.read_game(f)
    assert game is not None
    return game


def _build_game(moves: list[str]) -> chess.pgn.Game:
    game = chess.pgn.Game()
    cursor: chess.pgn.GameNode = game
    for san in moves:
        cursor = cursor.add_variation(cursor.board().parse_san(san))
    return game


def _game_from_moves_str(moves_str: str) -> chess.pgn.Game:
    """Build a game from a space-separated SAN string (as stored in lisperer JSON)."""
    board = chess.Board()
    game = chess.pgn.Game()
    cursor: chess.pgn.GameNode = game
    for san in moves_str.split():
        move = board.parse_san(san)
        cursor = cursor.add_variation(move)
        board.push(move)
    return game


def _reference_mixedness(board: chess.Board) -> int:
    """Independent reimplementation of _mixedness for test cross-validation."""
    small = 0x0303
    white = board.occupied_co[chess.WHITE]
    black = board.occupied_co[chess.BLACK]
    acc = 0
    for y in range(7):
        for x in range(7):
            region = small << (x + 8 * y)
            ry = y + 1  # score uses y = i // 7 + 1
            wc = chess.popcount(white & region)
            bc = chess.popcount(black & region)
            acc += _mixedness_score(ry, wc, bc)
    return acc


# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_thresholds(self) -> None:
        assert MIDDLEGAME_PIECE_THRESHOLD == 10
        assert MIXEDNESS_THRESHOLD == 150
        assert BACKRANK_MIN == 4

    def test_regions_count(self) -> None:
        assert len(_MIXEDNESS_REGIONS) == 49

    def test_regions_are_2x2(self) -> None:
        for region in _MIXEDNESS_REGIONS:
            assert chess.popcount(region) == 4

    def test_regions_first(self) -> None:
        # First region: 0x0303 = a1,b1,a2,b2
        assert _MIXEDNESS_REGIONS[0] == 0x0303

    def test_regions_last(self) -> None:
        # Last region: y=6,x=6 → 0x0303 << (6 + 48) = 0x0303 << 54
        assert _MIXEDNESS_REGIONS[48] == (0x0303 << 54)


# ── _majors_and_minors ────────────────────────────────────────────────────────


class TestMajorsAndMinors:
    def test_initial_position(self) -> None:
        board = chess.Board()
        assert _majors_and_minors(board) == 14

    def test_empty_board_except_kings_and_pawns(self) -> None:
        # Only kings + pawns: 0 majors/minors
        board = chess.Board("4k3/pppppppp/8/8/8/8/PPPPPPPP/4K3 w - - 0 1")
        assert _majors_and_minors(board) == 0

    def test_exactly_ten_triggers_threshold(self) -> None:
        # 5 white majors/minors + 5 black (Q,R,B,B,N each): 10 total
        board = chess.Board("r1bqkb1r/pppppppp/8/8/8/8/PPPPPPPP/R1BQKB1R w KQkq - 0 1")
        assert _majors_and_minors(board) == 10

    def test_eleven_does_not_cross_threshold(self) -> None:
        # 12 majors/minors — below threshold
        board = chess.Board("rnbqkb1r/pppppppp/8/8/8/8/PPPPPPPP/RNBQKB1R w KQkq - 0 1")
        assert _majors_and_minors(board) == 12
        assert _majors_and_minors(board) > MIDDLEGAME_PIECE_THRESHOLD


# ── _backrank_sparse ──────────────────────────────────────────────────────────


class TestBackrankSparse:
    def test_initial_position_not_sparse(self) -> None:
        board = chess.Board()
        assert not _backrank_sparse(board)

    def test_white_sparse(self) -> None:
        # Only 3 white pieces on rank 1 (K, Q, R)
        board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/3QK2R w Kkq - 0 1")
        assert chess.popcount(chess.BB_RANK_1 & board.occupied_co[chess.WHITE]) == 3
        assert _backrank_sparse(board)

    def test_black_sparse(self) -> None:
        # Only 3 black pieces on rank 8 (k, q, r)
        board = chess.Board("3qk2r/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQk - 0 1")
        assert chess.popcount(chess.BB_RANK_8 & board.occupied_co[chess.BLACK]) == 3
        assert _backrank_sparse(board)

    def test_exactly_four_not_sparse(self) -> None:
        # Exactly 4 on each back rank — not sparse
        board = chess.Board("r3kb1r/pppppppp/8/8/8/8/PPPPPPPP/R3KB1R w KQkq - 0 1")
        wc = chess.popcount(chess.BB_RANK_1 & board.occupied_co[chess.WHITE])
        bc = chess.popcount(chess.BB_RANK_8 & board.occupied_co[chess.BLACK])
        assert wc == 4 and bc == 4
        assert not _backrank_sparse(board)


# ── _mixedness_score ──────────────────────────────────────────────────────────


class TestMixednessScore:
    def test_zero_zero(self) -> None:
        # No pieces in region → 0 for all y
        for y in range(1, 8):
            assert _mixedness_score(y, 0, 0) == 0

    def test_white1_black0(self) -> None:
        # 1 + (8 - y) for any y in 1..7
        for y in range(1, 8):
            assert _mixedness_score(y, 1, 0) == 1 + (8 - y)

    def test_white0_black1(self) -> None:
        # 1 + y
        for y in range(1, 8):
            assert _mixedness_score(y, 0, 1) == 1 + y

    def test_white2_black2(self) -> None:
        # always 7
        for y in range(1, 8):
            assert _mixedness_score(y, 2, 2) == 7

    def test_white1_black1(self) -> None:
        # 5 + abs(4 - y)
        for y in range(1, 8):
            assert _mixedness_score(y, 1, 1) == 5 + abs(4 - y)

    def test_white4_black1_zero(self) -> None:
        # white=4, black=1 → else branch → 0
        for y in range(1, 8):
            assert _mixedness_score(y, 4, 1) == 0

    def test_white5_any_zero(self) -> None:
        for y in range(1, 8):
            assert _mixedness_score(y, 5, 0) == 0

    def test_white0_black2_boundary(self) -> None:
        # y<6 triggers; y=5: 2+(6-5)=3; y=6 and y=7: 0 (condition y<6 false)
        assert _mixedness_score(5, 0, 2) == 3
        assert _mixedness_score(6, 0, 2) == 0
        assert _mixedness_score(7, 0, 2) == 0

    def test_white0_black3_boundary(self) -> None:
        # y<7: 3+(7-y); y=7: 0
        assert _mixedness_score(6, 0, 3) == 4
        assert _mixedness_score(7, 0, 3) == 0

    def test_white2_black0_boundary(self) -> None:
        # y>2: 2+(y-2); y<=2: 0
        assert _mixedness_score(3, 2, 0) == 3
        assert _mixedness_score(2, 2, 0) == 0


# ── _mixedness ────────────────────────────────────────────────────────────────


class TestMixedness:
    def test_initial_position_not_middlegame(self) -> None:
        board = chess.Board()
        score = _mixedness(board)
        # Opening must not end at ply 0
        assert score <= MIXEDNESS_THRESHOLD

    def test_initial_position_score(self) -> None:
        # Initial position: all pieces on back ranks, separated — score is 0
        board = chess.Board()
        assert _mixedness(board) == 0

    def test_matches_reference_implementation(self) -> None:
        board = chess.Board()
        assert _mixedness(board) == _reference_mixedness(board)

    def test_mixed_position_exceeds_threshold(self) -> None:
        # A mid-game position with pieces interleaved across the center
        board = chess.Board("r3k3/1pp2ppp/p1nb1n2/q1ppp3/3PPPP1/2NBBN2/PPP1Q1P1/R3K2R w KQq - 0 1")
        score = _mixedness(board)
        assert score > MIXEDNESS_THRESHOLD

    def test_mixed_position_matches_reference(self) -> None:
        board = chess.Board("r3k3/1pp2ppp/p1nb1n2/q1ppp3/3PPPP1/2NBBN2/PPP1Q1P1/R3K2R w KQq - 0 1")
        assert _mixedness(board) == _reference_mixedness(board)


# ── _is_middlegame ────────────────────────────────────────────────────────────


class TestIsMiddlegame:
    def test_initial_position_not_middlegame(self) -> None:
        assert not _is_middlegame(chess.Board())

    def test_sparse_triggers_middlegame(self) -> None:
        # 3 white pieces on rank 1 → backrankSparse → middlegame
        board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/3QK2R w Kkq - 0 1")
        assert _is_middlegame(board)

    def test_piece_count_triggers_middlegame(self) -> None:
        # 10 majors/minors → triggers
        board = chess.Board("r1bqkb1r/pppppppp/8/8/8/8/PPPPPPPP/R1BQKB1R w KQkq - 0 1")
        assert _is_middlegame(board)

    def test_mixedness_triggers_middlegame(self) -> None:
        board = chess.Board("r3k3/1pp2ppp/p1nb1n2/q1ppp3/3PPPP1/2NBBN2/PPP1Q1P1/R3K2R w KQq - 0 1")
        assert _is_middlegame(board)


# ── boards_from_game ──────────────────────────────────────────────────────────


class TestBoardsFromGame:
    def test_includes_initial_position(self) -> None:
        game = chess.pgn.Game()
        boards = boards_from_game(game)
        assert len(boards) == 1
        assert boards[0].fen() == chess.Board().fen()

    def test_length_equals_moves_plus_one(self) -> None:
        game = _build_game(["e4", "e5", "Nf3"])
        boards = boards_from_game(game)
        assert len(boards) == 4  # initial + 3 moves

    def test_boards_at_correct_positions(self) -> None:
        game = _build_game(["e4", "e5"])
        boards = boards_from_game(game)
        # boards[0]: initial
        assert boards[0].fen() == chess.Board().fen()
        # boards[1]: after e4
        b = chess.Board()
        b.push_san("e4")
        assert boards[1].fen() == b.fen()

    def test_main_line_only(self) -> None:
        # Variations should not affect board count
        game = chess.pgn.Game()
        node = game.add_variation(game.board().parse_san("e4"))
        node.add_variation(node.board().parse_san("e5"))
        node.add_variation(node.board().parse_san("c5"))  # variation
        boards = boards_from_game(game)
        assert len(boards) == 3  # initial + e4 + e5 (main line)


# ── opening_end_ply ───────────────────────────────────────────────────────────


class TestOpeningEndPly:
    def test_very_short_game_returns_none(self) -> None:
        # Only 2 moves: opening never ends
        game = _build_game(["e4", "e5"])
        result = opening_end_ply(game)
        # With only the initial position and 2 moves, none should trigger
        # (all boards are very opening-like with 14 m&m and not sparse)
        assert result is None

    def test_accepts_board_sequence(self) -> None:
        boards = [chess.Board()]
        result = opening_end_ply(boards)
        assert result is None  # initial position never triggers

    def test_ply_indexes_first_qualifying_board(self) -> None:
        # Build a game where we know the opening ends. Use lisperer sample.
        game = _load(SAMPLES / "hillbilly_v3.pgn")
        ply = opening_end_ply(game)
        assert ply is not None
        boards = boards_from_game(game)
        # boards[ply] must be the first qualifying board
        assert _is_middlegame(boards[ply])
        # boards[ply-1] must NOT be (if ply > 0)
        if ply > 0:
            assert not _is_middlegame(boards[ply - 1])

    def test_initial_position_never_ply_zero(self) -> None:
        # ply 0 = initial position: should never trigger
        game = chess.pgn.Game()
        result = opening_end_ply(game)
        assert result is None

    def test_result_is_int_or_none(self) -> None:
        game = _load(SAMPLES / "lisperer_vs_verenitach.pgn")
        result = opening_end_ply(game)
        assert result is None or isinstance(result, int)


# ── annotate_opening_end ──────────────────────────────────────────────────────


class TestAnnotateOpeningEnd:
    def test_annotates_correct_node(self) -> None:
        game = _build_game(["e4", "e5", "Nf3", "Nc6"])
        annotate_opening_end(game, 2)
        # ply=2: root → e4 → e5; the node at depth 2 is after e5
        node = game.variations[0].variations[0]  # after e5
        assert "[%opening_end]" in node.comment

    def test_annotates_root_at_ply_zero(self) -> None:
        game = _build_game(["e4", "e5"])
        annotate_opening_end(game, 0)
        assert "[%opening_end]" in game.comment

    def test_preserves_existing_comment(self) -> None:
        game = _build_game(["e4", "e5"])
        # Set existing comment on the e5 node (ply=2)
        game.variations[0].variations[0].comment = "Great move!"
        annotate_opening_end(game, 2)
        node = game.variations[0].variations[0]
        assert "Great move!" in node.comment
        assert "[%opening_end]" in node.comment

    def test_no_duplication_if_already_present(self) -> None:
        game = _build_game(["e4", "e5"])
        game.variations[0].comment = "[%opening_end]"
        annotate_opening_end(game, 1)
        node = game.variations[0]
        assert node.comment.count("[%opening_end]") == 1

    def test_ply_beyond_game_length_safe(self) -> None:
        # Should not raise even if ply > game length
        game = _build_game(["e4"])
        annotate_opening_end(game, 100)  # no crash

    def test_comment_format_strip_and_join(self) -> None:
        game = _build_game(["e4"])
        game.variations[0].comment = "  Existing  "
        annotate_opening_end(game, 1)
        comment = game.variations[0].comment
        assert not comment.startswith(" ")
        assert "[%opening_end]" in comment
        assert "Existing" in comment


# ── Parity: lisperer-games-black.json ────────────────────────────────────────


class TestParityLichessCorpus:
    """Primary proof: our divider reproduces Lichess division.middle exactly."""

    @pytest.fixture(scope="class")
    def corpus(self) -> list[dict]:
        corpus_path = REPO_ROOT / "lisperer-games-black.json"
        with open(corpus_path) as f:
            return json.load(f)

    def test_standard_subset_is_large(self, corpus: list[dict]) -> None:
        standard = [g for g in corpus if g.get("variant", "standard") == "standard"]
        assert len(standard) > 300

    def test_parity_against_lichess_division_middle(self, corpus: list[dict]) -> None:
        mismatches: list[str] = []

        for g in corpus:
            if g.get("variant", "standard") != "standard":
                continue

            moves_str = g.get("moves", "")
            game = _game_from_moves_str(moves_str)

            expected = g.get("division", {}).get("middle")
            computed = opening_end_ply(game)

            if expected != computed:
                mismatches.append(
                    f"id={g['id']} expected={expected} computed={computed}"
                )

        assert not mismatches, (
            f"{len(mismatches)} mismatch(es):\n" + "\n".join(mismatches[:10])
        )

    def test_no_middle_games_return_none(self, corpus: list[dict]) -> None:
        """Games where Lichess omits division.middle should return None."""
        no_middle = [
            g for g in corpus
            if g.get("variant", "standard") == "standard"
            and "middle" not in g.get("division", {})
        ]
        for g in no_middle:
            game = _game_from_moves_str(g.get("moves", ""))
            assert opening_end_ply(game) is None, (
                f"Expected None for game {g['id']} but got a value"
            )


# ── Regression golden fixtures ────────────────────────────────────────────────


class TestGoldenFixtures:
    def test_hillbilly_v3(self) -> None:
        game = _load(SAMPLES / "hillbilly_v3.pgn")
        assert opening_end_ply(game) == 19

    def test_lisperer_vs_verenitach(self) -> None:
        game = _load(SAMPLES / "lisperer_vs_verenitach.pgn")
        assert opening_end_ply(game) == 27

    def test_hillbilly_ply_is_first_qualifying(self) -> None:
        game = _load(SAMPLES / "hillbilly_v3.pgn")
        ply = opening_end_ply(game)
        assert ply is not None
        boards = boards_from_game(game)
        assert _is_middlegame(boards[ply])
        for i in range(ply):
            assert not _is_middlegame(boards[i]), f"boards[{i}] unexpectedly qualifies"
