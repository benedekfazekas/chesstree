from __future__ import annotations

import io
import json
import pathlib
import sys
import tempfile

import chess.pgn
import pytest

import chesstree.cli
from chesstree.cli import pgn_to_json, json_to_pgn, _detect_input_format, game_to_d3html, parse_args
from chesstree.json_exporter import JsonExporter
from chesstree.utils import CURRENT_SCHEMA_VERSION

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
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, edn=False)
        output_f.seek(0)
        data = json.loads(output_f.read())
        assert data["headers"]["White"] == "Alice"
        assert data["result"] == "1-0"

    def test_edn_output(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, edn=True)
        output_f.seek(0)
        result = output_f.read()
        assert ":headers" in result
        assert ":moves" in result

    def test_concise_output(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, edn=False, concise=True)
        output_f.seek(0)
        # Trim trailing newlines added by print(..., end="\n\n")
        result = output_f.read().strip()
        assert "\n" not in result

    def test_forblack_flag_accepted(self):
        """Smoke test: pgn_to_json no longer accepts forblack; this test
        verifies the basic conversion still works."""
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, edn=False)
        output_f.seek(0)
        data = json.loads(output_f.read())
        assert len(data["moves"]) > 0

    def test_empty_pgn_exits_with_error(self):
        output_f = _make_output()
        with pytest.raises(SystemExit) as exc_info:
            pgn_to_json(_make_input(EMPTY_PGN), output_f, edn=False)
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

SAMPLES = pathlib.Path(__file__).parent / "sample_pgns"
LISPERER = SAMPLES / "lisperer_vs_verenitach.pgn"


class TestGameToD3html:
    def test_d3html_produces_html(self):
        output_f = _make_output()
        game_to_d3html(_make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn")
        output_f.seek(0)
        html = output_f.read()
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_d3html_title_in_output(self):
        output_f = _make_output()
        game_to_d3html(_make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn")
        output_f.seek(0)
        html = output_f.read()
        assert "Alice" in html

    def test_d3html_tree_data_embedded(self):
        output_f = _make_output()
        game_to_d3html(_make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn")
        output_f.seek(0)
        html = output_f.read()
        assert "JSON.parse" in html

    def test_d3html_hover_disabled_by_default(self):
        output_f = _make_output()
        game_to_d3html(_make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn")
        output_f.seek(0)
        html = output_f.read()
        assert "hoverEnabled = false" in html

    def test_d3html_hover_enabled(self):
        output_f = _make_output()
        game_to_d3html(_make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn", hover=True)
        output_f.seek(0)
        html = output_f.read()
        assert "hoverEnabled = true" in html

    def test_d3html_none_images_mode(self):
        output_f = _make_output()
        game_to_d3html(
            _make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn",
            images=["none"],
        )
        output_f.seek(0)
        html = output_f.read()
        assert "<!DOCTYPE html>" in html

    def test_d3html_svg_files_written_to_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = pathlib.Path(tmpdir) / "game.html"
            with open(html_path, "w") as out_f:
                game_to_d3html(
                    _make_input(SIMPLE_PGN, "game.pgn"), out_f, "pgn",
                    images=["all"],
                )
            svg_files = list(pathlib.Path(tmpdir).glob("*.svg"))
            assert len(svg_files) > 0

    def test_d3html_no_svg_on_stdout(self):
        output_f = _make_output()  # name = "<stdout>"
        game_to_d3html(
            _make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn",
            images=["all"],
        )
        # No SVG files should be written; just verify no error

    def test_d3html_custom_template(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(
                "<html><body>{{CHESSTREE_TITLE}}"
                "{{CHESSTREE_TREE_DATA}}{{CHESSTREE_IMAGES}}"
                "{{CHESSTREE_HOVER_DATA}}</body></html>"
            )
            tmp_path = pathlib.Path(f.name)
        try:
            output_f = _make_output()
            template_f = open(tmp_path)
            game_to_d3html(
                _make_input(SIMPLE_PGN, "game.pgn"), output_f, "pgn",
                template_file=template_f,
            )
            template_f.close()
            output_f.seek(0)
            html = output_f.read()
            assert "Alice" in html
        finally:
            tmp_path.unlink()

    def test_d3html_empty_pgn_exits(self):
        output_f = _make_output()
        with pytest.raises(SystemExit) as exc_info:
            game_to_d3html(_make_input("", "game.pgn"), output_f, "pgn")
        assert exc_info.value.code == 1


class TestVersionOutput:
    def test_version_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["chesstree", "--version"])
        with pytest.raises(SystemExit) as exc_info:
            parse_args()
        assert exc_info.value.code == 0

    def test_version_contains_program_name(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["chesstree", "--version"])
        with pytest.raises(SystemExit):
            parse_args()
        captured = capsys.readouterr()
        assert "chesstree" in captured.out
        assert captured.err == ""

    def test_version_contains_schema_version(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["chesstree", "--version"])
        with pytest.raises(SystemExit):
            parse_args()
        captured = capsys.readouterr()
        assert f"schema {CURRENT_SCHEMA_VERSION}" in captured.out

    def test_version_format(self, monkeypatch, capsys):
        monkeypatch.setattr(chesstree.cli, "__version__", "2026.1")
        monkeypatch.setattr(sys, "argv", ["chesstree", "--version"])
        with pytest.raises(SystemExit):
            parse_args()
        captured = capsys.readouterr()
        assert captured.out.strip() == f"chesstree 2026.1 (schema {CURRENT_SCHEMA_VERSION})"
