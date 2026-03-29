from __future__ import annotations

import json as _json
import pathlib
from importlib.resources import files as _pkg_files
from typing import Optional

import chess.pgn

from chesstree.dot_exporter import export_dot

PLACEHOLDER_TITLE = "{{CHESSTREE_TITLE}}"
PLACEHOLDER_IMAGES = "{{CHESSTREE_IMAGES}}"
PLACEHOLDER_DOT = "{{CHESSTREE_DOT}}"
PLACEHOLDER_HOVER_DATA = "{{CHESSTREE_HOVER_DATA}}"

_REQUIRED_PLACEHOLDERS = (PLACEHOLDER_TITLE, PLACEHOLDER_IMAGES, PLACEHOLDER_DOT, PLACEHOLDER_HOVER_DATA)


def _read_default_template() -> str:
    """Read the built-in template using importlib.resources (works when installed)."""
    return (
        _pkg_files("chesstree.templates")
        .joinpath("dothtml_default.html")
        .read_text(encoding="utf-8")
    )


def _game_title(game: chess.pgn.Game) -> str:
    """Derive a human-readable title from game headers."""
    headers = game.headers
    white = headers.get("White")
    black = headers.get("Black")
    date = headers.get("UTCDate") or headers.get("Date") or "unknown date"
    if white and black and white != "?" and black != "?":
        return f"{white} vs {black} at {date}"
    event = headers.get("Event", "?")
    return f"{event} at {date}"


def _build_add_images(images: dict[str, str]) -> str:
    """Build the .addImage(...) chain lines for the template."""
    if not images:
        return ""
    lines = [
        f'.addImage("./{filename}", "144px", "144px")'
        for filename in images
    ]
    # Indent to align under the graphviz call in the template
    indent = "        "
    return ("\n" + indent).join(lines)


def _build_hover_data(hover_images: dict[str, str], enabled: bool) -> str:
    """Build the JS hover data block for the template placeholder.

    When ``enabled`` is ``True`` and ``hover_images`` is non-empty, emits a
    populated ``hoverImages`` dict and sets ``hoverEnabled = true``.
    When disabled, emits an empty dict and ``hoverEnabled = false`` so the
    template's hover handler is a no-op without any further branching.

    SVG content is JSON-encoded to safely embed arbitrary SVG in a JS object
    literal without any escaping edge-cases.
    """
    flag = "true" if enabled else "false"
    images_json = _json.dumps(hover_images if enabled else {})
    return f"const hoverEnabled = {flag};\nconst hoverImages = {images_json};"


def export_dothtml(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    template_path: Optional[pathlib.Path] = None,
    hover: bool = False,
) -> tuple[str, dict[str, str]]:
    """Export a chess game to a self-contained d3-graphviz HTML string.

    Returns ``(html_string, images)`` where ``images`` maps SVG filename to
    SVG content.  The caller is responsible for writing the SVG files alongside
    the HTML file so that the browser can load them.

    When ``hover=True``, every individual move in the graph becomes a
    clickable/hoverable cell.  Mousing over a move shows a floating board
    image popup.  The hover SVG data is inlined in the HTML; no extra files
    are written for hover images.

    ``template_path`` overrides the built-in template.  The template must
    contain the placeholders ``{{CHESSTREE_TITLE}}``, ``{{CHESSTREE_IMAGES}}``,
    ``{{CHESSTREE_DOT}}``, and ``{{CHESSTREE_HOVER_DATA}}``.
    """
    dot_str, images, hover_images = export_dot(
        game,
        image_modes=image_modes,
        board_img_for_black=board_img_for_black,
        hover=hover,
    )

    if template_path is not None:
        template = template_path.read_text(encoding="utf-8")
        template_label = str(template_path)
    else:
        template = _read_default_template()
        template_label = "built-in dothtml_default.html"

    missing = [p for p in _REQUIRED_PLACEHOLDERS if p not in template]
    if missing:
        raise ValueError(
            f"Template '{template_label}' is missing required placeholder(s): {', '.join(missing)}"
        )

    title = _game_title(game)
    add_images = _build_add_images(images)
    safe_dot = _escape_js_template_literal(dot_str)
    hover_data = _build_hover_data(hover_images, enabled=hover)

    html = template
    html = html.replace(PLACEHOLDER_TITLE, title)
    html = html.replace(PLACEHOLDER_IMAGES, add_images)
    html = html.replace(PLACEHOLDER_DOT, safe_dot)
    html = html.replace(PLACEHOLDER_HOVER_DATA, hover_data)

    return html, images


def _escape_js_template_literal(s: str) -> str:
    """Escape a string for safe embedding inside a JS backtick template literal.

    Prevents content in the DOT string (e.g. from PGN comments or player names)
    from breaking out of the ``var dot = `...`;`` block and injecting JS.

    Escape order: backslash first (to avoid double-escaping), then backtick,
    then ``${`` (template expression opener).
    """
    s = s.replace("\\", "\\\\")
    s = s.replace("`", "\\`")
    s = s.replace("${", "\\${")
    return s
