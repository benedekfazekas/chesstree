"""Tests for chesstree/leaf_evaluator.py — pure core with stub providers."""
from __future__ import annotations

import io
import re

import chess
import chess.engine
import chess.pgn
import pytest

from chesstree.leaf_evaluator import (
    ALL,
    BRANCHES,
    DEFAULT_DEPTH,
    TERMINAL,
    EngineUnavailable,
    EvalProvider,
    annotate_evals,
    format_eval,
    make_engine_provider,
    _select_nodes,
)
from chesstree.utils import normalize_fen


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_pgn(pgn: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    return game


def _stub_provider(score: chess.engine.PovScore | None) -> EvalProvider:
    """Return a provider that always returns the given score."""
    def provider(board: chess.Board) -> chess.engine.PovScore | None:
        return score
    return provider


def _recording_provider(
    score: chess.engine.PovScore | None,
) -> tuple[EvalProvider, list[str]]:
    """Return a provider + list that records normalized FENs it is called with."""
    calls: list[str] = []

    def provider(board: chess.Board) -> chess.engine.PovScore | None:
        calls.append(normalize_fen(board.fen()))
        return score

    return provider, calls


def _pov_cp(cp: int) -> chess.engine.PovScore:
    return chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE)


def _pov_mate(n: int) -> chess.engine.PovScore:
    return chess.engine.PovScore(chess.engine.Mate(n), chess.WHITE)


# ── Sample game with variations ───────────────────────────────────────────────
#
#  Main line:    1. e4  e5  2. Nf3  Nc6  3. Bb5
#  Variation A (after 1. e4): 1... c5   (Sicilian instead of e5)
#  Sub-variation (after 1. e4 c5): 2. d4
#  Leaf of main line: after 3. Bb5
#  Leaf of variation A (no sub-var): after 1. e4 c5 in sub-var → after 2. d4
#  Leaf of variation A main:         after 1. e4 c5 (no continuation)

_FORK_PGN = """\
[Event "Test"]
[Site "?"]
[Date "2024.01.01"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 ( 1... c5 2. d4 ) 2. Nf3 Nc6 3. Bb5 *
"""

# Node counts in _FORK_PGN:
# root (game node, no move)
# after e4             — branch point (has variations: e5 and c5)
# after e5             — main line continuation
# after c5             — variation leaf? no, has child 2.d4
# after d4             — leaf (variation A end)
# after Nf3            — continuation
# after Nc6            — continuation
# after Bb5            — leaf (main line end)

# Total nodes incl root = 8


# ── normalize_fen tests ───────────────────────────────────────────────────────


class TestNormalizeFen:
    def test_drops_halfmove_and_fullmove(self) -> None:
        full = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        result = normalize_fen(full)
        assert result == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"

    def test_passthrough_when_4_fields(self) -> None:
        four = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"
        assert normalize_fen(four) == four

    def test_no_en_passant(self) -> None:
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        assert normalize_fen(fen) == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"


# ── format_eval ───────────────────────────────────────────────────────────────


class TestFormatEval:
    def test_cp_positive(self) -> None:
        assert format_eval(_pov_cp(43)) == "0.43"

    def test_cp_negative(self) -> None:
        assert format_eval(_pov_cp(-120)) == "-1.20"

    def test_cp_zero(self) -> None:
        assert format_eval(_pov_cp(0)) == "0.00"

    def test_mate_positive(self) -> None:
        assert format_eval(_pov_mate(3)) == "#3"

    def test_mate_negative(self) -> None:
        assert format_eval(_pov_mate(-3)) == "#-3"

    def test_cp_large(self) -> None:
        assert format_eval(_pov_cp(500)) == "5.00"

    def test_cp_negative_one_pawn(self) -> None:
        assert format_eval(_pov_cp(-100)) == "-1.00"


# ── Round-trip: format → embed → parse (matches json_exporter logic) ──────────


class TestRoundTrip:
    """Verify format_eval is the exact inverse of the json_exporter eval parser."""

    def _parse_eval_from_comment(self, comment: str) -> dict | None:
        """Mirror json_exporter._extract_command_annotations eval extraction."""
        m = chess.pgn.EVAL_REGEX.search(comment)
        if not m:
            return None
        if m.group("mate"):
            return {"mate": int(m.group("mate"))}
        return {"cp": round(float(m.group("cp")) * 100)}

    def _round_trip(self, pov: chess.engine.PovScore) -> dict:
        formatted = format_eval(pov)
        comment = f"[%eval {formatted}]"
        parsed = self._parse_eval_from_comment(comment)
        assert parsed is not None
        return parsed

    def test_cp_43(self) -> None:
        assert self._round_trip(_pov_cp(43)) == {"cp": 43}

    def test_cp_minus_120(self) -> None:
        assert self._round_trip(_pov_cp(-120)) == {"cp": -120}

    def test_cp_zero(self) -> None:
        assert self._round_trip(_pov_cp(0)) == {"cp": 0}

    def test_mate_3(self) -> None:
        assert self._round_trip(_pov_mate(3)) == {"mate": 3}

    def test_mate_minus_3(self) -> None:
        assert self._round_trip(_pov_mate(-3)) == {"mate": -3}


# ── Scope selection ───────────────────────────────────────────────────────────


class TestScopeSelection:
    def test_leaves_only_count(self) -> None:
        game = _load_pgn(_FORK_PGN)
        nodes = _select_nodes(game, TERMINAL)
        # Leaves: after Bb5 (main line end), after d4 (variation end)
        assert len(nodes) == 2

    def test_leaves_are_end_nodes(self) -> None:
        game = _load_pgn(_FORK_PGN)
        nodes = _select_nodes(game, TERMINAL)
        for node in nodes:
            assert node.is_end()

    def test_branch_points_includes_leaves_and_fork(self) -> None:
        game = _load_pgn(_FORK_PGN)
        nodes = _select_nodes(game, BRANCHES)
        # 2 leaves + 1 branch point (after e4, which has e5 and c5)
        assert len(nodes) == 3

    def test_branch_point_has_multiple_variations(self) -> None:
        game = _load_pgn(_FORK_PGN)
        nodes = _select_nodes(game, BRANCHES)
        branch_nodes = [n for n in nodes if not n.is_end()]
        assert len(branch_nodes) == 1
        assert len(branch_nodes[0].variations) > 1

    def test_all_includes_root_and_all_moves(self) -> None:
        game = _load_pgn(_FORK_PGN)
        nodes = _select_nodes(game, ALL)
        # root + e4 + e5 + c5 + d4 + Nf3 + Nc6 + Bb5 = 8
        assert len(nodes) == 8

    def test_invalid_scope_raises(self) -> None:
        game = _load_pgn(_FORK_PGN)
        with pytest.raises(ValueError, match="Unknown scope"):
            _select_nodes(game, "invalid-scope")

    def test_variation_leaf_included_in_leaves(self) -> None:
        game = _load_pgn(_FORK_PGN)
        nodes = _select_nodes(game, TERMINAL)
        # Both leaves are end nodes — one is in a variation
        end_sans = set()
        for n in nodes:
            if hasattr(n, "move") and n.move is not None:
                board = n.parent.board()  # type: ignore[union-attr]
                end_sans.add(board.san(n.move))
        assert "Bb5" in end_sans  # main line end
        assert "d4" in end_sans   # variation end


# ── annotate_evals: basic annotation ─────────────────────────────────────────


class TestAnnotateEvals:
    def test_appends_eval_annotation(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider = _stub_provider(_pov_cp(43))
        count = annotate_evals(game, provider, scope=TERMINAL)
        assert count == 2
        nodes = _select_nodes(game, TERMINAL)
        for node in nodes:
            assert "[%eval 0.43]" in node.comment

    def test_preserves_existing_human_comment(self) -> None:
        game = _load_pgn(_FORK_PGN)
        # Add a human comment to the main-line leaf
        leaf = _select_nodes(game, TERMINAL)[0]
        leaf.comment = "Ruy Lopez!"
        provider = _stub_provider(_pov_cp(55))
        annotate_evals(game, provider, scope=TERMINAL)
        assert "Ruy Lopez!" in leaf.comment
        assert "[%eval 0.55]" in leaf.comment

    def test_returns_correct_count(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider = _stub_provider(_pov_cp(0))
        count = annotate_evals(game, provider, scope=TERMINAL)
        assert count == 2

    def test_branches_scope_annotates_more_nodes(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider = _stub_provider(_pov_cp(10))
        count = annotate_evals(game, provider, scope=BRANCHES)
        assert count == 3

    def test_all_scope_annotates_all_nodes(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider = _stub_provider(_pov_cp(10))
        count = annotate_evals(game, provider, scope=ALL)
        assert count == 8  # root + all moves


# ── overwrite behaviour ───────────────────────────────────────────────────────


class TestOverwrite:
    def test_no_overwrite_skips_existing_eval(self) -> None:
        game = _load_pgn(_FORK_PGN)
        # Pre-annotate one leaf
        leaf = _select_nodes(game, TERMINAL)[0]
        leaf.comment = "[%eval 0.99]"
        provider = _stub_provider(_pov_cp(43))
        count = annotate_evals(game, provider, scope=TERMINAL, overwrite=False)
        # Only 1 annotated (the other leaf was skipped)
        assert count == 1
        assert "[%eval 0.99]" in leaf.comment  # old value kept
        assert "[%eval 0.43]" not in leaf.comment

    def test_overwrite_replaces_old_eval(self) -> None:
        game = _load_pgn(_FORK_PGN)
        leaf = _select_nodes(game, TERMINAL)[0]
        leaf.comment = "Nice! [%eval 0.99]"
        provider = _stub_provider(_pov_cp(43))
        count = annotate_evals(game, provider, scope=TERMINAL, overwrite=True)
        assert count == 2
        assert "[%eval 0.43]" in leaf.comment
        assert "[%eval 0.99]" not in leaf.comment

    def test_overwrite_preserves_other_comment_text(self) -> None:
        game = _load_pgn(_FORK_PGN)
        leaf = _select_nodes(game, TERMINAL)[0]
        leaf.comment = "Interesting! [%eval 0.99] Good play."
        provider = _stub_provider(_pov_cp(43))
        annotate_evals(game, provider, scope=TERMINAL, overwrite=True)
        assert "Interesting!" in leaf.comment
        assert "Good play." in leaf.comment
        assert "[%eval 0.43]" in leaf.comment
        assert "[%eval 0.99]" not in leaf.comment


# ── de-duplication ────────────────────────────────────────────────────────────

_TRANSPOSITION_PGN = """\
[Event "Transposition"]
[Site "?"]
[Date "2024.01.01"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 ( 1... e5 ) *
"""
# Both 1... e5 (main line) and the variation 1... e5 share the same position.
# provider should be called ONCE for that normalized FEN.


class TestDeDuplication:
    def test_provider_called_once_per_unique_fen(self) -> None:
        # Build a game where two leaves share the same normalized FEN.
        # Construct manually: after 1. e4 e5, add a variation that also leads to
        # the same position (same board state after e5 in both lines).
        game = chess.pgn.Game()
        e4 = game.add_variation(game.board().parse_san("e4"))
        e5_main = e4.add_variation(e4.board().parse_san("e5"))
        # Add a second variation from e4 that also plays e5 (same position)
        e5_var = e4.add_variation(e4.board().parse_san("e5"))

        provider, calls = _recording_provider(_pov_cp(10))
        annotate_evals(game, provider, scope=TERMINAL)

        # Both leaves are at the same normalized FEN → provider called once
        assert len(calls) == 1

    def test_different_positions_called_separately(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider, calls = _recording_provider(_pov_cp(10))
        annotate_evals(game, provider, scope=TERMINAL)
        # 2 leaves with different positions → 2 calls
        assert len(calls) == 2

    def test_call_count_equals_unique_fens(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider, calls = _recording_provider(_pov_cp(5))
        annotate_evals(game, provider, scope=BRANCHES)
        # 3 targets, all at different positions → 3 calls
        assert len(calls) == 3


# ── None provider result ──────────────────────────────────────────────────────


class TestNoneProvider:
    def test_none_leaves_nodes_unannotated(self) -> None:
        game = _load_pgn(_FORK_PGN)
        provider = _stub_provider(None)
        count = annotate_evals(game, provider, scope=TERMINAL)
        assert count == 0
        for node in _select_nodes(game, TERMINAL):
            assert "[%eval" not in node.comment

    def test_partial_none_counts_only_annotated(self) -> None:
        game = _load_pgn(_FORK_PGN)
        leaves = _select_nodes(game, TERMINAL)
        # Pre-populate so we know which FEN maps to which leaf
        fens = [normalize_fen(n.board().fen()) for n in leaves]
        target_fen = fens[0]

        def selective_provider(board: chess.Board) -> chess.engine.PovScore | None:
            if normalize_fen(board.fen()) == target_fen:
                return _pov_cp(77)
            return None

        count = annotate_evals(game, selective_provider, scope=TERMINAL)
        assert count == 1


# ── make_engine_provider ──────────────────────────────────────────────────────


class TestMakeEngineProvider:
    def test_bogus_binary_raises_engine_unavailable(self) -> None:
        with pytest.raises(EngineUnavailable, match="definitely-not-a-real-engine-binary-xyz"):
            make_engine_provider("definitely-not-a-real-engine-binary-xyz")

    def test_provider_returns_pov_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected_score = chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE)
        analyse_calls: list[tuple] = []

        class FakeEngine:
            def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> chess.engine.InfoDict:
                analyse_calls.append((board, limit, kwargs))
                return {"score": expected_score}  # type: ignore[return-value]

            def quit(self) -> None:
                pass

        monkeypatch.setattr(
            chess.engine.SimpleEngine,
            "popen_uci",
            staticmethod(lambda path, **kw: FakeEngine()),
        )

        board = chess.Board()
        provider, closer = make_engine_provider()
        result = provider(board)
        closer()

        assert result == expected_score
        assert len(analyse_calls) == 1
        _board, limit, _kwargs = analyse_calls[0]
        assert limit == chess.engine.Limit(depth=DEFAULT_DEPTH)

    def test_provider_returns_none_on_engine_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeEngine:
            def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> chess.engine.InfoDict:
                raise chess.engine.EngineError("boom")

            def quit(self) -> None:
                pass

        monkeypatch.setattr(
            chess.engine.SimpleEngine,
            "popen_uci",
            staticmethod(lambda path, **kw: FakeEngine()),
        )

        provider, closer = make_engine_provider()
        result = provider(chess.Board())
        closer()

        assert result is None

    def test_closer_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        quit_calls: list[int] = []

        class FakeEngine:
            def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> chess.engine.InfoDict:
                return {"score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE)}  # type: ignore[return-value]

            def quit(self) -> None:
                quit_calls.append(1)

        monkeypatch.setattr(
            chess.engine.SimpleEngine,
            "popen_uci",
            staticmethod(lambda path, **kw: FakeEngine()),
        )

        _provider, closer = make_engine_provider()
        closer()
        closer()  # second call must not raise

        assert len(quit_calls) == 1  # quit called exactly once

    def test_multipv_uses_first_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        score0 = chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE)
        score1 = chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE)

        class FakeEngine:
            def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> list[chess.engine.InfoDict]:
                return [{"score": score0}, {"score": score1}]  # type: ignore[return-value]

            def quit(self) -> None:
                pass

        monkeypatch.setattr(
            chess.engine.SimpleEngine,
            "popen_uci",
            staticmethod(lambda path, **kw: FakeEngine()),
        )

        provider, closer = make_engine_provider(multipv=2)
        result = provider(chess.Board())
        closer()

        assert result == score0

    def test_custom_limit_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom_limit = chess.engine.Limit(depth=5)
        analyse_calls: list[chess.engine.Limit] = []

        class FakeEngine:
            def analyse(self, board: chess.Board, limit: chess.engine.Limit, **kwargs) -> chess.engine.InfoDict:
                analyse_calls.append(limit)
                return {"score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE)}  # type: ignore[return-value]

            def quit(self) -> None:
                pass

        monkeypatch.setattr(
            chess.engine.SimpleEngine,
            "popen_uci",
            staticmethod(lambda path, **kw: FakeEngine()),
        )

        provider, closer = make_engine_provider(limit=custom_limit)
        provider(chess.Board())
        closer()

        assert analyse_calls[0] == custom_limit
