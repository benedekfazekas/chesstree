"""D3 tree exporter: converts a chess game to a JSON tree structure for D3 rendering."""
from __future__ import annotations

from typing import Optional

import chess
import chess.pgn
import chess.svg

from chesstree.utils import (
    NAG_TO_PGN_STRING,
    _PGN_COMMAND_ANNOTATION_RE,
    _ASSESSMENT_NAGS_PRIORITY,
    _nag_symbol,
    _node_id,
    _last_move_fill,
)

from chess.pgn import (
    NAG_BLUNDER,
    NAG_BRILLIANT_MOVE,
    NAG_DUBIOUS_MOVE,
    NAG_GOOD_MOVE,
    NAG_MISTAKE,
    NAG_SPECULATIVE_MOVE,
)

_NAG_CSS_CLASSES: dict[int, str] = {
    NAG_BLUNDER: "nag-blunder",
    NAG_MISTAKE: "nag-mistake",
    NAG_DUBIOUS_MOVE: "nag-dubious",
    NAG_SPECULATIVE_MOVE: "nag-speculative",
    NAG_GOOD_MOVE: "nag-good",
    NAG_BRILLIANT_MOVE: "nag-brilliant",
}


def _nag_class(node: chess.pgn.ChildNode) -> Optional[str]:
    for nag in _ASSESSMENT_NAGS_PRIORITY:
        if nag in node.nags:
            return _NAG_CSS_CLASSES[nag]
    return None


def _format_move_num(node: chess.pgn.ChildNode) -> str:
    num = node.parent.board().fullmove_number
    is_white = node.parent.board().turn == chess.WHITE
    return f"{num}." if is_white else f"{num}\u2026"


def _wrap_text(text: str, width: int = 32) -> list[str]:
    """Wrap text at word boundaries, returning a list of line strings."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).lstrip()
        if current and len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _format_edge_label(node: chess.pgn.ChildNode) -> dict:
    """Return a structured edge label dict with move, NAG class, and comments.

    Comments are pre-wrapped into lines for direct rendering in the template.
    """
    num = node.parent.board().fullmove_number
    is_white = node.parent.board().turn == chess.WHITE
    san = node.parent.board().san(node.move)
    nag = _nag_symbol(node)
    nag_cls = _nag_class(node)
    move_text = f"{num}. {san}{nag}" if is_white else f"{num}\u2026 {san}{nag}"

    starting_comment = _PGN_COMMAND_ANNOTATION_RE.sub("", node.starting_comment or "").strip()
    comment = _PGN_COMMAND_ANNOTATION_RE.sub("", node.comment or "").strip()

    return {
        "move": move_text,
        "nagClass": nag_cls,
        "startingComment": _wrap_text(starting_comment) if starting_comment else None,
        "comment": _wrap_text(comment) if comment else None,
    }


class _D3TreeBuilder:
    """Builds a JSON tree from a chess game for D3 rendering."""

    def __init__(
        self,
        game: chess.pgn.Game,
        image_modes: frozenset[str] = frozenset(["variations"]),
        board_img_for_black: bool = False,
        hover: bool = False,
        highlight_last_move: bool = True,
    ) -> None:
        self.game = game
        self.image_modes = image_modes
        self.orientation = chess.BLACK if board_img_for_black else chess.WHITE
        self.hover = hover
        self.highlight_last_move = highlight_last_move
        self._images: dict[str, str] = {}
        self._hover_images: dict[str, str] = {}

    def build(self) -> tuple[dict, dict[str, str], dict[str, str]]:
        headers = self.game.headers
        white = headers.get("White")
        black = headers.get("Black")
        raw_date = headers.get("UTCDate") or headers.get("Date") or None
        date = raw_date if raw_date and "?" not in raw_date else None

        if white and black and white != "?" and black != "?":
            title = f"{white} vs {black} at {date}" if date else f"{white} vs {black}"
        else:
            event = headers.get("Event", "?")
            title = f"{event} at {date}" if date else event

        game_comment = _PGN_COMMAND_ANNOTATION_RE.sub("", self.game.comment or "").strip()

        root = {
            "type": "root",
            "title": title,
            "headers": {
                k: v
                for k, v in headers.items()
                if k not in ("FEN", "SetUp")
            },
            "gameComment": game_comment or None,
            "children": [],
        }

        if self.game.variations:
            main_segments = self._collect_main_segments_flat(self.game.variations[0])
            root["children"].extend(main_segments)
            for alt in self.game.variations[1:]:
                root["children"].append(
                    self._build_variation_segment(
                        alt, is_variation=True, edge_label=_format_edge_label(alt)
                    )
                )

        return root, self._images, self._hover_images

    def _collect_main_segments_flat(
        self,
        start: chess.pgn.ChildNode,
    ) -> list[dict]:
        """Collect all main-line segments as a flat list, each with their own
        variation children but without chaining to the next main-line segment.

        This mirrors DOT's ``_collect_main_segments`` traversal but returns a
        flat list so that all main-line segments become direct children of the
        root node in the tree, rather than being nested one inside the next.
        """
        segments: list[dict] = []
        current_start: Optional[chess.pgn.ChildNode] = start

        while current_start is not None:
            block: list[chess.pgn.ChildNode] = []
            branch_alternatives: list[chess.pgn.ChildNode] = []
            next_continuation: Optional[chess.pgn.ChildNode] = None
            current: Optional[chess.pgn.ChildNode] = current_start

            while current is not None:
                block.append(current)
                n_vars = len(current.variations)
                if n_vars == 0:
                    break
                elif n_vars > 1:
                    branch_alternatives = list(current.variations[1:])
                    branching_move = current.variations[0]
                    block.append(branching_move)
                    if branching_move.variations:
                        next_continuation = branching_move.variations[0]
                    break
                else:
                    current = current.variations[0]

            moves = self._build_moves(block)
            self._populate_move_images(block, moves)
            hover_fens = self._build_hover_fens(block)

            segment: dict = {
                "type": "segment",
                "isVariation": False,
                "isMainLine": True,
                "edgeLabel": None,
                "moves": moves,
                "hoverFens": hover_fens,
                "children": [],
            }

            for alt in branch_alternatives:
                segment["children"].append(
                    self._build_variation_segment(
                        alt, is_variation=True, edge_label=_format_edge_label(alt)
                    )
                )

            segments.append(segment)
            current_start = next_continuation

        return segments

    def _build_variation_segment(
        self,
        start: chess.pgn.ChildNode,
        is_variation: bool,
        edge_label: Optional[str],
    ) -> dict:
        """Variation segment: collects ALL moves until the line ends.

        Follows ``variations[0]`` past sub-branch points, noting the
        alternatives (``variations[1:]``) as children.  Mirrors DOT's
        ``_collect_variation_moves`` behaviour.  Never splits at comments.
        """
        block: list[chess.pgn.ChildNode] = []
        sub_variations: list[chess.pgn.ChildNode] = []
        current: Optional[chess.pgn.ChildNode] = start

        while current is not None:
            block.append(current)
            n_vars = len(current.variations)
            if n_vars == 0:
                break
            elif n_vars > 1:
                sub_variations.extend(current.variations[1:])
                current = current.variations[0]
            else:
                current = current.variations[0]

        moves = self._build_moves(block)
        self._populate_move_images(block, moves)
        hover_fens = self._build_hover_fens(block)

        segment: dict = {
            "type": "segment",
            "isVariation": is_variation,
            "isMainLine": False,
            "edgeLabel": edge_label,
            "moves": moves,
            "hoverFens": hover_fens,
            "children": [],
        }

        for alt in sub_variations:
            segment["children"].append(
                self._build_variation_segment(
                    alt, is_variation=True, edge_label=_format_edge_label(alt)
                )
            )
        return segment

    def _build_moves(self, block: list[chess.pgn.ChildNode]) -> list[dict]:
        moves = []
        for node in block:
            san = node.parent.board().san(node.move)
            nag = _nag_symbol(node)
            css_class = _nag_class(node)
            fen = node.board().fen()
            comment_raw = node.comment or ""
            comment = _PGN_COMMAND_ANNOTATION_RE.sub("", comment_raw).strip() or None
            moves.append(
                {
                    "num": _format_move_num(node),
                    "san": san,
                    "nag": nag or None,
                    "nagClass": css_class,
                    "fen": fen,
                    "comment": comment,
                    "image": None,
                }
            )
        return moves

    def _populate_move_images(
        self,
        block: list[chess.pgn.ChildNode],
        moves: list[dict],
    ) -> None:
        """Set the ``image`` field on move dicts in-place.

        Mirrors DOT's ``_block_needs_image`` logic:
        - ``all``: image at every block boundary (commented move OR last move).
        - ``variations``: image at the last move only.
        - ``commented``: image at each commented move.
        Modes combine additively.
        """
        if not self.image_modes or "none" in self.image_modes:
            return
        last_idx = len(moves) - 1
        for i, (node, m) in enumerate(zip(block, moves)):
            is_last = i == last_idx
            if "all" in self.image_modes:
                if m.get("comment") or is_last:
                    m["image"] = self._ensure_image(node)
            else:
                if "variations" in self.image_modes and is_last:
                    m["image"] = self._ensure_image(node)
                if "commented" in self.image_modes and m.get("comment"):
                    m["image"] = self._ensure_image(node)

    def _build_hover_fens(self, block: list[chess.pgn.ChildNode]) -> dict[str, str]:
        hover_fens: dict[str, str] = {}
        if not self.hover:
            return hover_fens
        for node in block:
            fen = node.board().fen()
            img_key = _node_id(fen)
            hover_fens[img_key] = fen
            if img_key not in self._hover_images:
                fill = _last_move_fill(node.move) if self.highlight_last_move else {}
                self._hover_images[img_key] = chess.svg.board(
                    node.board(), size=150, orientation=self.orientation, fill=fill
                )
        return hover_fens

    def _ensure_image(self, node: chess.pgn.ChildNode) -> str:
        board = node.board()
        filename = _node_id(board.fen()) + ".svg"
        if filename not in self._images:
            fill = _last_move_fill(node.move) if self.highlight_last_move else {}
            self._images[filename] = chess.svg.board(
                board, size=250, orientation=self.orientation, fill=fill
            )
        return filename


def export_d3tree(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    hover: bool = False,
    highlight_last_move: bool = True,
) -> tuple[dict, dict[str, str], dict[str, str]]:
    """Export a chess game as a JSON tree dict plus image dicts.

    Returns ``(tree_dict, images, hover_images)`` where:
    - ``tree_dict`` is the JSON-serialisable tree for the D3 renderer
    - ``images`` maps SVG filename → SVG content for board position images
    - ``hover_images`` maps node-ID → SVG content for hover board popups
      (only populated when ``hover=True``)
    """
    return _D3TreeBuilder(game, image_modes, board_img_for_black, hover, highlight_last_move).build()
