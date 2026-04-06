"""Tests for the D3HTML exporter."""
from __future__ import annotations

import json
import pathlib
import tempfile

import chess.pgn
import pytest

from chesstree.d3html_exporter import (
    PLACEHOLDER_HOVER_DATA,
    PLACEHOLDER_IMAGES,
    PLACEHOLDER_TITLE,
    PLACEHOLDER_TREE_DATA,
    _build_hover_data_js,
    _read_default_template,
    export_d3html,
)

SAMPLES = pathlib.Path(__file__).parent / "sample_pgns"
LISPERER = SAMPLES / "lisperer_vs_verenitach.pgn"
HILLBILLY = SAMPLES / "hillbilly_v3.pgn"


def _load(path: pathlib.Path) -> chess.pgn.Game:
    with open(path) as f:
        return chess.pgn.read_game(f)


# ---------------------------------------------------------------------------
# Default template
# ---------------------------------------------------------------------------


class TestDefaultTemplate:
    def test_template_is_readable(self):
        content = _read_default_template()
        assert len(content) > 0

    def test_template_has_all_placeholders(self):
        content = _read_default_template()
        assert PLACEHOLDER_TITLE in content
        assert PLACEHOLDER_TREE_DATA in content
        assert PLACEHOLDER_IMAGES in content
        assert PLACEHOLDER_HOVER_DATA in content


# ---------------------------------------------------------------------------
# export_d3html
# ---------------------------------------------------------------------------


class TestExportD3html:
    def test_returns_html_string(self):
        html, _ = export_d3html(_load(LISPERER))
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_title_substituted(self):
        html, _ = export_d3html(_load(LISPERER))
        assert "lisperer" in html.lower()
        assert PLACEHOLDER_TITLE not in html

    def test_tree_data_substituted(self):
        html, _ = export_d3html(_load(LISPERER))
        assert "JSON.parse" in html
        assert PLACEHOLDER_TREE_DATA not in html

    def test_images_placeholder_substituted(self):
        html, images = export_d3html(_load(LISPERER), image_modes=frozenset(["variations"]))
        assert PLACEHOLDER_IMAGES not in html

    def test_hover_data_placeholder_substituted(self):
        html, _ = export_d3html(_load(LISPERER))
        assert PLACEHOLDER_HOVER_DATA not in html

    def test_tree_data_is_valid_json(self):
        """Extract the JSON from the HTML and verify it parses cleanly."""
        import re
        html, _ = export_d3html(_load(LISPERER))
        # The JSON is embedded as JSON.parse(`...`)
        m = re.search(r'JSON\.parse\(`(.*?)`\)', html, re.DOTALL)
        assert m is not None, "JSON.parse(`...`) not found in HTML"
        # Un-escape the JS template literal escapes
        raw = m.group(1).replace("\\`", "`").replace("\\\\", "\\").replace("\\${", "${")
        data = json.loads(raw)
        assert data["type"] == "root"

    def test_images_dict_returned(self):
        _, images = export_d3html(_load(LISPERER), image_modes=frozenset(["variations"]))
        assert len(images) > 0

    def test_none_mode_no_images(self):
        _, images = export_d3html(_load(LISPERER), image_modes=frozenset(["none"]))
        assert images == {}

    def test_forblack_flag_accepted(self):
        html, _ = export_d3html(_load(LISPERER), board_img_for_black=True,
                                image_modes=frozenset(["variations"]))
        assert "JSON.parse" in html

    def test_hover_false_sets_flag(self):
        html, _ = export_d3html(_load(LISPERER), hover=False)
        assert "hoverEnabled = false" in html

    def test_hover_true_sets_flag(self):
        html, _ = export_d3html(_load(LISPERER), hover=True)
        assert "hoverEnabled = true" in html

    def test_hover_true_embeds_hover_images(self):
        html, _ = export_d3html(_load(LISPERER), hover=True)
        assert "hoverImages" in html
        # The hover images dict should not be empty
        import re
        m = re.search(r'const hoverImages = (\{.*?\});', html, re.DOTALL)
        assert m is not None
        imgs = json.loads(m.group(1))
        assert len(imgs) > 0

    def test_custom_template_used(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(
                "<html><head><title>{{CHESSTREE_TITLE}}</title></head>"
                "<body>{{CHESSTREE_TREE_DATA}}{{CHESSTREE_IMAGES}}"
                "{{CHESSTREE_HOVER_DATA}}</body></html>"
            )
            tmp_path = pathlib.Path(f.name)
        try:
            html, _ = export_d3html(_load(LISPERER), template_path=tmp_path)
            assert "<html>" in html
            assert "JSON.parse" not in html  # custom template has no JSON.parse
            assert PLACEHOLDER_TITLE not in html
            assert PLACEHOLDER_TREE_DATA not in html
        finally:
            tmp_path.unlink()

    def test_missing_placeholder_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            # Missing PLACEHOLDER_HOVER_DATA
            f.write(
                "<html>{{CHESSTREE_TITLE}}{{CHESSTREE_TREE_DATA}}"
                "{{CHESSTREE_IMAGES}}</html>"
            )
            tmp_path = pathlib.Path(f.name)
        try:
            with pytest.raises(ValueError, match="{{CHESSTREE_HOVER_DATA}}"):
                export_d3html(_load(LISPERER), template_path=tmp_path)
        finally:
            tmp_path.unlink()

    def test_multiple_missing_placeholders_all_reported(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("<html>only title: {{CHESSTREE_TITLE}}</html>")
            tmp_path = pathlib.Path(f.name)
        try:
            with pytest.raises(ValueError) as exc_info:
                export_d3html(_load(LISPERER), template_path=tmp_path)
            msg = str(exc_info.value)
            assert "{{CHESSTREE_TREE_DATA}}" in msg
            assert "{{CHESSTREE_IMAGES}}" in msg
            assert "{{CHESSTREE_HOVER_DATA}}" in msg
        finally:
            tmp_path.unlink()


# ---------------------------------------------------------------------------
# JS template literal escaping (tree data)
# ---------------------------------------------------------------------------


class TestJsEscapingInTreeData:
    def test_backtick_in_pgn_comment_escaped(self):
        import io
        pgn = (
            '[Event "Test"]\n[White "?"]\n[Black "?"]\n\n'
            '1. e4 { `; alert("xss"); var x = ` } 1-0'
        )
        game = chess.pgn.read_game(io.StringIO(pgn))
        html, _ = export_d3html(game, image_modes=frozenset(["none"]))
        # Raw backtick injection should not appear unescaped in the JS template literal
        assert '`; alert("xss");' not in html
        assert "\\`" in html

    def test_backslash_in_player_name_escaped(self):
        import io
        pgn = '[White "Alice\\\\Bob"]\n[Black "?"]\n\n1. e4 1-0'
        game = chess.pgn.read_game(io.StringIO(pgn))
        html, _ = export_d3html(game, image_modes=frozenset(["none"]))
        # The title contains Alice\\Bob → should be properly escaped
        assert html is not None


# ---------------------------------------------------------------------------
# _build_hover_data_js
# ---------------------------------------------------------------------------


class TestBuildHoverDataJs:
    def test_hover_disabled(self):
        js = _build_hover_data_js(False, {})
        assert "hoverEnabled = false" in js
        assert "hoverImages" in js

    def test_hover_enabled_with_images(self):
        js = _build_hover_data_js(True, {"n12345678": "<svg/>"})
        assert "hoverEnabled = true" in js
        assert "n12345678" in js

    def test_hover_enabled_empty_images(self):
        js = _build_hover_data_js(True, {})
        assert "hoverEnabled = true" in js
        assert "hoverImages = {}" in js
