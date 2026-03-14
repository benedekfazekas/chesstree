"""Tests for the dothtml exporter."""
from __future__ import annotations

import pathlib
import tempfile

import chess.pgn
import pytest

from chesstree.dothtml_exporter import (
    PLACEHOLDER_DOT,
    PLACEHOLDER_IMAGES,
    PLACEHOLDER_TITLE,
    _build_add_images,
    _escape_js_template_literal,
    _game_title,
    _read_default_template,
    export_dothtml,
)

SAMPLES = pathlib.Path(__file__).parent / "sample_pgns"
LISPERER = SAMPLES / "lisperer_vs_verenitach.pgn"
HILLBILLY = SAMPLES / "hillbilly_v3.pgn"


def _load(path: pathlib.Path) -> chess.pgn.Game:
    with open(path) as f:
        return chess.pgn.read_game(f)


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestGameTitle:
    def test_real_game_with_players(self):
        game = _load(LISPERER)
        title = _game_title(game)
        assert "lisperer" in title.lower()
        assert "verenitach" in title.lower()

    def test_study_uses_event(self):
        game = _load(HILLBILLY)
        title = _game_title(game)
        assert len(title) > 0

    def test_includes_date(self):
        title = _game_title(_load(LISPERER))
        # some date-like string should be present
        assert "at" in title


class TestBuildAddImages:
    def test_empty_dict(self):
        assert _build_add_images({}) == ""

    def test_single_image(self):
        result = _build_add_images({"n1a2b3c4.svg": "<svg/>"})
        assert '.addImage("./n1a2b3c4.svg", "144px", "144px")' in result

    def test_multiple_images_all_present(self):
        images = {"na.svg": "<svg/>", "nb.svg": "<svg/>", "nc.svg": "<svg/>"}
        result = _build_add_images(images)
        assert result.count(".addImage") == 3
        for name in images:
            assert f'"./{name}"' in result


# ---------------------------------------------------------------------------
# Default template: placeholder presence
# ---------------------------------------------------------------------------


class TestDefaultTemplate:
    def test_template_is_readable(self):
        content = _read_default_template()
        assert len(content) > 0

    def test_template_has_all_placeholders(self):
        content = _read_default_template()
        assert PLACEHOLDER_TITLE in content
        assert PLACEHOLDER_IMAGES in content
        assert PLACEHOLDER_DOT in content


# ---------------------------------------------------------------------------
# export_dothtml
# ---------------------------------------------------------------------------


class TestExportDothtml:
    def test_returns_html_string(self):
        html, _ = export_dothtml(_load(LISPERER))
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_title_substituted(self):
        html, _ = export_dothtml(_load(LISPERER))
        assert "lisperer" in html.lower()
        assert PLACEHOLDER_TITLE not in html

    def test_dot_substituted(self):
        html, _ = export_dothtml(_load(LISPERER))
        assert "digraph {" in html
        assert PLACEHOLDER_DOT not in html

    def test_images_substituted(self):
        html, images = export_dothtml(_load(LISPERER), image_modes=frozenset(["variations"]))
        assert PLACEHOLDER_IMAGES not in html
        for filename in images:
            assert filename in html

    def test_none_mode_no_add_image_calls(self):
        html, images = export_dothtml(_load(LISPERER), image_modes=frozenset(["none"]))
        assert images == {}
        assert ".addImage(" not in html

    def test_variations_mode_has_add_image_calls(self):
        html, images = export_dothtml(_load(LISPERER), image_modes=frozenset(["variations"]))
        assert len(images) > 0
        assert ".addImage(" in html

    def test_images_dict_matches_add_image_references(self):
        html, images = export_dothtml(_load(LISPERER), image_modes=frozenset(["all"]))
        for filename in images:
            assert filename in html

    def test_custom_template_used(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(
                "<html><head><title>{{CHESSTREE_TITLE}}</title></head>"
                "<body>{{CHESSTREE_IMAGES}}{{CHESSTREE_DOT}}</body></html>"
            )
            tmp_path = pathlib.Path(f.name)
        try:
            html, _ = export_dothtml(_load(LISPERER), template_path=tmp_path)
            assert "<html>" in html
            assert "digraph {" in html
            assert PLACEHOLDER_TITLE not in html
        finally:
            tmp_path.unlink()

    def test_missing_placeholder_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            # Missing {{CHESSTREE_DOT}}
            f.write("<html>{{CHESSTREE_TITLE}}{{CHESSTREE_IMAGES}}</html>")
            tmp_path = pathlib.Path(f.name)
        try:
            with pytest.raises(ValueError, match="{{CHESSTREE_DOT}}"):
                export_dothtml(_load(LISPERER), template_path=tmp_path)
        finally:
            tmp_path.unlink()

    def test_multiple_missing_placeholders_all_reported(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html>only title: {{CHESSTREE_TITLE}}</html>")
            tmp_path = pathlib.Path(f.name)
        try:
            with pytest.raises(ValueError) as exc_info:
                export_dothtml(_load(LISPERER), template_path=tmp_path)
            msg = str(exc_info.value)
            assert "{{CHESSTREE_IMAGES}}" in msg
            assert "{{CHESSTREE_DOT}}" in msg
        finally:
            tmp_path.unlink()

    def test_forblack_flag_accepted(self):
        html, _ = export_dothtml(_load(LISPERER), board_img_for_black=True,
                                 image_modes=frozenset(["variations"]))
        assert "digraph {" in html


# ---------------------------------------------------------------------------
# JS template literal escaping
# ---------------------------------------------------------------------------


class TestEscapeJsTemplateLiteral:
    def test_backtick_escaped(self):
        assert _escape_js_template_literal("a`b") == "a\\`b"

    def test_backslash_escaped(self):
        assert _escape_js_template_literal("a\\b") == "a\\\\b"

    def test_template_expression_escaped(self):
        assert _escape_js_template_literal("${evil}") == "\\${evil}"

    def test_backslash_before_backtick_no_double_escape(self):
        # a\`b → a\\`b (backslash escaped first, then backtick)
        assert _escape_js_template_literal("a\\`b") == "a\\\\\\`b"

    def test_plain_text_unchanged(self):
        assert _escape_js_template_literal("hello world") == "hello world"

    def test_empty_string(self):
        assert _escape_js_template_literal("") == ""

    def test_dot_string_injected_safely(self):
        """A crafted DOT string with backticks cannot break out of the JS literal."""
        import io
        import chess.pgn
        # Craft a PGN with a comment that tries to break out of a JS backtick string
        pgn = (
            '[Event "Test"]\n[White "?"]\n[Black "?"]\n\n'
            '1. e4 { `; alert("xss"); var x = ` } 1-0'
        )
        game = chess.pgn.read_game(io.StringIO(pgn))
        html, _ = export_dothtml(game, image_modes=frozenset(["none"]))
        # The raw injection sequence must not appear unescaped
        assert '`; alert("xss"); var x = `' not in html
        # But the escaped version should be present
        assert "\\`" in html
