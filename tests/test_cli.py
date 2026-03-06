from __future__ import annotations

import io
import json
import sys

import chess.pgn
import pytest

from chesstree.cli import pgn_to_json, json_to_pgn, _detect_input_format
from chesstree.json_exporter import JsonExporter

SIMPLE_PGN = """\
[Event "Test Game"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 1-0
"""

EMPTY_PGN = ""  # empty input → read_game returns None


def _make_input(text: str, name: str = "<test>") -> io.StringIO:
    f = io.StringIO(text)
    f.name = name
    return f


def _make_output(name: str = "<stdout>") -> io.StringIO:
    f = io.StringIO()
    f.name = name
    return f


def _pgn_to_json_str(pgn: str) -> str:
    """Helper: convert a PGN string to JSON via JsonExporter."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    return game.accept(JsonExporter(headers=True, comments=True, variations=True))


class TestPgnToJson:
    def test_basic_conversion_produces_valid_json(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=False, edn=False)
        output_f.seek(0)
        data = json.loads(output_f.read())
        assert data["headers"]["White"] == "Alice"
        assert data["result"] == "1-0"

    def test_edn_output(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=False, edn=True)
        output_f.seek(0)
        result = output_f.read()
        assert ":headers" in result
        assert ":moves" in result

    def test_concise_output(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=False, edn=False, concise=True)
        output_f.seek(0)
        # Trim trailing newlines added by print(..., end="\n\n")
        result = output_f.read().strip()
        assert "\n" not in result

    def test_forblack_flag_accepted(self):
        """Smoke test that the forblack flag doesn't raise."""
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=True, edn=False)
        output_f.seek(0)
        data = json.loads(output_f.read())
        assert len(data["moves"]) > 0

    def test_empty_pgn_exits_with_error(self):
        output_f = _make_output()
        with pytest.raises(SystemExit) as exc_info:
            pgn_to_json(_make_input(EMPTY_PGN), output_f, forblack=False, edn=False)
        assert exc_info.value.code == 1


class TestJsonToPgn:
    def test_basic_conversion_produces_valid_pgn(self):
        json_input = _make_input(_pgn_to_json_str(SIMPLE_PGN), "<test.json>")
        output_f = _make_output()
        json_to_pgn(json_input, output_f)
        output_f.seek(0)
        result = output_f.read()
        assert "1. e4 e5 2. Nf3" in result

    def test_headers_preserved(self):
        json_input = _make_input(_pgn_to_json_str(SIMPLE_PGN), "<test.json>")
        output_f = _make_output()
        json_to_pgn(json_input, output_f)
        output_f.seek(0)
        result = output_f.read()
        assert '[White "Alice"]' in result
        assert '[Black "Bob"]' in result
        assert '[Result "1-0"]' in result

    def test_result_preserved(self):
        json_input = _make_input(_pgn_to_json_str(SIMPLE_PGN), "<test.json>")
        output_f = _make_output()
        json_to_pgn(json_input, output_f)
        output_f.seek(0)
        # chess.pgn appends result token at the end of the move text
        assert "1-0" in output_f.read()

    def test_output_is_readable_pgn(self):
        """Round-trip: write PGN output then re-parse it with chess.pgn."""
        json_input = _make_input(_pgn_to_json_str(SIMPLE_PGN), "<test.json>")
        output_f = _make_output()
        json_to_pgn(json_input, output_f)
        output_f.seek(0)
        game = chess.pgn.read_game(output_f)
        assert game is not None
        assert game.headers["White"] == "Alice"

    def test_invalid_json_exits_with_error(self):
        output_f = _make_output()
        with pytest.raises(SystemExit) as exc_info:
            json_to_pgn(_make_input("not valid json", "<bad.json>"), output_f)
        assert exc_info.value.code == 1

    def test_status_messages_go_to_stderr(self, capsys):
        json_input = _make_input(_pgn_to_json_str(SIMPLE_PGN), "<test.json>")
        json_to_pgn(json_input, _make_output())
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "PGN" in captured.err


class TestInputFormatDetection:
    def test_pgn_extension_detected_as_pgn(self):
        f = _make_input("", "game.pgn")
        assert _detect_input_format(f, None) == "pgn"

    def test_json_extension_detected_as_json(self):
        f = _make_input("", "game.json")
        assert _detect_input_format(f, None) == "json"

    def test_stdin_defaults_to_pgn(self):
        f = _make_input("", "<stdin>")
        assert _detect_input_format(f, None) == "pgn"

    def test_unknown_extension_defaults_to_pgn(self):
        f = _make_input("", "game.txt")
        assert _detect_input_format(f, None) == "pgn"

    def test_override_takes_precedence_over_extension(self):
        f = _make_input("", "game.pgn")
        assert _detect_input_format(f, "json") == "json"

    def test_override_json_on_non_json_file(self):
        f = _make_input("", "data.txt")
        assert _detect_input_format(f, "json") == "json"
