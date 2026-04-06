"""
Functional tests using real PGN files from tests/sample_pgns/.

These tests verify observable behaviour of the full conversion pipeline —
board images, NAG handling, and variation structure — without asserting on
exact output content.
"""
from __future__ import annotations

import io
import json
import pathlib
from typing import Iterator

import chess.pgn
import pytest

from chesstree.cli import pgn_to_json
from chesstree.json_exporter import JsonExporter
from chesstree.json_parser import parse_json
from chesstree.dot_exporter import export_dot

SAMPLE_PGNS = pathlib.Path(__file__).parent / "sample_pgns"

HILLBILLY = SAMPLE_PGNS / "hillbilly_v3.pgn"
CARO_KANN = SAMPLE_PGNS / "lichess_study_caro-kann-exchange-sample3.pgn"
LISPERER  = SAMPLE_PGNS / "lisperer_vs_verenitach.pgn"
GERGESHAIN = SAMPLE_PGNS / "gergeshain-vs-lisperer.pgn"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def convert(pgn_path: pathlib.Path, edn: bool = False, concise: bool = False) -> dict:
    """Run the full pgn_to_json pipeline and return the parsed JSON dict."""
    output = io.StringIO()
    output.name = "<stdout>"
    with open(pgn_path) as f:
        pgn_to_json(f, output, edn=edn, concise=concise)
    output.seek(0)
    return json.loads(output.read())


def iter_moves(moves: list) -> Iterator[dict]:
    """Yield every move entry recursively, descending into variations."""
    for entry in moves:
        if "variation" in entry:
            yield from iter_moves(entry["variation"])
        else:
            yield entry


def main_line_moves(moves: list) -> list[dict]:
    """Return only the top-level (non-variation) move entries."""
    return [m for m in moves if "variation" not in m]


def find_in_main_line(moves: list, san: str, turn: str | None = None) -> dict | None:
    """Find the first matching move in the main line (variations excluded)."""
    for entry in main_line_moves(moves):
        if entry["san"] == san and (turn is None or entry["turn"] == turn):
            return entry
    return None


def nag_symbols(move: dict) -> list[str | None]:
    return list(move.get("nags", {}).values())


# ---------------------------------------------------------------------------
# Board images
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Board images are no longer in JSON output
# ---------------------------------------------------------------------------

class TestNoBoardImagesInJson:
    def test_no_board_img_after_in_any_move(self):
        data = convert(LISPERER)
        for move in iter_moves(data["moves"]):
            assert "board_img_after" not in move, f"Unexpected board_img_after on {move['san']}"

    def test_no_board_img_after_in_variation_moves(self):
        data = convert(HILLBILLY)
        for move in iter_moves(data["moves"]):
            assert "board_img_after" not in move, f"Unexpected board_img_after on {move['san']}"

    def test_fen_after_still_present(self):
        data = convert(LISPERER)
        for move in iter_moves(data["moves"]):
            assert "fen_after" in move, f"Missing fen_after on {move['san']}"


# ---------------------------------------------------------------------------
# NAGs
# ---------------------------------------------------------------------------

class TestNags:
    def test_mistake_nag_on_h3(self):
        # 16. h3? is annotated as a mistake in the main line
        data = convert(LISPERER)
        move = find_in_main_line(data["moves"], "h3", turn="white")
        assert move is not None, "h3 not found in main line"
        assert "?" in nag_symbols(move), f"Expected '?' NAG on h3, got {nag_symbols(move)}"

    def test_blunder_nag_on_g5(self):
        # 24... g5?? is a blunder in the main line
        data = convert(LISPERER)
        move = find_in_main_line(data["moves"], "g5", turn="black")
        assert move is not None, "g5 not found in main line"
        assert "??" in nag_symbols(move), f"Expected '??' NAG on g5, got {nag_symbols(move)}"

    def test_dubious_move_nag_on_nxg5(self):
        # 29. Nxg5?! is annotated as dubious in the main line
        data = convert(LISPERER)
        move = find_in_main_line(data["moves"], "Nxg5", turn="white")
        assert move is not None, "Nxg5 not found in main line"
        assert "?!" in nag_symbols(move), f"Expected '?!' NAG on Nxg5, got {nag_symbols(move)}"

    def test_blunder_nag_in_variation(self):
        # Be2?? appears inside a variation
        data = convert(LISPERER)
        def has_blunder(moves: list) -> bool:
            for entry in moves:
                if "variation" in entry:
                    if has_blunder(entry["variation"]):
                        return True
                elif "??" in nag_symbols(entry):
                    return True
            return False
        assert has_blunder(data["moves"]), "No blunder (??) NAG found anywhere in variations"

    def test_good_move_nag_in_variation(self):
        # e5! appears in a variation
        data = convert(LISPERER)
        def has_good_move(moves: list) -> bool:
            for entry in moves:
                if "variation" in entry:
                    if has_good_move(entry["variation"]):
                        return True
                elif "!" in nag_symbols(entry):
                    return True
            return False
        assert has_good_move(data["moves"]), "No good move (!) NAG found anywhere in variations"

    def test_numeric_nag_with_symbol(self):
        # 11... Nf6 $10 — NAG 10 = NAG_DRAWISH_POSITION, now maps to "="
        data = convert(LISPERER)
        nf6 = find_in_main_line(data["moves"], "Nf6", turn="black")
        assert nf6 is not None, "Nf6 (black, move 11) not found in main line"
        assert "nags" in nf6, "Expected $10 NAG on Nf6"
        # JSON serialises integer dict keys as strings, so 10 → "10"
        assert "10" in nf6["nags"], f"Expected NAG key '10', got {list(nf6['nags'].keys())}"
        # NAG 10 = NAG_DRAWISH_POSITION → symbol "="
        assert nf6["nags"]["10"] == "="

    def test_clean_moves_have_no_nags(self):
        # d4 (first move) carries no annotation
        data = convert(LISPERER)
        d4 = find_in_main_line(data["moves"], "d4", turn="white")
        assert d4 is not None
        assert "nags" not in d4


# ---------------------------------------------------------------------------
# Variations
# ---------------------------------------------------------------------------

class TestVariations:
    def test_variations_present(self):
        data = convert(HILLBILLY)
        variation_entries = [m for m in data["moves"] if "variation" in m]
        assert len(variation_entries) > 0, "Expected variation entries in hillbilly game"

    def test_each_variation_entry_has_non_empty_move_list(self):
        data = convert(HILLBILLY)
        for entry in data["moves"]:
            if "variation" in entry:
                assert isinstance(entry["variation"], list)
                assert len(entry["variation"]) > 0, "Variation entry has empty move list"

    def test_nested_variations_reach_depth_two(self):
        # hillbilly has variations inside variations
        data = convert(HILLBILLY)

        def max_depth(moves: list, current: int = 0) -> int:
            best = current
            for entry in moves:
                if "variation" in entry:
                    best = max(best, max_depth(entry["variation"], current + 1))
            return best

        assert max_depth(data["moves"]) >= 2, "Expected at least 2 levels of nested variations"

    def test_variations_absent_when_disabled(self):
        with open(HILLBILLY) as f:
            game = chess.pgn.read_game(f)
        exporter = JsonExporter(variations=False)
        data = json.loads(game.accept(exporter))
        variation_entries = [m for m in data["moves"] if "variation" in m]
        assert len(variation_entries) == 0, "Expected no variation entries when variations=False"

    def test_comments_present_in_study(self):
        data = convert(CARO_KANN)
        all_moves = list(iter_moves(data["moves"]))
        moves_with_comments = [m for m in all_moves if "comments" in m]
        assert len(moves_with_comments) > 0, "Expected comments in caro-kann study"

    def test_comments_are_lists_of_strings(self):
        data = convert(CARO_KANN)
        for move in iter_moves(data["moves"]):
            if "comments" in move:
                assert isinstance(move["comments"], list), "comments should be a list"
                for c in move["comments"]:
                    assert isinstance(c, str), f"Each comment should be a string, got {type(c)}"

    def test_branch_fen_equals_first_variation_move_fen_before(self):
        """branch_fen on every variation wrapper must equal the first move's fen_before."""
        data = convert(HILLBILLY)

        def check_branch_fens(moves: list) -> None:
            for entry in moves:
                if "variation" in entry:
                    assert "branch_fen" in entry, "variation wrapper missing branch_fen"
                    first_move = entry["variation"][0]
                    assert entry["branch_fen"] == first_move["fen_before"], (
                        f"branch_fen {entry['branch_fen']!r} != "
                        f"first move fen_before {first_move['fen_before']!r}"
                    )
                    check_branch_fens(entry["variation"])

        check_branch_fens(data["moves"])

    def test_lisperer_has_variations_and_comments(self):
        # The annotated real game has both
        data = convert(LISPERER)
        variation_entries = [m for m in data["moves"] if "variation" in m]
        all_moves = list(iter_moves(data["moves"]))
        moves_with_comments = [m for m in all_moves if "comments" in m]
        assert len(variation_entries) > 0, "Expected variations in annotated game"
        assert len(moves_with_comments) > 0, "Expected comments in annotated game"


# ---------------------------------------------------------------------------
# Round-trip: PGN → JSON → Game → PGN
# ---------------------------------------------------------------------------

def _roundtrip(pgn_path: pathlib.Path) -> tuple[str, str]:
    """
    Parse original PGN → game1, export to JSON, parse JSON → game2.
    Returns (str(game1), str(game2)) for direct comparison.
    Board images are not round-tripped (skipped in json_parser).
    """
    with open(pgn_path) as f:
        game1 = chess.pgn.read_game(f)
    json_str = game1.accept(JsonExporter(headers=True, comments=True, variations=True))
    game2 = parse_json(json.loads(json_str))
    return str(game1), str(game2)


class TestRoundTrip:
    """
    PGN → JSON → Game round-trip tests using all three sample PGNs.

    str(game) uses chess.pgn.StringExporter which renders headers, moves,
    NAGs, comments, and all variations, so string equality implies correctness
    of the entire game tree.
    """

    def test_lisperer_pgn_matches_after_roundtrip(self):
        # Annotated real game: covers NAGs, variations, and comments
        pgn1, pgn2 = _roundtrip(LISPERER)
        assert pgn1 == pgn2

    def test_hillbilly_pgn_matches_after_roundtrip(self):
        # Opening study: covers deeply nested variations (3+ levels)
        pgn1, pgn2 = _roundtrip(HILLBILLY)
        assert pgn1 == pgn2

    def test_caro_kann_pgn_matches_after_roundtrip(self):
        # Lichess study: covers multiple variation branches and prose comments
        pgn1, pgn2 = _roundtrip(CARO_KANN)
        assert pgn1 == pgn2

    def test_variation_starting_comment_round_trips(self):
        pgn_text = (
            "[White \"A\"]\n[Black \"B\"]\n[Result \"*\"]\n\n"
            "1. e4 e5 ({ The Sicilian is also popular. } 1... c5 2. Nf3) 2. Nf3 *"
        )
        game1 = chess.pgn.read_game(io.StringIO(pgn_text))
        json_str = game1.accept(JsonExporter(headers=True, comments=True, variations=True))
        data = json.loads(json_str)
        # The variation wrapper must carry the comment, not headers["Comment"]
        wrapper = next(m for m in data["moves"] if "variation" in m)
        assert wrapper.get("comment") == "The Sicilian is also popular."
        assert "Comment" not in data["headers"]
        # After parsing back, starting_comment lands on the first move of the variation
        game2 = parse_json(data)
        e4_node = game2.variations[0]
        c5_var = e4_node.variations[1]
        assert c5_var.starting_comment == "The Sicilian is also popular."
        assert str(game1) == str(game2)


# ---------------------------------------------------------------------------
# Clock-annotated game: gergeshain-vs-lisperer
# Tests game comment extraction and clock-annotation filtering.
# ---------------------------------------------------------------------------

def _load_game(pgn_path: pathlib.Path) -> chess.pgn.Game:
    with open(pgn_path) as f:
        game = chess.pgn.read_game(f)
    assert game is not None
    return game


class TestGergeshainLisperer:
    """Functional tests for a real blitz game with [%clk] on every move and a game comment."""

    # -- JSON / EDN output ---------------------------------------------------

    def test_game_comment_captured_in_headers(self):
        data = convert(GERGESHAIN)
        assert "Comment" in data["headers"], "Game comment should be stored in headers['Comment']"
        assert "opening mistake" in data["headers"]["Comment"]

    def test_clock_tags_absent_from_move_comments(self):
        """[%clk ...] tags must not appear in move comments."""
        data = convert(GERGESHAIN)
        for move in iter_moves(data["moves"]):
            for c in move.get("comments", []):
                assert "[%clk" not in c, f"[%clk] leaked into comments of move {move['san']}: {c!r}"

    def test_commented_mode_no_image_on_clock_only_moves(self):
        """In commented mode, DOT output should not produce images for clock-only moves."""
        game = _load_game(GERGESHAIN)
        _, images_commented = export_dot(game, image_modes=frozenset(["commented"]))
        _, images_all = export_dot(game, image_modes=frozenset(["all"]))
        assert len(images_commented) < len(images_all)

    def test_commented_mode_image_on_real_comment_moves(self):
        """In commented mode, DOT output should produce images for real-comment moves."""
        game = _load_game(GERGESHAIN)
        _, images_commented = export_dot(game, image_modes=frozenset(["commented"]))
        assert len(images_commented) > 0

    def test_fewer_commented_images_than_all(self):
        game = _load_game(GERGESHAIN)
        _, images_all = export_dot(game, image_modes=frozenset(["all"]))
        _, images_commented = export_dot(game, image_modes=frozenset(["commented"]))
        assert len(images_commented) < len(images_all), (
            f"commented mode ({len(images_commented)}) should produce fewer DOT SVGs than all mode ({len(images_all)})"
        )

    def test_real_comments_present_on_annotated_moves(self):
        """Moves with real prose commentary must have a 'comments' field."""
        data = convert(GERGESHAIN)
        # 22... Ne7 has "moving the king away would have been better..."
        ne7 = find_in_main_line(data["moves"], "Ne7", turn="black")
        assert ne7 is not None, "Ne7 not found in main line"
        assert "comments" in ne7, "Ne7 should carry a human comment"
        assert any("moving the king away" in c for c in ne7["comments"])

    def test_clock_only_moves_have_no_comments(self):
        """Moves whose only annotation is [%clk] must have no 'comments' entry."""
        data = convert(GERGESHAIN)
        # c6 (1... c6) has only [%clk 0:05:00]
        c6 = find_in_main_line(data["moves"], "c6", turn="black")
        assert c6 is not None, "c6 not found in main line"
        assert "comments" not in c6, "c6 (clock-only) should not have a comments entry"

    def test_clock_field_present_on_annotated_moves(self):
        """Every main-line move annotated with [%clk] must expose a float 'clock' field."""
        data = convert(GERGESHAIN)
        for move in main_line_moves(data["moves"]):
            assert "clock" in move, f"Expected clock field on {move['san']}"
            assert isinstance(move["clock"], float)

    def test_clock_value_correct(self):
        """Spot-check: 1. e4 has clock=300.0 (5:00 remaining)."""
        data = convert(GERGESHAIN)
        e4 = find_in_main_line(data["moves"], "e4", turn="white")
        assert e4 is not None
        assert e4["clock"] == pytest.approx(300.0)

    # -- DOT output ----------------------------------------------------------

    def test_dot_root_node_contains_game_comment(self):
        game = _load_game(GERGESHAIN)
        dot, _ = export_dot(game)
        assert "opening mistake" in dot, "DOT root node should contain the game comment text"

    def test_dot_root_node_game_comment_is_italic(self):
        game = _load_game(GERGESHAIN)
        dot, _ = export_dot(game)
        assert "<i>" in dot, "Game comment should be wrapped in <i> tags in the DOT root node"

    def test_dot_output_no_clk_annotations(self):
        """[%clk] text must never appear in the DOT output."""
        game = _load_game(GERGESHAIN)
        dot, _ = export_dot(game)
        assert "[%clk" not in dot, "[%clk] annotation leaked into DOT output"

    def test_dot_commented_mode_fewer_images_than_all(self):
        game = _load_game(GERGESHAIN)
        _, images_all = export_dot(game, image_modes=frozenset(["all"]))
        _, images_commented = export_dot(game, image_modes=frozenset(["commented"]))
        assert len(images_commented) < len(images_all), (
            f"commented mode ({len(images_commented)}) should produce fewer DOT SVGs than all mode ({len(images_all)})"
        )
