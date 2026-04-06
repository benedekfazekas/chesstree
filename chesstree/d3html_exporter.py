"""D3HTML exporter: wraps the D3 tree JSON in an interactive HTML template."""
from __future__ import annotations

import json as json_mod
import pathlib
from importlib.resources import files as _pkg_files
from typing import Optional

import chess.pgn

from chesstree.d3tree_exporter import export_d3tree
from chesstree.dothtml_exporter import _escape_js_template_literal, _game_title

PLACEHOLDER_TITLE = "{{CHESSTREE_TITLE}}"
PLACEHOLDER_TREE_DATA = "{{CHESSTREE_TREE_DATA}}"
PLACEHOLDER_IMAGES = "{{CHESSTREE_IMAGES}}"
PLACEHOLDER_HOVER_DATA = "{{CHESSTREE_HOVER_DATA}}"

_REQUIRED_PLACEHOLDERS = (
    PLACEHOLDER_TITLE,
    PLACEHOLDER_TREE_DATA,
    PLACEHOLDER_IMAGES,
    PLACEHOLDER_HOVER_DATA,
)


def _read_default_template() -> str:
    return (
        _pkg_files("chesstree.templates")
        .joinpath("d3html_default.html")
        .read_text(encoding="utf-8")
    )


def _build_hover_data_js(hover: bool, hover_images: dict[str, str]) -> str:
    """Build the JS snippet that sets hoverEnabled and hoverImages."""
    if not hover:
        return "const hoverEnabled = false;\nconst hoverImages = {};"
    safe = json_mod.dumps(hover_images)
    return f"const hoverEnabled = true;\nconst hoverImages = {safe};"


def export_d3html(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    template_path: Optional[pathlib.Path] = None,
    hover: bool = False,
    highlight_last_move: bool = True,
) -> tuple[str, dict[str, str]]:
    """Export a chess game to an interactive D3 HTML string.

    Returns ``(html_string, images)`` where ``images`` maps SVG filename to
    SVG content.  The caller is responsible for writing the SVG files alongside
    the HTML file so that the browser can load them.

    ``template_path`` overrides the built-in template.  The template must
    contain all four required placeholders:
    ``{{CHESSTREE_TITLE}}``, ``{{CHESSTREE_TREE_DATA}}``,
    ``{{CHESSTREE_IMAGES}}``, and ``{{CHESSTREE_HOVER_DATA}}``.
    """
    tree_dict, images, hover_images = export_d3tree(
        game,
        image_modes=image_modes,
        board_img_for_black=board_img_for_black,
        hover=hover,
        highlight_last_move=highlight_last_move,
    )

    if template_path is not None:
        template = template_path.read_text(encoding="utf-8")
        template_label = str(template_path)
    else:
        template = _read_default_template()
        template_label = "built-in d3html_default.html"

    missing = [p for p in _REQUIRED_PLACEHOLDERS if p not in template]
    if missing:
        raise ValueError(
            f"Template '{template_label}' is missing required placeholder(s): "
            + ", ".join(missing)
        )

    title = _game_title(game)
    tree_json = _escape_js_template_literal(json_mod.dumps(tree_dict))
    images_js = _build_images_js(images)
    hover_js = _build_hover_data_js(hover, hover_images)

    html = template
    html = html.replace(PLACEHOLDER_TITLE, title)
    html = html.replace(PLACEHOLDER_TREE_DATA, tree_json)
    html = html.replace(PLACEHOLDER_IMAGES, images_js)
    html = html.replace(PLACEHOLDER_HOVER_DATA, hover_js)

    return html, images


def _build_images_js(images: dict[str, str]) -> str:
    """Build a JS comment listing the image filenames (informational only).

    The D3 template loads images via <img> src attributes, not via an addImage
    call.  This placeholder is kept for template compatibility.
    """
    if not images:
        return "// no board images"
    names = ", ".join(f'"{n}"' for n in images)
    return f"// board images: [{names}]"
