from __future__ import annotations

import io
import json

import chess
import chess.pgn
import pytest

from chesstree.json_exporter import JsonExporter, to_edn

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
        assert "board_img_before" in first_move
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
