"""Tests for the DOT exporter."""
from __future__ import annotations

import io
import re
import pathlib

import chess.pgn
import pytest
from chess.pgn import NAG_BLUNDER, NAG_DUBIOUS_MOVE, NAG_GOOD_MOVE, NAG_MISTAKE

from chesstree.dot_exporter import _DotBuilder, _nag_symbol, _wrap, export_dot

# ---------------------------------------------------------------------------
# Sample PGN paths
# ---------------------------------------------------------------------------
import pathlib

SAMPLES = pathlib.Path(__file__).parent / "sample_pgns"
HILLBILLY = SAMPLES / "hillbilly_v3.pgn"
CARO_KANN = SAMPLES / "lichess_study_caro-kann-exchange-sample3.pgn"
LISPERER = SAMPLES / "lisperer_vs_verenitach.pgn"


def _load(path: pathlib.Path) -> chess.pgn.Game:
    with open(path) as f:
        return chess.pgn.read_game(f)


def _load_pgn_str(pgn: str) -> chess.pgn.Game:
    return chess.pgn.read_game(io.StringIO(pgn))


# ---------------------------------------------------------------------------
# Unit tests: _nag_symbol
# ---------------------------------------------------------------------------


class TestNagSymbol:
    def _make_node(self, nags: set[int]) -> chess.pgn.ChildNode:
        game = chess.pgn.Game()
        node = game.add_variation(chess.Move.from_uci("e2e4"))
        node.nags = nags
        return node

    def test_blunder(self):
        assert _nag_symbol(self._make_node({NAG_BLUNDER})) == "??"

    def test_good_move(self):
        assert _nag_symbol(self._make_node({NAG_GOOD_MOVE})) == "!"

    def test_mistake(self):
        assert _nag_symbol(self._make_node({NAG_MISTAKE})) == "?"

    def test_dubious(self):
        assert _nag_symbol(self._make_node({NAG_DUBIOUS_MOVE})) == "?!"

    def test_no_nag(self):
        assert _nag_symbol(self._make_node(set())) == ""

    def test_blunder_takes_priority_over_good(self):
        # Blunder outweighs good move annotation
        assert _nag_symbol(self._make_node({NAG_BLUNDER, NAG_GOOD_MOVE})) == "??"


# ---------------------------------------------------------------------------
# Unit tests: _wrap
# ---------------------------------------------------------------------------


class TestWrap:
    def test_short_text_unchanged(self):
        assert _wrap("hello world") == "hello world"

    def test_wraps_at_word_boundary(self):
        text = "a" * 35 + " " + "b" * 10
        result = _wrap(text, width=40)
        assert '<br align="left"/>' in result

    def test_empty_string(self):
        assert _wrap("") == ""

    def test_single_long_word(self):
        long_word = "a" * 50
        assert _wrap(long_word) == long_word  # can't break, no spaces


# ---------------------------------------------------------------------------
# Unit tests: _format_block_moves
# ---------------------------------------------------------------------------


class TestFormatBlockMoves:
    def _fmt(self, block, first_block):
        return _DotBuilder(chess.pgn.Game())._format_block_moves(block, first_block)

    def test_white_first_block(self):
        game = _load_pgn_str("[Result '*']\n1. e4 e5 *")
        node1 = game.variations[0]  # e4
        node2 = node1.variations[0]  # e5
        result = self._fmt([node1, node2], first_block=True)
        assert result == "1. e4 e5"

    def test_black_first_in_first_block_gets_dotdot(self):
        game = _load_pgn_str("[Result '*']\n1. e4 e5 *")
        e5_node = game.variations[0].variations[0]
        result = self._fmt([e5_node], first_block=True)
        assert result == "1. .. e5"

    def test_black_first_in_non_first_block_gets_dotdot(self):
        game = _load_pgn_str("[Result '*']\n1. e4 e5 *")
        e5_node = game.variations[0].variations[0]
        result = self._fmt([e5_node], first_block=False)
        assert result == "1. .. e5"

    def test_nag_appended_to_san_with_font_color(self):
        game = _load_pgn_str("[Result '*']\n1. e4? *")
        node = game.variations[0]
        node.nags = {NAG_MISTAKE}
        result = self._fmt([node], first_block=True)
        assert result == '1. <font color="#e05040">e4?</font>'

    def test_white_always_shows_number(self):
        game = _load_pgn_str("[Result '*']\n1. e4 e5 2. Nf3 *")
        e4 = game.variations[0]
        e5 = e4.variations[0]
        nf3 = e5.variations[0]
        result = self._fmt([e5, nf3], first_block=False)
        assert result == "1. .. e5 2. Nf3"


# ---------------------------------------------------------------------------
# Unit tests: _move_color
# ---------------------------------------------------------------------------


class TestMoveColor:
    def _make_node(self, nags: set[int]) -> chess.pgn.ChildNode:
        game = chess.pgn.Game()
        node = game.add_variation(chess.Move.from_uci("e2e4"))
        node.nags = nags
        return node

    def test_blunder_color(self):
        from chesstree.dot_exporter import _move_color
        assert _move_color(self._make_node({NAG_BLUNDER})) == "#cc2200"

    def test_mistake_color(self):
        from chesstree.dot_exporter import _move_color
        assert _move_color(self._make_node({NAG_MISTAKE})) == "#e05040"

    def test_good_move_color(self):
        from chesstree.dot_exporter import _move_color
        assert _move_color(self._make_node({NAG_GOOD_MOVE})) == "#84c043"

    def test_no_nag_no_color(self):
        from chesstree.dot_exporter import _move_color
        assert _move_color(self._make_node(set())) is None


# ---------------------------------------------------------------------------
# Unit tests: _group_into_blocks
# ---------------------------------------------------------------------------


class TestGroupIntoBlocks:
    def test_no_comments_one_block(self):
        game = _load_pgn_str("[Result '*']\n1. e4 e5 *")
        moves = [game.variations[0], game.variations[0].variations[0]]
        builder = _DotBuilder(game)
        blocks = builder._group_into_blocks(moves)
        assert len(blocks) == 1
        assert len(blocks[0]) == 2

    def test_comment_splits_block(self):
        game = _load_pgn_str("[Result '*']\n1. e4 { good move } e5 *")
        e4 = game.variations[0]
        e4.comment = "good move"
        e5 = e4.variations[0]
        builder = _DotBuilder(game)
        blocks = builder._group_into_blocks([e4, e5])
        assert len(blocks) == 2
        assert blocks[0] == [e4]
        assert blocks[1] == [e5]


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------


class TestDotFunctional:
    def _dot(self, path: pathlib.Path) -> str:
        return export_dot(_load(path))

    def test_output_is_valid_digraph(self):
        for path in [HILLBILLY, CARO_KANN, LISPERER]:
            dot = self._dot(path)
            assert dot.startswith("digraph {")
            assert dot.strip().endswith("}")

    def test_rankdir_lr(self):
        for path in [HILLBILLY, CARO_KANN, LISPERER]:
            assert "rankdir=LR" in self._dot(path)

    def test_rank_same_constraint_present(self):
        for path in [HILLBILLY, CARO_KANN, LISPERER]:
            assert "rank = same" in self._dot(path)

    def test_root_node_present(self):
        dot = self._dot(LISPERER)
        assert "lisperer vs verenitach" in dot

    def test_root_node_study(self):
        dot = self._dot(HILLBILLY)
        assert "caro-kann, hillbilly: hillbilly" in dot

    def test_main_segments_present(self):
        dot = self._dot(LISPERER)
        segments = re.findall(r"Main line: \d+ - \d+ moves", dot)
        assert len(segments) >= 5  # verenitach has 8 main segments

    def test_variation_nodes_present(self):
        dot = self._dot(LISPERER)
        variations = re.findall(r"Variation: \d+ - \d+ moves", dot)
        assert len(variations) >= 5

    def test_nags_in_move_text(self):
        dot = self._dot(LISPERER)
        assert "g5??" in dot
        assert "h3?" in dot
        assert "d5?" in dot
        assert "Nxg5?!" in dot

    def test_nag_in_edge_label_separate_bold(self):
        dot = self._dot(LISPERER)
        # e5! edge label: NAG is a separate <b>!</b> element, not appended to san
        assert "&#160;<b>!</b>&#160;" in dot

    def test_variation_edge_labels(self):
        dot = self._dot(LISPERER)
        assert "7. Nc3" in dot  # first variation edge in verenitach
        assert "11. .. e5" in dot

    def test_invis_edges_present(self):
        dot = self._dot(LISPERER)
        assert "style=invis" in dot

    def test_empty_label_edges_to_main_segments(self):
        dot = self._dot(LISPERER)
        assert "[label=<>]" in dot

    def test_segment_move_numbers_correct(self):
        dot = self._dot(LISPERER)
        assert "Main line: 1 - 7 moves" in dot
        assert "Main line: 7 - 11 moves" in dot

    def test_black_dotdot_prefix_in_first_block(self):
        dot = self._dot(LISPERER)
        # Segment starting with black move uses ".." prefix
        assert "7. .. O-O" in dot

    def test_black_move_number_in_subsequent_blocks(self):
        dot = self._dot(LISPERER)
        # Second block of seg2 starts with black's dxe4 → should show move number
        assert "9. .. dxe4 10. Nxe4" in dot

    def test_moves_prefix_on_first_block_only(self):
        dot = self._dot(LISPERER)
        # First block of every node has "moves:" prefix
        assert "moves:1. d4" in dot
        assert "moves:7. .. O-O" in dot

    def test_hillbilly_structure(self):
        dot = self._dot(HILLBILLY)
        segs = re.findall(r"Main line: \d+ - \d+ moves", dot)
        assert len(segs) >= 3

    def test_caro_kann_structure(self):
        dot = self._dot(CARO_KANN)
        segs = re.findall(r"Main line: \d+ - \d+ moves", dot)
        assert len(segs) >= 4
