from __future__ import annotations

import io
import json
import pathlib
import sys
import tempfile

import chess.engine
import chess.pgn
import pytest

import chesstree.cli
import chesstree.leaf_evaluator
from chesstree.cli import pgn_to_json, json_to_pgn, _detect_input_format, game_to_d3html, parse_args, pgn_to_pgn, _maybe_annotate_opening_end
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
        monkeypatch.setattr(chesstree.cli, "__version__", "2026.2.dev0")
        monkeypatch.setattr(sys, "argv", ["chesstree", "--version"])
        with pytest.raises(SystemExit):
            parse_args()
        captured = capsys.readouterr()
        assert captured.out.strip() == f"chesstree 2026.2.dev0 (schema {CURRENT_SCHEMA_VERSION})"


class TestAnnotateOpeningEndFlag:
    """Tests for --annotate-opening-end flag and the pgn→pgn passthrough."""

    def test_flag_default_false(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER)])
        args = parse_args()
        assert args.annotate_opening_end is False

    def test_flag_true_when_set(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER), "--annotate-opening-end"])
        args = parse_args()
        assert args.annotate_opening_end is True

    def test_maybe_annotate_noop_when_disabled(self):
        game = chess.pgn.read_game(io.StringIO(SIMPLE_PGN))
        assert game is not None
        _maybe_annotate_opening_end(game, enabled=False)
        node = game
        while not node.is_end():
            assert "[%opening_end]" not in node.comment
            node = node.variations[0]

    def test_maybe_annotate_noop_when_opening_never_ends(self):
        """Short game: divider returns None → helper leaves game untouched."""
        game = chess.pgn.read_game(io.StringIO(SIMPLE_PGN))
        assert game is not None
        _maybe_annotate_opening_end(game, enabled=True)
        result = str(game)
        assert "[%opening_end]" not in result

    # ── pgn → pgn ─────────────────────────────────────────────────────────────

    def test_pgn_to_pgn_annotates_at_correct_ply(self):
        """lisperer_vs_verenitach.pgn → divider fires at ply 27."""
        with open(LISPERER) as f:
            pgn_text = f.read()
        inp = _make_input(pgn_text, "lisperer.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_opening_end=True)
        output_f.seek(0)
        pgn_out = output_f.read()
        assert "[%opening_end]" in pgn_out
        game = chess.pgn.read_game(io.StringIO(pgn_out))
        assert game is not None
        node = game
        for _ in range(27):
            node = node.variations[0]
        assert "[%opening_end]" in node.comment
        assert "[%opening_end]" not in node.parent.comment  # type: ignore[union-attr]

    def test_pgn_to_pgn_no_annotation_when_flag_off(self):
        with open(LISPERER) as f:
            pgn_text = f.read()
        inp = _make_input(pgn_text, "lisperer.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_opening_end=False)
        output_f.seek(0)
        assert "[%opening_end]" not in output_f.read()

    def test_pgn_to_pgn_noop_for_short_game(self):
        """Short game: divider returns None → no annotation written."""
        inp = _make_input(SIMPLE_PGN, "simple.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_opening_end=True)
        output_f.seek(0)
        assert "[%opening_end]" not in output_f.read()

    def test_pgn_to_pgn_preserves_game_structure(self):
        """Output is valid PGN that round-trips back to a parsed game."""
        with open(LISPERER) as f:
            pgn_text = f.read()
        inp = _make_input(pgn_text, "lisperer.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_opening_end=True)
        output_f.seek(0)
        game = chess.pgn.read_game(output_f)
        assert game is not None

    def test_pgn_to_pgn_empty_pgn_exits(self):
        output_f = _make_output()
        with pytest.raises(SystemExit) as exc_info:
            pgn_to_pgn(_make_input("", "empty.pgn"), output_f)
        assert exc_info.value.code == 1

    # ── json → pgn ────────────────────────────────────────────────────────────

    def test_json_to_pgn_with_annotation(self):
        """Annotation flows through json→pgn path."""
        with open(LISPERER) as f:
            pgn_text = f.read()
        json_str = _pgn_to_json_str(pgn_text)
        inp = _make_input(json_str, "lisperer.json")
        output_f = _make_output()
        json_to_pgn(inp, output_f, annotate_opening_end=True)
        output_f.seek(0)
        pgn_out = output_f.read()
        assert "[%opening_end]" in pgn_out

    def test_json_to_pgn_no_annotation_when_flag_off(self):
        json_str = _pgn_to_json_str(SIMPLE_PGN)
        inp = _make_input(json_str, "simple.json")
        output_f = _make_output()
        json_to_pgn(inp, output_f, annotate_opening_end=False)
        output_f.seek(0)
        assert "[%opening_end]" not in output_f.read()

    # ── pgn → d3html ──────────────────────────────────────────────────────────

    def test_pgn_to_d3html_with_annotation_produces_valid_html(self):
        """Flag threads through game_to_d3html without error.

        [%opening_end] is a command annotation; it is stripped from d3html rendered
        text by has_real_comment, so we assert the output is valid HTML rather than
        scanning for the literal string.
        """
        with open(LISPERER) as f:
            pgn_text = f.read()
        inp = _make_input(pgn_text, "lisperer.pgn")
        output_f = _make_output()
        game_to_d3html(inp, output_f, "pgn", images=["none"], annotate_opening_end=True)
        output_f.seek(0)
        html = output_f.read()
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_pgn_to_d3html_annotation_applied_to_game_object(self):
        """_maybe_annotate_opening_end annotates the game object at ply 27."""
        import chess.pgn as pgn_mod
        with open(LISPERER) as f:
            game = pgn_mod.read_game(f)
        assert game is not None
        _maybe_annotate_opening_end(game, enabled=True)
        node = game
        for _ in range(27):
            node = node.variations[0]
        assert "[%opening_end]" in node.comment


# ── PGN with variations for eval tests ──────────────────────────────────────

VARIED_PGN = """\
[Event "Test"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 (1... c5 2. Nf3) 2. Nf3 Nc6 *
"""


def _make_stub_provider(cp: int = 30) -> tuple:
    """Return (stub_provider, closer, calls) where calls records invocations."""
    calls: list[chess.Board] = []

    def stub_provider(board: chess.Board) -> chess.engine.PovScore:
        calls.append(board)
        return chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE)

    return stub_provider, calls


class TestAnnotateEvalFlag:
    """Tests for --annotate-eval and related flags."""

    # ── parse_args defaults ──────────────────────────────────────────────────

    def test_annotate_eval_default_false(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER)])
        args = parse_args()
        assert args.annotate_eval is False

    def test_eval_scope_default_branch_points(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER)])
        args = parse_args()
        assert args.eval_scope == "branch-points"

    def test_engine_default_stockfish(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER)])
        args = parse_args()
        assert args.engine == "stockfish"

    def test_eval_depth_default_none(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER)])
        args = parse_args()
        assert args.eval_depth is None

    def test_eval_time_default_none(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER)])
        args = parse_args()
        assert args.eval_time is None

    def test_annotate_eval_flag_parsed(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER), "--annotate-eval"])
        args = parse_args()
        assert args.annotate_eval is True

    def test_eval_scope_choices_parsed(self, monkeypatch):
        for scope in ("leaves", "branch-points", "all"):
            monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER), "--eval-scope", scope])
            args = parse_args()
            assert args.eval_scope == scope

    def test_eval_depth_parsed(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER), "--eval-depth", "15"])
        args = parse_args()
        assert args.eval_depth == 15

    def test_eval_time_parsed(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER), "--eval-time", "0.5"])
        args = parse_args()
        assert args.eval_time == 0.5

    def test_engine_path_parsed(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["chesstree", "-i", str(LISPERER), "--engine", "/usr/bin/stockfish"])
        args = parse_args()
        assert args.engine == "/usr/bin/stockfish"

    # ── stub provider annotates ──────────────────────────────────────────────

    def test_pgn_to_pgn_annotates_with_stub_provider(self, monkeypatch):
        """pgn→pgn with annotate_eval=True writes [%eval ...] via stub provider."""
        closer_called: list[bool] = []
        stub_provider, _ = _make_stub_provider(cp=30)

        def fake_make_engine_provider(engine_path, limit):
            def recording_closer():
                closer_called.append(True)
            return stub_provider, recording_closer

        monkeypatch.setattr(chesstree.cli.leaf_evaluator, "make_engine_provider", fake_make_engine_provider)

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True, eval_scope="branch-points")
        output_f.seek(0)
        pgn_out = output_f.read()

        assert "[%eval 0.30]" in pgn_out
        assert closer_called, "closer must be called after annotation"

    def test_pgn_to_pgn_annotates_all_scope(self, monkeypatch):
        """scope=all annotates every node including mainline moves."""
        stub_provider, calls = _make_stub_provider(cp=15)

        monkeypatch.setattr(
            chesstree.cli.leaf_evaluator, "make_engine_provider",
            lambda engine_path, limit: (stub_provider, lambda: None),
        )

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True, eval_scope="all")
        output_f.seek(0)
        pgn_out = output_f.read()

        assert "[%eval 0.15]" in pgn_out
        # multiple positions should be annotated
        assert pgn_out.count("[%eval") > 1

    # ── engine unavailable path ──────────────────────────────────────────────

    def test_engine_unavailable_warns_and_continues(self, monkeypatch, capsys):
        """EngineUnavailable → warning on stderr, output produced, no crash."""
        def raise_unavailable(engine_path, limit):
            raise chesstree.leaf_evaluator.EngineUnavailable("no engine found")

        monkeypatch.setattr(chesstree.cli.leaf_evaluator, "make_engine_provider", raise_unavailable)

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True)

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "no engine found" in captured.err

        output_f.seek(0)
        pgn_out = output_f.read()
        assert "1. e4" in pgn_out
        assert "[%eval" not in pgn_out

    def test_engine_unavailable_continuing_message(self, monkeypatch, capsys):
        """Second warning line says 'continuing without eval annotation'."""
        monkeypatch.setattr(
            chesstree.cli.leaf_evaluator, "make_engine_provider",
            lambda p, l: (_ for _ in ()).throw(chesstree.leaf_evaluator.EngineUnavailable("oops")),
        )

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True)

        captured = capsys.readouterr()
        assert "continuing without eval annotation" in captured.err

    # ── annotate_eval=False does NOT call make_engine_provider ───────────────

    def test_no_eval_flag_does_not_call_provider(self, monkeypatch):
        """When annotate_eval=False (default), make_engine_provider must not be called."""
        def must_not_be_called(engine_path, limit):
            raise AssertionError("make_engine_provider must NOT be called when annotate_eval=False")

        monkeypatch.setattr(chesstree.cli.leaf_evaluator, "make_engine_provider", must_not_be_called)

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=False)
        output_f.seek(0)
        assert "1. e4" in output_f.read()

    # ── limit construction ───────────────────────────────────────────────────

    def test_eval_time_takes_precedence_over_depth(self, monkeypatch):
        """When both eval_time and eval_depth given, time limit is used."""
        received_limits: list = []

        def capture_limit(engine_path, limit):
            received_limits.append(limit)
            stub_provider, _ = _make_stub_provider()
            return stub_provider, lambda: None

        monkeypatch.setattr(chesstree.cli.leaf_evaluator, "make_engine_provider", capture_limit)

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True, eval_time=0.5, eval_depth=10)

        assert len(received_limits) == 1
        lim = received_limits[0]
        assert lim.time == 0.5
        assert lim.depth is None

    def test_eval_depth_used_when_no_time(self, monkeypatch):
        received_limits: list = []

        def capture_limit(engine_path, limit):
            received_limits.append(limit)
            stub_provider, _ = _make_stub_provider()
            return stub_provider, lambda: None

        monkeypatch.setattr(chesstree.cli.leaf_evaluator, "make_engine_provider", capture_limit)

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True, eval_depth=10)

        assert len(received_limits) == 1
        lim = received_limits[0]
        assert lim.depth == 10
        assert lim.time is None

    def test_no_limit_args_passes_none(self, monkeypatch):
        """Neither depth nor time → None limit passed to make_engine_provider."""
        received_limits: list = []

        def capture_limit(engine_path, limit):
            received_limits.append(limit)
            stub_provider, _ = _make_stub_provider()
            return stub_provider, lambda: None

        monkeypatch.setattr(chesstree.cli.leaf_evaluator, "make_engine_provider", capture_limit)

        inp = _make_input(VARIED_PGN, "game.pgn")
        output_f = _make_output()
        pgn_to_pgn(inp, output_f, annotate_eval=True)

        assert received_limits[0] is None
