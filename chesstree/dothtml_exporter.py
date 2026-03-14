from __future__ import annotations

import pathlib
from typing import Optional

import chess.pgn

from chesstree.dot_exporter import export_dot

_DEFAULT_TEMPLATE = pathlib.Path(__file__).parent / "templates" / "dothtml_default.html"

PLACEHOLDER_TITLE = "{{CHESSTREE_TITLE}}"
PLACEHOLDER_IMAGES = "{{CHESSTREE_IMAGES}}"
PLACEHOLDER_DOT = "{{CHESSTREE_DOT}}"

_REQUIRED_PLACEHOLDERS = (PLACEHOLDER_TITLE, PLACEHOLDER_IMAGES, PLACEHOLDER_DOT)


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


def export_dothtml(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    template_path: Optional[pathlib.Path] = None,
) -> tuple[str, dict[str, str]]:
    """Export a chess game to a self-contained d3-graphviz HTML string.

    Returns ``(html_string, images)`` where ``images`` maps SVG filename to
    SVG content.  The caller is responsible for writing the SVG files alongside
    the HTML file so that the browser can load them.

    ``template_path`` overrides the built-in template.  The template must
    contain the placeholders ``{{CHESSTREE_TITLE}}``, ``{{CHESSTREE_IMAGES}}``,
    and ``{{CHESSTREE_DOT}}``.
    """
    dot_str, images = export_dot(game, image_modes=image_modes, board_img_for_black=board_img_for_black)

    path = template_path or _DEFAULT_TEMPLATE
    template = path.read_text(encoding="utf-8")

    missing = [p for p in _REQUIRED_PLACEHOLDERS if p not in template]
    if missing:
        raise ValueError(
            f"Template {path} is missing required placeholder(s): {', '.join(missing)}"
        )

    title = _game_title(game)
    add_images = _build_add_images(images)

    html = template
    html = html.replace(PLACEHOLDER_TITLE, title)
    html = html.replace(PLACEHOLDER_IMAGES, add_images)
    html = html.replace(PLACEHOLDER_DOT, dot_str)

    return html, images
