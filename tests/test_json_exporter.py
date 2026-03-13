from __future__ import annotations

import io
import json

import chess
import chess.pgn
import pytest

from chesstree.json_exporter import JsonExporter, to_edn, NAG_TO_PGN_STRING, collect_image_fens

SIMPLE_PGN = """\
[Event "Test Game"]
[Site "?"]
[Date "2024.01.01"]
[Round "1"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0
"""

VARIATION_PGN = """\
[Event "Variation Test"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 (1... c5 2. Nf3) 2. Nf3 1-0
"""


def _parse_game(pgn_text: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    assert game is not None
    return game


class TestJsonExporter:
    def test_basic_output_is_valid_json(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter()
        result = game.accept(exporter)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_headers_included(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter(headers=True)
        data = json.loads(game.accept(exporter))
        assert data["headers"]["White"] == "Alice"
        assert data["headers"]["Black"] == "Bob"

    def test_headers_excluded(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter(headers=False)
        data = json.loads(game.accept(exporter))
        assert data["headers"] == {}

    def test_moves_present(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter()
        data = json.loads(game.accept(exporter))
        assert len(data["moves"]) == 5  # e4, e5, Nf3, Nc6, Bb5

    def test_move_fields(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter()
        data = json.loads(game.accept(exporter))
        first_move = data["moves"][0]
        assert first_move["san"] == "e4"
        assert first_move["turn"] == "white"
        assert first_move["move_number"] == 1
        assert "fen" in first_move
        assert "uci" in first_move
        assert "board_img_after" in first_move

    def test_result(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter()
        data = json.loads(game.accept(exporter))
        assert data["result"] == "1-0"

    def test_concise_output_no_newlines(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter(concise=True)
        result = game.accept(exporter)
        assert "\n" not in result

    def test_pretty_output_has_newlines(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter(concise=False)
        result = game.accept(exporter)
        assert "\n" in result

    def test_edn_output(self):
        game = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter(edn=True)
        result = game.accept(exporter)
        assert result.startswith("{")
        assert ":headers" in result
        assert ":moves" in result

    def test_variations_included(self):
        game = _parse_game(VARIATION_PGN)
        exporter = JsonExporter(variations=True)
        data = json.loads(game.accept(exporter))
        # Second move entry should contain a variation dict
        variation_entries = [m for m in data["moves"] if "variation" in m]
        assert len(variation_entries) == 1

    def test_variations_excluded(self):
        game = _parse_game(VARIATION_PGN)
        exporter = JsonExporter(variations=False)
        data = json.loads(game.accept(exporter))
        variation_entries = [m for m in data["moves"] if "variation" in m]
        assert len(variation_entries) == 0

    def test_reset_between_games(self):
        game1 = _parse_game(SIMPLE_PGN)
        game2 = _parse_game(SIMPLE_PGN)
        exporter = JsonExporter()
        result1 = game1.accept(exporter)
        result2 = game2.accept(exporter)
        assert json.loads(result1) == json.loads(result2)


class TestToEdn:
    def test_dict(self):
        assert to_edn({"key": "value"}) == '{:key "value"}'

    def test_list(self):
        assert to_edn([1, 2, 3]) == "[1 2 3]"

    def test_string_as_keyword(self):
        assert to_edn("my_key", str_as_keyword=True) == ":my-key"

    def test_string_as_value(self):
        assert to_edn("hello") == '"hello"'

    def test_bool_true(self):
        assert to_edn(True) == "true"

    def test_bool_false(self):
        assert to_edn(False) == "false"

    def test_none(self):
        assert to_edn(None) == "nil"

    def test_number(self):
        assert to_edn(42) == "42"

    def test_nested(self):
        result = to_edn({"moves": [1, 2]})
        assert result == "{:moves [1 2]}"


class TestNagMapping:
    """Unit tests for the NAG → symbol mapping table."""

    # ------------------------------------------------------------------
    # Direct mapping table tests
    # ------------------------------------------------------------------

    def test_move_assessment_symbols(self):
        from chess.pgn import (
            NAG_GOOD_MOVE, NAG_MISTAKE, NAG_BRILLIANT_MOVE,
            NAG_BLUNDER, NAG_SPECULATIVE_MOVE, NAG_DUBIOUS_MOVE,
        )
        assert NAG_TO_PGN_STRING[NAG_GOOD_MOVE] == "!"
        assert NAG_TO_PGN_STRING[NAG_MISTAKE] == "?"
        assert NAG_TO_PGN_STRING[NAG_BRILLIANT_MOVE] == "!!"
        assert NAG_TO_PGN_STRING[NAG_BLUNDER] == "??"
        assert NAG_TO_PGN_STRING[NAG_SPECULATIVE_MOVE] == "!?"
        assert NAG_TO_PGN_STRING[NAG_DUBIOUS_MOVE] == "?!"

    def test_forced_move_symbol(self):
        from chess.pgn import NAG_FORCED_MOVE
        assert NAG_TO_PGN_STRING[NAG_FORCED_MOVE] == "□"

    def test_position_assessment_symbols(self):
        from chess.pgn import (
            NAG_DRAWISH_POSITION, NAG_UNCLEAR_POSITION,
            NAG_WHITE_SLIGHT_ADVANTAGE, NAG_BLACK_SLIGHT_ADVANTAGE,
            NAG_WHITE_MODERATE_ADVANTAGE, NAG_BLACK_MODERATE_ADVANTAGE,
            NAG_WHITE_DECISIVE_ADVANTAGE, NAG_BLACK_DECISIVE_ADVANTAGE,
        )
        assert NAG_TO_PGN_STRING[NAG_DRAWISH_POSITION] == "="
        assert NAG_TO_PGN_STRING[NAG_UNCLEAR_POSITION] == "∞"
        assert NAG_TO_PGN_STRING[NAG_WHITE_SLIGHT_ADVANTAGE] == "⩲"
        assert NAG_TO_PGN_STRING[NAG_BLACK_SLIGHT_ADVANTAGE] == "⩱"
        assert NAG_TO_PGN_STRING[NAG_WHITE_MODERATE_ADVANTAGE] == "±"
        assert NAG_TO_PGN_STRING[NAG_BLACK_MODERATE_ADVANTAGE] == "∓"
        assert NAG_TO_PGN_STRING[NAG_WHITE_DECISIVE_ADVANTAGE] == "+-"
        assert NAG_TO_PGN_STRING[NAG_BLACK_DECISIVE_ADVANTAGE] == "-+"

    def test_zugzwang_symbols(self):
        from chess.pgn import NAG_WHITE_ZUGZWANG, NAG_BLACK_ZUGZWANG
        assert NAG_TO_PGN_STRING[NAG_WHITE_ZUGZWANG] == "⨀"
        assert NAG_TO_PGN_STRING[NAG_BLACK_ZUGZWANG] == "⨀"

    def test_counterplay_symbols(self):
        from chess.pgn import (
            NAG_WHITE_MODERATE_COUNTERPLAY, NAG_BLACK_MODERATE_COUNTERPLAY,
            NAG_WHITE_DECISIVE_COUNTERPLAY, NAG_BLACK_DECISIVE_COUNTERPLAY,
        )
        assert NAG_TO_PGN_STRING[NAG_WHITE_MODERATE_COUNTERPLAY] == "⇆"
        assert NAG_TO_PGN_STRING[NAG_BLACK_MODERATE_COUNTERPLAY] == "⇆"
        assert NAG_TO_PGN_STRING[NAG_WHITE_DECISIVE_COUNTERPLAY] == "⇆"
        assert NAG_TO_PGN_STRING[NAG_BLACK_DECISIVE_COUNTERPLAY] == "⇆"

    def test_time_pressure_symbols(self):
        from chess.pgn import (
            NAG_WHITE_MODERATE_TIME_PRESSURE, NAG_BLACK_MODERATE_TIME_PRESSURE,
            NAG_WHITE_SEVERE_TIME_PRESSURE, NAG_BLACK_SEVERE_TIME_PRESSURE,
        )
        assert NAG_TO_PGN_STRING[NAG_WHITE_MODERATE_TIME_PRESSURE] == "⨁"
        assert NAG_TO_PGN_STRING[NAG_BLACK_MODERATE_TIME_PRESSURE] == "⨁"
        assert NAG_TO_PGN_STRING[NAG_WHITE_SEVERE_TIME_PRESSURE] == "⨁"
        assert NAG_TO_PGN_STRING[NAG_BLACK_SEVERE_TIME_PRESSURE] == "⨁"

    def test_novelty_symbol(self):
        from chess.pgn import NAG_NOVELTY
        assert NAG_TO_PGN_STRING[NAG_NOVELTY] == "N"

    def test_nags_without_standard_symbol_return_none(self):
        from chess.pgn import NAG_SINGULAR_MOVE, NAG_WORST_MOVE, NAG_QUIET_POSITION, NAG_ACTIVE_POSITION
        # These NAGs are defined by python-chess but have no standard PGN symbol
        assert NAG_TO_PGN_STRING.get(NAG_SINGULAR_MOVE) is None
        assert NAG_TO_PGN_STRING.get(NAG_WORST_MOVE) is None
        assert NAG_TO_PGN_STRING.get(NAG_QUIET_POSITION) is None
        assert NAG_TO_PGN_STRING.get(NAG_ACTIVE_POSITION) is None

    # ------------------------------------------------------------------
    # Integration: NAGs surfaced correctly through the full pipeline
    # ------------------------------------------------------------------

    def _game_with_nag(self, nag: int) -> dict:
        """Parse a minimal PGN where the first move carries the given NAG."""
        pgn = f"[Event \"NAG Test\"]\n[Result \"*\"]\n\n1. e4 ${nag} e5 *\n"
        game = chess.pgn.read_game(io.StringIO(pgn))
        assert game is not None
        exporter = JsonExporter()
        return json.loads(game.accept(exporter))

    def _first_move_nag_symbol(self, nag: int) -> str | None:
        data = self._game_with_nag(nag)
        e4 = data["moves"][0]
        assert "nags" in e4, f"Expected NAG on e4 for NAG {nag}"
        # JSON round-trip turns int keys to strings
        entry = next(n for n in e4["nags"] if list(n.keys())[0] == str(nag))
        return list(entry.values())[0]

    def test_integration_forced_move(self):
        from chess.pgn import NAG_FORCED_MOVE
        assert self._first_move_nag_symbol(NAG_FORCED_MOVE) == "□"

    def test_integration_drawish(self):
        from chess.pgn import NAG_DRAWISH_POSITION
        assert self._first_move_nag_symbol(NAG_DRAWISH_POSITION) == "="

    def test_integration_unclear(self):
        from chess.pgn import NAG_UNCLEAR_POSITION
        assert self._first_move_nag_symbol(NAG_UNCLEAR_POSITION) == "∞"

    def test_integration_white_slight_advantage(self):
        from chess.pgn import NAG_WHITE_SLIGHT_ADVANTAGE
        assert self._first_move_nag_symbol(NAG_WHITE_SLIGHT_ADVANTAGE) == "⩲"

    def test_integration_black_slight_advantage(self):
        from chess.pgn import NAG_BLACK_SLIGHT_ADVANTAGE
        assert self._first_move_nag_symbol(NAG_BLACK_SLIGHT_ADVANTAGE) == "⩱"

    def test_integration_white_moderate_advantage(self):
        from chess.pgn import NAG_WHITE_MODERATE_ADVANTAGE
        assert self._first_move_nag_symbol(NAG_WHITE_MODERATE_ADVANTAGE) == "±"

    def test_integration_black_moderate_advantage(self):
        from chess.pgn import NAG_BLACK_MODERATE_ADVANTAGE
        assert self._first_move_nag_symbol(NAG_BLACK_MODERATE_ADVANTAGE) == "∓"

    def test_integration_white_decisive_advantage(self):
        from chess.pgn import NAG_WHITE_DECISIVE_ADVANTAGE
        assert self._first_move_nag_symbol(NAG_WHITE_DECISIVE_ADVANTAGE) == "+-"

    def test_integration_black_decisive_advantage(self):
        from chess.pgn import NAG_BLACK_DECISIVE_ADVANTAGE
        assert self._first_move_nag_symbol(NAG_BLACK_DECISIVE_ADVANTAGE) == "-+"

    def test_integration_zugzwang(self):
        from chess.pgn import NAG_WHITE_ZUGZWANG, NAG_BLACK_ZUGZWANG
        assert self._first_move_nag_symbol(NAG_WHITE_ZUGZWANG) == "⨀"
        assert self._first_move_nag_symbol(NAG_BLACK_ZUGZWANG) == "⨀"

    def test_integration_counterplay(self):
        from chess.pgn import NAG_WHITE_MODERATE_COUNTERPLAY, NAG_BLACK_MODERATE_COUNTERPLAY
        assert self._first_move_nag_symbol(NAG_WHITE_MODERATE_COUNTERPLAY) == "⇆"
        assert self._first_move_nag_symbol(NAG_BLACK_MODERATE_COUNTERPLAY) == "⇆"

    def test_integration_time_pressure(self):
        from chess.pgn import NAG_WHITE_SEVERE_TIME_PRESSURE, NAG_BLACK_SEVERE_TIME_PRESSURE
        assert self._first_move_nag_symbol(NAG_WHITE_SEVERE_TIME_PRESSURE) == "⨁"
        assert self._first_move_nag_symbol(NAG_BLACK_SEVERE_TIME_PRESSURE) == "⨁"

    def test_integration_novelty(self):
        from chess.pgn import NAG_NOVELTY
        assert self._first_move_nag_symbol(NAG_NOVELTY) == "N"

    def test_integration_unknown_nag_symbol_is_none(self):
        from chess.pgn import NAG_SINGULAR_MOVE
        assert self._first_move_nag_symbol(NAG_SINGULAR_MOVE) is None


# ---------------------------------------------------------------------------
# collect_image_fens
# ---------------------------------------------------------------------------

def _load_pgn(pgn: str) -> chess.pgn.Game:
    return chess.pgn.read_game(io.StringIO(pgn))

BRANCH_PGN = """\
[Result "*"]

1. e4 e5 (1... c5 2. Nf3) 2. Nf3 *
"""

COMMENT_PGN = """\
[Result "*"]

1. e4 { good opening } e5 2. Nf3 *
"""


class TestCollectImageFens:
    def test_none_mode_returns_empty_set(self):
        game = _load_pgn(SIMPLE_PGN)
        result = collect_image_fens(game, frozenset(["none"]))
        assert result == set()

    def test_all_mode_returns_none(self):
        game = _load_pgn(SIMPLE_PGN)
        result = collect_image_fens(game, frozenset(["all"]))
        assert result is None

    def test_variations_mode_includes_last_move(self):
        game = _load_pgn(SIMPLE_PGN)
        fens = collect_image_fens(game, frozenset(["variations"]))
        # Last move of the 5-move game must be in the set
        node = game.variations[0]
        while node.variations:
            node = node.variations[0]
        assert node.board().fen() in fens

    def test_variations_mode_includes_branch_point(self):
        game = _load_pgn(BRANCH_PGN)
        fens = collect_image_fens(game, frozenset(["variations"]))
        # At 1. e4 there is a branch (1... e5 main, 1... c5 variation).
        # Image goes on the branching move (e5 = e4_node.variations[0]), not on e4 itself.
        e4_node = game.variations[0]
        e5_node = e4_node.variations[0]
        assert e5_node.board().fen() in fens
        assert e4_node.board().fen() not in fens

    def test_variations_mode_not_all_moves(self):
        game = _load_pgn(SIMPLE_PGN)
        fens = collect_image_fens(game, frozenset(["variations"]))
        total_moves = sum(1 for _ in game.mainline())
        assert len(fens) < total_moves

    def test_commented_mode_only_commented_fens(self):
        game = _load_pgn(COMMENT_PGN)
        fens = collect_image_fens(game, frozenset(["commented"]))
        # Only 1. e4 has a comment → only its FEN should be in the set
        e4_node = game.variations[0]
        assert e4_node.board().fen() in fens
        e5_node = e4_node.variations[0]
        assert e5_node.board().fen() not in fens

    def test_combined_variations_and_commented(self):
        game = _load_pgn(COMMENT_PGN)
        fens_vars = collect_image_fens(game, frozenset(["variations"]))
        fens_both = collect_image_fens(game, frozenset(["variations", "commented"]))
        assert fens_both >= fens_vars
