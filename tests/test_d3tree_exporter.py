"""Tests for the D3 tree exporter."""
from __future__ import annotations

import io
import pathlib

import chess
import chess.pgn
import pytest

from chesstree.d3tree_exporter import export_d3tree, _node_id, _format_edge_label

SAMPLES = pathlib.Path(__file__).parent / "sample_pgns"
HILLBILLY = SAMPLES / "hillbilly_v3.pgn"
LISPERER = SAMPLES / "lisperer_vs_verenitach.pgn"
CARO_KANN = SAMPLES / "lichess_study_caro-kann-exchange-sample3.pgn"
GERGESHAIN = SAMPLES / "gergeshain-vs-lisperer.pgn"


def _load(path: pathlib.Path) -> chess.pgn.Game:
    with open(path) as f:
        return chess.pgn.read_game(f)


def _load_pgn(pgn: str) -> chess.pgn.Game:
    return chess.pgn.read_game(io.StringIO(pgn))


def _all_segments(node: dict) -> list[dict]:
    """Recursively collect all segment nodes from the tree."""
    if node["type"] != "segment":
        result = []
        for child in node.get("children", []):
            result.extend(_all_segments(child))
        return result
    result = [node]
    for child in node.get("children", []):
        result.extend(_all_segments(child))
    return result


# ---------------------------------------------------------------------------
# Root node structure
# ---------------------------------------------------------------------------


class TestRootNode:
    def test_root_type(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert tree["type"] == "root"

    def test_root_has_title(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert "lisperer" in tree["title"].lower()
        assert "verenitach" in tree["title"].lower()

    def test_root_has_headers(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert "headers" in tree
        assert "White" in tree["headers"]

    def test_root_has_children(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert len(tree["children"]) > 0

    def test_root_game_comment_none_when_no_comment(self):
        game = chess.pgn.Game()
        game.variations  # ensure no variations
        tree, _, _ = export_d3tree(game)
        assert tree["gameComment"] is None

    def test_root_game_comment_present(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n{ This is a game comment. }\n1. e4 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert tree["gameComment"] == "This is a game comment."

    def test_root_game_comment_strips_pgn_annotations(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n{ [%clk 0:05:00] Opening mistake } 1. e4 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert "[%clk" not in tree["gameComment"]
        assert "Opening mistake" in tree["gameComment"]


# ---------------------------------------------------------------------------
# Segment structure
# ---------------------------------------------------------------------------


class TestSegmentStructure:
    def test_first_child_is_segment(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert tree["children"][0]["type"] == "segment"

    def test_segment_has_moves(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        seg = tree["children"][0]
        assert len(seg["moves"]) > 0

    def test_segment_moves_have_required_fields(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        for seg in _all_segments(tree):
            for move in seg["moves"]:
                assert "num" in move
                assert "san" in move
                assert "nag" in move
                assert "nagClass" in move
                assert "fen" in move
                assert "comment" in move

    def test_white_move_num_format(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 e5 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[0]["num"] == "1."

    def test_black_move_num_format(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 e5 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[1]["num"] == "1\u2026"

    def test_main_line_is_not_variation(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert tree["children"][0]["isVariation"] is False

    def test_main_line_edge_label_is_none(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert tree["children"][0]["edgeLabel"] is None

    def test_no_comment_move_comment_is_none(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 e5 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        for m in _all_segments(tree)[0]["moves"]:
            assert m["comment"] is None

    def test_comment_stored_on_move(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { [%clk 0:05:00] Good opening } 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        seg = _all_segments(tree)[0]
        e4_move = seg["moves"][0]
        assert e4_move["comment"] == "Good opening"

    def test_clock_only_comment_becomes_none_on_move(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { [%clk 0:05:00] } 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        seg = _all_segments(tree)[0]
        assert seg["moves"][0]["comment"] is None


# ---------------------------------------------------------------------------
# Move-level comments (comments no longer split segments)
# ---------------------------------------------------------------------------


class TestMoveComments:
    def test_comment_does_not_split_segment(self):
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 { First comment } 1... e5 2. Nf3 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        segs = _all_segments(tree)
        # All moves are in one main-line segment (no comment-based splitting)
        assert len(segs) == 1

    def test_comment_stored_per_move_in_segment(self):
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 { This is a comment } 1... e5 2. Nf3 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        seg = _all_segments(tree)[0]
        e4_move = seg["moves"][0]
        assert e4_move["comment"] == "This is a comment"
        # Remaining moves have no comment
        for m in seg["moves"][1:]:
            assert m["comment"] is None

    def test_no_comment_no_extra_segments(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 e5 2. Nf3 Nc6 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        segs = _all_segments(tree)
        assert len(segs) == 1

    def test_multiple_comments_all_in_one_segment(self):
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 { First } 1... e5 { Second } 2. Nf3 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        segs = _all_segments(tree)
        # All moves in one segment; two moves carry comments
        assert len(segs) == 1
        commented = [m for m in segs[0]["moves"] if m["comment"]]
        assert len(commented) == 2


# ---------------------------------------------------------------------------
# Variations
# ---------------------------------------------------------------------------


class TestVariations:
    def test_variation_node_is_flagged(self):
        tree, _, _ = export_d3tree(_load(HILLBILLY))
        all_segs = _all_segments(tree)
        variations = [s for s in all_segs if s["isVariation"]]
        assert len(variations) > 0

    def test_variation_has_edge_label(self):
        tree, _, _ = export_d3tree(_load(HILLBILLY))
        all_segs = _all_segments(tree)
        variations = [s for s in all_segs if s["isVariation"]]
        for v in variations:
            assert v["edgeLabel"] is not None
            assert len(v["edgeLabel"]["move"]) > 0

    def test_main_continuation_not_variation(self):
        # First child of root is main line
        tree, _, _ = export_d3tree(_load(HILLBILLY))
        assert tree["children"][0]["isVariation"] is False

    def test_variation_edge_label_includes_move_number(self):
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 (1. d4 d5) 1... e5 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        all_segs = _all_segments(tree)
        variations = [s for s in all_segs if s["isVariation"]]
        assert len(variations) == 1
        assert "1" in variations[0]["edgeLabel"]["move"]

    def test_branch_point_creates_children(self):
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 (1. d4 d5) 1... e5 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        all_segs = _all_segments(tree)
        # Main segment e4+e5 + variation d4 d5 as direct children of root
        assert len(all_segs) >= 2
        variations = [c for c in tree["children"] if c.get("isVariation")]
        assert len(variations) >= 1

    def test_no_game_returns_empty_children(self):
        game = chess.pgn.Game()
        tree, images, hover = export_d3tree(game)
        assert tree["children"] == []
        assert images == {}
        assert hover == {}

    def test_branching_move_alternatives_not_dropped(self):
        # Regression: when a main-line branch point's chosen move (branching_move)
        # itself has alternatives, those alternatives must appear in the tree.
        # Structure: main=1.e4 c5 2.Nf3 d6 3.d4
        #   - alt at c5: 2.d4 (instead of 2.Nf3)
        #   - alt at Nf3: 2...Nf6 (instead of 2...d6)  ← was dropped
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 c5 2. Nf3 (2. d4) d6 (2... Nf6) 3. d4 *"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        all_segs = _all_segments(tree)
        san_sets = [
            {m["san"] for m in seg["moves"]} for seg in all_segs
        ]
        # 2...Nf6 alternative must appear in some segment
        assert any("Nf6" in sans for sans in san_sets), (
            "2...Nf6 variation was dropped from the tree"
        )
        # 2.d4 alternative must also appear
        assert any("d4" in sans for sans in san_sets)
        # Total unique paths: main + 2 alternatives = 3
        def count_paths(node):
            children = node.get("children", [])
            if not children:
                return 1
            return 1 + sum(count_paths(c) for c in children)
        main_segs = [c for c in tree["children"] if c.get("isMainLine")]
        var_segs_root = [c for c in tree["children"] if not c.get("isMainLine")]
        total = (
            1
            + sum(sum(count_paths(vc) for vc in s.get("children", [])) for s in main_segs)
            + sum(count_paths(v) for v in var_segs_root)
        )
        assert total == 3, f"Expected 3 unique paths but got {total}"


# ---------------------------------------------------------------------------
# NAG classes
# ---------------------------------------------------------------------------


class TestNagClasses:
    def _make_game(self, nag: int) -> chess.pgn.Game:
        game = chess.pgn.Game()
        node = game.add_variation(chess.Move.from_uci("e2e4"))
        node.nags = {nag}
        return game

    def test_blunder_nag_class(self):
        from chess.pgn import NAG_BLUNDER
        tree, _, _ = export_d3tree(self._make_game(NAG_BLUNDER))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[0]["nagClass"] == "nag-blunder"
        assert moves[0]["nag"] == "??"

    def test_good_move_nag_class(self):
        from chess.pgn import NAG_GOOD_MOVE
        tree, _, _ = export_d3tree(self._make_game(NAG_GOOD_MOVE))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[0]["nagClass"] == "nag-good"
        assert moves[0]["nag"] == "!"

    def test_no_nag(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[0]["nag"] is None
        assert moves[0]["nagClass"] is None

    def test_lisperer_has_nag_classes(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        all_segs = _all_segments(tree)
        all_moves = [m for s in all_segs for m in s["moves"]]
        nag_moves = [m for m in all_moves if m["nagClass"] is not None]
        assert len(nag_moves) > 0


# ---------------------------------------------------------------------------
# Image modes
# ---------------------------------------------------------------------------


class TestImageModes:
    def _all_move_images(self, tree) -> list[str]:
        """Collect all non-None move image filenames across all segments."""
        return [
            m["image"]
            for seg in _all_segments(tree)
            for m in seg["moves"]
            if m.get("image")
        ]

    def test_none_mode_no_images(self):
        tree, images, _ = export_d3tree(_load(LISPERER), image_modes=frozenset(["none"]))
        assert images == {}
        assert self._all_move_images(tree) == []

    def test_all_mode_every_segment_has_image(self):
        tree, images, _ = export_d3tree(_load(LISPERER), image_modes=frozenset(["all"]))
        assert len(images) > 0
        # Every segment must have at least one move with an image (last move always gets one)
        for seg in _all_segments(tree):
            assert any(m.get("image") for m in seg["moves"])

    def test_variations_mode_produces_images(self):
        tree, images, _ = export_d3tree(_load(LISPERER), image_modes=frozenset(["variations"]))
        assert len(images) > 0

    def test_variations_mode_fewer_than_all(self):
        _, imgs_all, _ = export_d3tree(_load(LISPERER), image_modes=frozenset(["all"]))
        _, imgs_var, _ = export_d3tree(_load(LISPERER), image_modes=frozenset(["variations"]))
        assert len(imgs_var) <= len(imgs_all)

    def test_commented_mode_no_image_on_clock_only(self):
        _, imgs_commented, _ = export_d3tree(
            _load(GERGESHAIN), image_modes=frozenset(["commented"])
        )
        _, imgs_all, _ = export_d3tree(
            _load(GERGESHAIN), image_modes=frozenset(["all"])
        )
        assert len(imgs_commented) < len(imgs_all)

    def test_commented_mode_images_on_commented_moves(self):
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 { Good } 1... e5 2. Nf3 { Nice } 2... Nc6 1-0"
        )
        tree, images, _ = export_d3tree(_load_pgn(pgn), image_modes=frozenset(["commented"]))
        seg = _all_segments(tree)[0]
        e4_move = next(m for m in seg["moves"] if m["san"] == "e4")
        nf3_move = next(m for m in seg["moves"] if m["san"] == "Nf3")
        assert e4_move["image"] is not None
        assert nf3_move["image"] is not None
        assert len(images) > 0

    def test_image_filename_in_tree_matches_images_dict(self):
        tree, images, _ = export_d3tree(_load(LISPERER), image_modes=frozenset(["variations"]))
        referenced = set(self._all_move_images(tree))
        for name in referenced:
            assert name in images

    def test_empty_image_modes_no_images(self):
        tree, images, _ = export_d3tree(_load(LISPERER), image_modes=frozenset())
        assert images == {}


# ---------------------------------------------------------------------------
# Hover mode
# ---------------------------------------------------------------------------


class TestHoverMode:
    def test_hover_false_empty_hover_images(self):
        _, _, hover = export_d3tree(_load(LISPERER), hover=False)
        assert hover == {}

    def test_hover_true_populates_hover_images(self):
        _, _, hover = export_d3tree(_load(LISPERER), hover=True)
        assert len(hover) > 0

    def test_hover_true_populates_hover_fens_in_segments(self):
        tree, _, _ = export_d3tree(_load(LISPERER), hover=True)
        all_segs = _all_segments(tree)
        segs_with_hover = [s for s in all_segs if s["hoverFens"]]
        assert len(segs_with_hover) > 0

    def test_hover_fen_keys_match_hover_images(self):
        tree, _, hover_images = export_d3tree(_load(LISPERER), hover=True)
        all_segs = _all_segments(tree)
        all_fen_keys = set()
        for s in all_segs:
            all_fen_keys.update(s["hoverFens"].keys())
        for key in all_fen_keys:
            assert key in hover_images

    def test_hover_false_empty_hover_fens_in_segments(self):
        tree, _, _ = export_d3tree(_load(LISPERER), hover=False)
        for seg in _all_segments(tree):
            assert seg["hoverFens"] == {}


# ---------------------------------------------------------------------------
# Node ID stability
# ---------------------------------------------------------------------------


class TestNodeId:
    def test_node_id_is_stable(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        assert _node_id(fen) == _node_id(fen)

    def test_node_id_different_for_different_fens(self):
        fen1 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        fen2 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
        assert _node_id(fen1) != _node_id(fen2)

    def test_node_id_format(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        nid = _node_id(fen)
        assert nid.startswith("n")
        assert len(nid) == 9  # 'n' + 8 hex chars


# ---------------------------------------------------------------------------
# Eval field in move dicts
# ---------------------------------------------------------------------------


_EVAL_PGN = (
    "[White \"A\"]\n[Black \"B\"]\n\n"
    "1. e4 { [%clk 0:09:57] [%eval 0.30,20] Human note } "
    "1... e5 { [%eval -0.15] } "
    "2. Nf3 { [%eval #3] } "
    "2... Nc6 { [%eval #-2,15] } *"
)


class TestMoveEval:
    def _game(self):
        return chess.pgn.read_game(io.StringIO(_EVAL_PGN))

    def _moves(self):
        tree, _, _ = export_d3tree(self._game())
        return _all_segments(tree)[0]["moves"]

    def test_eval_field_present_on_all_moves(self):
        for m in self._moves():
            assert "eval" in m

    def test_eval_cp_parsed(self):
        moves = self._moves()
        e4 = moves[0]
        assert e4["eval"] is not None
        assert e4["eval"]["cp"] == 30
        assert e4["eval"]["depth"] == 20
        assert "mate" not in e4["eval"]

    def test_eval_cp_negative(self):
        moves = self._moves()
        e5 = moves[1]
        assert e5["eval"] is not None
        assert e5["eval"]["cp"] == -15
        assert "mate" not in e5["eval"]

    def test_eval_mate_positive(self):
        moves = self._moves()
        nf3 = moves[2]
        assert nf3["eval"] is not None
        assert nf3["eval"]["mate"] == 3
        assert "cp" not in nf3["eval"]

    def test_eval_mate_negative_with_depth(self):
        moves = self._moves()
        nc6 = moves[3]
        assert nc6["eval"] is not None
        assert nc6["eval"]["mate"] == -2
        assert nc6["eval"]["depth"] == 15

    def test_no_eval_returns_none(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { just a comment } *"
        tree, _, _ = export_d3tree(chess.pgn.read_game(io.StringIO(pgn)))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[0]["eval"] is None

    def test_comment_stripped_of_eval_annotation(self):
        """The comment field strips [%eval ...] but the eval field captures it."""
        moves = self._moves()
        e4 = moves[0]
        assert e4["comment"] == "Human note"
        assert e4["eval"]["cp"] == 30


# ---------------------------------------------------------------------------
# var_summary_mode and forBlack in root dict
# ---------------------------------------------------------------------------


class TestVarSummaryMode:
    def test_no_mode_default_none(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert tree.get("varSummaryMode") is None

    def test_leaves_mode_stored(self):
        tree, _, _ = export_d3tree(_load(LISPERER), var_summary_mode="leaves")
        assert tree["varSummaryMode"] == "leaves"

    def test_all_mode_stored(self):
        tree, _, _ = export_d3tree(_load(LISPERER), var_summary_mode="all")
        assert tree["varSummaryMode"] == "all"

    def test_for_black_false_default(self):
        tree, _, _ = export_d3tree(_load(LISPERER))
        assert tree["forBlack"] is False

    def test_for_black_true_when_set(self):
        tree, _, _ = export_d3tree(_load(LISPERER), board_img_for_black=True)
        assert tree["forBlack"] is True


# ---------------------------------------------------------------------------
# Move-level result field
# ---------------------------------------------------------------------------


class TestMoveResult:
    def test_result_field_present_on_all_moves(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 e5 *"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        for m in _all_segments(tree)[0]["moves"]:
            assert "result" in m

    def test_result_none_when_no_annotation(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { just a comment } *"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert _all_segments(tree)[0]["moves"][0]["result"] is None

    def test_result_white_wins(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { [%result 1-0] } 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert _all_segments(tree)[0]["moves"][0]["result"] == "1-0"

    def test_result_black_wins(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { [%result 0-1] } 0-1"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert _all_segments(tree)[0]["moves"][0]["result"] == "0-1"

    def test_result_draw(self):
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { [%result 1/2-1/2] } 1/2-1/2"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert _all_segments(tree)[0]["moves"][0]["result"] == "1/2-1/2"

    def test_result_stripped_from_comment(self):
        """[%result ...] must not appear in the displayed comment text."""
        pgn = "[White \"A\"]\n[Black \"B\"]\n\n1. e4 { Good game [%result 1-0] } 1-0"
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        assert _all_segments(tree)[0]["moves"][0]["comment"] == "Good game"

    def test_result_coexists_with_eval(self):
        """Move can carry both an eval and a result annotation."""
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 { [%eval 0.30,20] [%result 1-0] } 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        m = _all_segments(tree)[0]["moves"][0]
        assert m["result"] == "1-0"
        assert m["eval"] is not None
        assert m["eval"]["cp"] == 30

    def test_result_only_on_annotated_move_not_others(self):
        """Only the move with [%result ...] gets a non-None result; others stay None."""
        pgn = (
            "[White \"A\"]\n[Black \"B\"]\n\n"
            "1. e4 e5 2. Nf3 { [%result 1-0] } 1-0"
        )
        tree, _, _ = export_d3tree(_load_pgn(pgn))
        moves = _all_segments(tree)[0]["moves"]
        assert moves[0]["result"] is None   # 1. e4 — no annotation
        assert moves[1]["result"] is None   # 1... e5 — no annotation
        assert moves[2]["result"] == "1-0"  # 2. Nf3 — annotated
