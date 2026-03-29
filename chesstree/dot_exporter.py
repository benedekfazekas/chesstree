from __future__ import annotations

import hashlib
from typing import Optional

import chess
import chess.pgn
import chess.svg
from chess.pgn import (
    NAG_BLUNDER,
    NAG_BRILLIANT_MOVE,
    NAG_DUBIOUS_MOVE,
    NAG_GOOD_MOVE,
    NAG_MISTAKE,
    NAG_SPECULATIVE_MOVE,
)

from chesstree.json_exporter import NAG_TO_PGN_STRING
from chesstree.utils import has_real_comment, _PGN_COMMAND_ANNOTATION_RE

# Assessment NAGs ordered by priority: most severe first.
# When a block or branch has multiple NAGs, the most severe wins for coloring.
_ASSESSMENT_NAGS_PRIORITY = [
    NAG_BLUNDER,
    NAG_MISTAKE,
    NAG_DUBIOUS_MOVE,
    NAG_SPECULATIVE_MOVE,
    NAG_GOOD_MOVE,
    NAG_BRILLIANT_MOVE,
]

_NAG_COLORS: dict[int, str] = {
    NAG_BLUNDER: "#cc2200",
    NAG_MISTAKE: "#e05040",
    NAG_DUBIOUS_MOVE: "#e08020",
    NAG_SPECULATIVE_MOVE: "#f4bc4f",
    NAG_GOOD_MOVE: "#84c043",
    NAG_BRILLIANT_MOVE: "#66ccff",
}


def _nag_symbol(node: chess.pgn.ChildNode) -> str:
    """Return the PGN symbol for the most significant assessment NAG on this node."""
    for nag in _ASSESSMENT_NAGS_PRIORITY:
        if nag in node.nags:
            return NAG_TO_PGN_STRING[nag]
    return ""


def _move_color(node: chess.pgn.ChildNode) -> Optional[str]:
    """Return the highlight color for a move based on its assessment NAG, or None."""
    for nag in _ASSESSMENT_NAGS_PRIORITY:
        if nag in node.nags:
            return _NAG_COLORS[nag]
    return None


def _node_id(fen: str) -> str:
    """Generate a stable node ID from a FEN string."""
    return "n" + hashlib.md5(fen.encode()).hexdigest()[:8]


def _wrap(text: str, width: int = 40) -> str:
    """Wrap text at word boundaries, joining lines with <br align="left"/>."""
    if not text:
        return text
    words = text.split(" ")
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
    return '<br align="left"/>'.join(lines)


def _move_num(node: chess.pgn.ChildNode) -> str:
    return str(node.parent.board().fullmove_number)


def _is_white_move(node: chess.pgn.ChildNode) -> bool:
    return node.parent.board().turn == chess.WHITE


class _DotBuilder:
    """Builds a GraphViz DOT representation of a chess game tree."""

    def __init__(
        self,
        game: chess.pgn.Game,
        image_modes: frozenset[str] = frozenset(["variations"]),
        board_img_for_black: bool = False,
        hover: bool = False,
    ) -> None:
        self.game = game
        self.image_modes = image_modes
        self.orientation = chess.BLACK if board_img_for_black else chess.WHITE
        self.hover = hover
        self._node_decls: list[str] = []
        self._edge_decls: list[str] = []
        self._main_seg_ids: list[str] = []
        self._images: dict[str, str] = {}       # filename → SVG content (inline images)
        self._hover_images: dict[str, str] = {} # fenhash → SVG content (hover popups)

    def build(self) -> tuple[str, dict[str, str]]:
        root_id = self._render_root_node()

        if self.game.variations:
            segments = self._collect_main_segments()
            prev_seg_id: Optional[str] = None

            for seg_nodes, alternatives in segments:
                seg_id = _node_id(seg_nodes[0].board().fen())
                self._main_seg_ids.append(seg_id)

                label = self._render_node_label(seg_nodes, is_main=True)
                self._node_decls.append(f"   {seg_id} [label={label}, shape=plaintext] ")

                self._edge_decls.append(f"   {root_id} -> {seg_id} [label=<>] ")
                if prev_seg_id:
                    self._edge_decls.append(f"   {prev_seg_id} -> {seg_id} [style=invis] ")

                branching_move = seg_nodes[-1]
                for alt_node in alternatives:
                    self._process_variation(alt_node, seg_id)

                prev_seg_id = seg_id

        lines = ["digraph {", "   graph[rankdir=LR]    "]
        lines.extend(self._node_decls)
        if self._main_seg_ids:
            seg_ids_str = "; ".join(self._main_seg_ids)
            lines.append(f"{{ rank = same; {seg_ids_str}}}")
        lines.extend(self._edge_decls)
        lines.append(" }")
        return "\n".join(lines), self._images, self._hover_images

    # ------------------------------------------------------------------
    # Graph structure helpers
    # ------------------------------------------------------------------

    def _collect_main_segments(
        self,
    ) -> list[tuple[list[chess.pgn.ChildNode], list[chess.pgn.ChildNode]]]:
        """Split the main line into (segment_nodes, alternatives) pairs.

        A segment ends when a node has >1 variations (branch point). At a
        branch point the chosen main-line move (variations[0], "the branching
        move") is added as the LAST node of the segment; alternatives
        (variations[1:]) spawn variation nodes.
        """
        result: list[tuple[list[chess.pgn.ChildNode], list[chess.pgn.ChildNode]]] = []
        current: list[chess.pgn.ChildNode] = []
        node: Optional[chess.pgn.ChildNode] = self.game.variations[0]

        while node is not None:
            current.append(node)
            n_vars = len(node.variations)

            if n_vars == 0:
                result.append((current, []))
                break
            elif n_vars > 1:
                # Branch point: include variations[0] (branching move) as the
                # last node of this segment, then start a new segment.
                alternatives = list(node.variations[1:])
                branching_move = node.variations[0]
                current.append(branching_move)
                result.append((current, alternatives))
                current = []
                if branching_move.variations:
                    node = branching_move.variations[0]
                else:
                    break
            else:
                node = node.variations[0]

        return result

    def _collect_variation_moves(
        self, start_node: chess.pgn.ChildNode
    ) -> tuple[list[chess.pgn.ChildNode], list[chess.pgn.ChildNode]]:
        """Collect all moves of a variation and note sub-branch alternative starts.

        Returns (moves, sub_variation_starts).
        """
        moves: list[chess.pgn.ChildNode] = []
        sub_variations: list[chess.pgn.ChildNode] = []
        node: Optional[chess.pgn.ChildNode] = start_node

        while node is not None:
            moves.append(node)
            n_vars = len(node.variations)
            if n_vars == 0:
                break
            elif n_vars > 1:
                continuation = node.variations[0]
                for alt in node.variations[1:]:
                    sub_variations.append(alt)
                node = continuation
            else:
                node = node.variations[0]

        return moves, sub_variations

    def _process_variation(
        self,
        start_node: chess.pgn.ChildNode,
        parent_id: str,
    ) -> None:
        """Render a variation node and recursively handle sub-variations."""
        moves, sub_variations = self._collect_variation_moves(start_node)
        var_id = _node_id(start_node.board().fen())

        label = self._render_node_label(moves, is_main=False)
        self._node_decls.append(f"   {var_id} [label={label}, shape=plaintext] ")

        edge_label = self._render_edge_label(start_node)
        self._edge_decls.append(f"   {parent_id} -> {var_id} [label={edge_label}] ")

        for alt_node in sub_variations:
            self._process_variation(alt_node, var_id)

    # ------------------------------------------------------------------
    # Node label rendering
    # ------------------------------------------------------------------

    def _render_root_node(self) -> str:
        headers = self.game.headers
        white = headers.get("White")
        black = headers.get("Black")
        date = headers.get("UTCDate") or "null"

        if white and black and white != "?" and black != "?":
            title = f"{white} vs {black} at {date}"
        else:
            event = headers.get("Event", "?")
            title = f"{event} at {date}"

        event = headers.get("Event", "?")
        site = headers.get("Site", "?")
        eco = headers.get("ECO", "?")
        opening = headers.get("Opening", "?")
        result = headers.get("Result", "?")
        body_text = f"{event} {site} opening ({eco}): {opening} Result: {result}"

        wrapped_title = _wrap(title)
        wrapped_body = _wrap(body_text)

        game_comment = _PGN_COMMAND_ANNOTATION_RE.sub("", self.game.comment or "").strip()

        root_id = _node_id(self.game.board().fen())
        comment_row = (
            f'<tr><td border="0"><i>{_wrap(game_comment)}</i></td></tr>'
            if game_comment
            else ""
        )
        label = (
            f"<<table>"
            f'<tr><td border="0"><b>{wrapped_title}</b></td></tr>'
            f"<hr/>"
            f'<tr><td border="0">{wrapped_body}</td></tr>'
            f"{comment_row}"
            f"</table>>"
        )
        self._node_decls.append(f"   {root_id} [label={label}, shape=plaintext]")
        return root_id

    def _render_node_label(
        self,
        moves: list[chess.pgn.ChildNode],
        is_main: bool,
    ) -> str:
        line_type = "Main" if is_main else "Variation"
        start = _move_num(moves[0])
        end = _move_num(moves[-1])

        title = (
            f"{line_type} line: {start} - {end} moves"
            if is_main
            else f"Variation: {start} - {end} moves"
        )

        blocks = self._group_into_blocks(moves)
        total_blocks = len(blocks)

        # In hover mode the table has multiple columns (one per move).
        # Compute the max column count so header/image rows can span the full width.
        if self.hover:
            max_cols = max(len(b) for b in blocks) if blocks else 1
            header = (
                f'<tr><td colspan="{max_cols}" border="0" align="center">'
                f'<b>{title}</b></td></tr>'
            )
        else:
            max_cols = 1  # non-hover table is always single-column
            header = f'<tr><td border="0"><b>{title}</b></td></tr>'

        rows = [header, "<hr/>"]

        for block_idx, block in enumerate(blocks):
            if self.hover:
                rows.append(self._render_block_row_hover(block, block_idx, max_cols))
            else:
                move_html = self._format_block_moves(block, first_block=(block_idx == 0))
                comment_raw = block[-1].comment or ""
                comment = _PGN_COMMAND_ANNOTATION_RE.sub("", comment_raw).strip()
                prefix = "moves:" if block_idx == 0 else ""
                wrapped_comment = _wrap(comment) if comment else ""
                content = f"&#160;<b>{prefix}{move_html}</b>&#160;{wrapped_comment}"
                rows.append(f'<tr><td border="0">{content}</td></tr>')

            if self._block_needs_image(block_idx, total_blocks, block):
                img_filename = self._ensure_image(block[-1])
                colspan_attr = f' colspan="{max_cols}"' if self.hover else ""
                rows.append(
                    f'<tr><td{colspan_attr} href="./{img_filename}" border="0" fixedsize="TRUE"'
                    f' height="100" width="100"><IMG src="./{img_filename}"/></td></tr>'
                )

        colspan_attr = f' colspan="{max_cols}"' if self.hover else ""
        rows.append(f'<tr><td{colspan_attr} border="0"></td></tr>')

        inner = "".join(rows)
        table_attrs = ' cellspacing="0"' if self.hover else ""
        return f"<<table{table_attrs}>{inner}</table>>"

    def _render_block_row_hover(
        self, block: list[chess.pgn.ChildNode], block_idx: int, max_cols: int
    ) -> str:
        """Render a move block as a <tr> with one <td href="#hover-..."> per move.

        Used when hover mode is enabled. Each move cell links to ``#hover-{fenhash}``
        so that the JS post-render hook can attach mouseover handlers.

        The comment (if any) is appended to the last move cell rather than given its
        own column.  The last cell also receives a ``colspan`` to fill any remaining
        columns up to ``max_cols``, keeping the table layout consistent for the
        header and image rows that always span the full width.
        """
        items = self._format_block_moves_hover(block, first_block=(block_idx == 0))
        comment_raw = block[-1].comment or ""
        comment = _PGN_COMMAND_ANNOTATION_RE.sub("", comment_raw).strip()
        wrapped_comment = f"&#160;{_wrap(comment)}" if comment else ""

        n = len(items)
        cells: list[str] = []
        for i, (san_html, fenhash) in enumerate(items):
            is_last = i == n - 1
            # Fold the "moves:" label into the first cell of the first block.
            prefix = "&#160;moves:&#160;" if (block_idx == 0 and i == 0) else "&#160;"
            if is_last:
                remaining = max_cols - n + 1
                colspan_attr = f' colspan="{remaining}"' if remaining > 1 else ""
                cells.append(
                    f'<td{colspan_attr} href="#hover-{fenhash}" border="0">'
                    f'{prefix}<b>{san_html}</b>{wrapped_comment}&#160;</td>'
                )
            else:
                cells.append(
                    f'<td href="#hover-{fenhash}" border="0">'
                    f'{prefix}<b>{san_html}</b></td>'
                )
        return "<tr>" + "".join(cells) + "</tr>"

    def _format_block_moves_hover(
        self, block: list[chess.pgn.ChildNode], first_block: bool
    ) -> list[tuple[str, str]]:
        """Return a list of (san_html, fenhash) for each move in the block.

        ``san_html`` is the formatted move text (with NAG font coloring).
        ``fenhash`` is the node ID of the board FEN *after* the move, used as
        the ``href`` fragment and as the key in the JS ``hoverImages`` dict.
        The hover SVG is generated and stored in ``self._hover_images``.
        """
        result: list[tuple[str, str]] = []
        for i, node in enumerate(block):
            white = _is_white_move(node)
            num = _move_num(node)
            san = node.parent.board().san(node.move)
            nag = _nag_symbol(node)
            color = _move_color(node)
            san_nag = f'<font color="{color}">{san}{nag}</font>' if color else f"{san}{nag}"

            if white:
                move_str = f"{num}. {san_nag}"
            elif i == 0:
                move_str = f"{num}. .. {san_nag}"
            else:
                move_str = san_nag

            fenhash = self._ensure_hover_image(node)
            result.append((move_str, fenhash))
        return result

    def _ensure_hover_image(self, node: chess.pgn.ChildNode) -> str:
        """Generate a hover SVG for the board after this node; return its fenhash key."""
        board = node.board()
        fenhash = _node_id(board.fen())
        if fenhash not in self._hover_images:
            self._hover_images[fenhash] = chess.svg.board(
                board, size=250, orientation=self.orientation
            )
        return fenhash

    def _block_needs_image(
        self,
        block_idx: int,
        total_blocks: int,
        block: list[chess.pgn.ChildNode],
    ) -> bool:
        if not self.image_modes or "none" in self.image_modes:
            return False
        if "all" in self.image_modes:
            return True
        needs = False
        if "variations" in self.image_modes and block_idx == total_blocks - 1:
            needs = True
        if "commented" in self.image_modes and has_real_comment(block[-1].comment):
            needs = True
        return needs

    def _ensure_image(self, node: chess.pgn.ChildNode) -> str:
        """Return filename for the board image after this node, generating SVG if needed."""
        board = node.board()
        filename = _node_id(board.fen()) + ".svg"
        if filename not in self._images:
            self._images[filename] = chess.svg.board(
                board, size=250, orientation=self.orientation
            )
        return filename


    def _group_into_blocks(
        self, moves: list[chess.pgn.ChildNode]
    ) -> list[list[chess.pgn.ChildNode]]:
        """Group moves into blocks, ending each block at a move with real human commentary.

        PGN command annotations such as ``[%clk ...]`` are not considered real
        comments and do not cause a block break.
        """
        blocks: list[list[chess.pgn.ChildNode]] = []
        current: list[chess.pgn.ChildNode] = []
        for node in moves:
            current.append(node)
            if has_real_comment(node.comment):
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)
        return blocks

    def _format_block_moves(self, block: list[chess.pgn.ChildNode], first_block: bool) -> str:
        """Format the SAN move text for a block of moves as an HTML fragment.

        Rules:
        - White moves: always show move number.
        - Black move at the start of any block (i == 0): show number with ".." prefix
          so the reader knows which move number they are looking at after a comment break.
        - Black move as a continuation within a block (i > 0): no number.
        - Moves with an assessment NAG are wrapped in <font color="..."> tags.
        """
        parts: list[str] = []
        for i, node in enumerate(block):
            white = _is_white_move(node)
            num = _move_num(node)
            san = node.parent.board().san(node.move)
            nag = _nag_symbol(node)
            color = _move_color(node)
            san_nag = f'<font color="{color}">{san}{nag}</font>' if color else f"{san}{nag}"

            if white:
                move_str = f"{num}. {san_nag}"
            elif i == 0:
                move_str = f"{num}. .. {san_nag}"
            else:
                move_str = san_nag

            parts.append(move_str)

        return " ".join(parts)

    def _render_edge_label(self, node: chess.pgn.ChildNode) -> str:
        """Format the label for an edge pointing to a variation start."""
        white = _is_white_move(node)
        num = _move_num(node)
        san = node.parent.board().san(node.move)
        nag = _nag_symbol(node)
        comment = _PGN_COMMAND_ANNOTATION_RE.sub("", node.comment or "").strip()

        move_text = f"{num}. {san}" if white else f"{num}. .. {san}"

        parts = [f"&#160;<b>{move_text}</b>&#160;"]
        if nag:
            parts.append(f"&#160;<b>{nag}</b>&#160;")
        if comment:
            parts.append(_wrap(comment))

        return "<" + "".join(parts) + ">"


def export_dot(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    hover: bool = False,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Export a chess game to a GraphViz DOT string plus image dicts.

    Returns ``(dot_string, inline_images, hover_images)`` where:

    - ``inline_images`` maps SVG filename to SVG content for board images
      embedded in graph nodes (controlled by ``image_modes``).
    - ``hover_images`` maps fenhash to SVG content for per-move hover popups
      (populated only when ``hover=True``; empty dict otherwise).

    The caller is responsible for writing ``inline_images`` files to disk.
    ``hover_images`` is intended for embedding in the dothtml template.
    """
    return _DotBuilder(game, image_modes, board_img_for_black, hover).build()
