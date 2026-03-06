from __future__ import annotations

import chess
import json
from chess.pgn import (
    BaseVisitor,
    SKIP,
    SkipType,
    NAG_GOOD_MOVE,
    NAG_MISTAKE,
    NAG_BRILLIANT_MOVE,
    NAG_BLUNDER,
    NAG_SPECULATIVE_MOVE,
    NAG_DUBIOUS_MOVE,
    NAG_FORCED_MOVE,
    NAG_DRAWISH_POSITION,
    NAG_UNCLEAR_POSITION,
    NAG_WHITE_SLIGHT_ADVANTAGE,
    NAG_BLACK_SLIGHT_ADVANTAGE,
    NAG_WHITE_MODERATE_ADVANTAGE,
    NAG_BLACK_MODERATE_ADVANTAGE,
    NAG_WHITE_DECISIVE_ADVANTAGE,
    NAG_BLACK_DECISIVE_ADVANTAGE,
    NAG_WHITE_ZUGZWANG,
    NAG_BLACK_ZUGZWANG,
    NAG_WHITE_MODERATE_COUNTERPLAY,
    NAG_BLACK_MODERATE_COUNTERPLAY,
    NAG_WHITE_DECISIVE_COUNTERPLAY,
    NAG_BLACK_DECISIVE_COUNTERPLAY,
    NAG_WHITE_MODERATE_TIME_PRESSURE,
    NAG_BLACK_MODERATE_TIME_PRESSURE,
    NAG_WHITE_SEVERE_TIME_PRESSURE,
    NAG_BLACK_SEVERE_TIME_PRESSURE,
    NAG_NOVELTY,
)
from typing import Optional, List, Union

try:
    from typing import override
except ImportError:
    from typing_extensions import override


def _standardize_comments(comment: Union[str, List[str]]) -> List[str]:
    if isinstance(comment, str):
        return [comment]
    elif isinstance(comment, list):
        return comment
    return []


def to_edn(obj: object, str_as_keyword: bool = False) -> str:
    """Recursively convert Python data structures to EDN strings."""
    if isinstance(obj, dict):
        return "{" + " ".join(f"{to_edn(k, True)} {to_edn(v)}" for k, v in obj.items()) + "}"
    elif isinstance(obj, list):
        return "[" + " ".join(to_edn(x) for x in obj) + "]"
    elif isinstance(obj, str):
        if str_as_keyword:
            return f":{obj.replace('_', '-')}"
        else:
            return f'"{obj}"'
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif obj is None:
        return "nil"
    else:
        return str(obj)


NAG_TO_PGN_STRING = {
    # Move assessment ($1–$6) — inline PGN symbols
    NAG_GOOD_MOVE: "!",
    NAG_MISTAKE: "?",
    NAG_BRILLIANT_MOVE: "!!",
    NAG_BLUNDER: "??",
    NAG_SPECULATIVE_MOVE: "!?",
    NAG_DUBIOUS_MOVE: "?!",
    # $7: forced/only move; $8 and $9 have no standard symbol
    NAG_FORCED_MOVE: "□",
    # Position assessment ($10–$19)
    # $11 (quiet) and $12 (active) have no standard symbol in the PGN spec
    NAG_DRAWISH_POSITION: "=",       # $10
    NAG_UNCLEAR_POSITION: "∞",       # $13
    NAG_WHITE_SLIGHT_ADVANTAGE: "⩲", # $14
    NAG_BLACK_SLIGHT_ADVANTAGE: "⩱", # $15
    NAG_WHITE_MODERATE_ADVANTAGE: "±", # $16
    NAG_BLACK_MODERATE_ADVANTAGE: "∓", # $17
    NAG_WHITE_DECISIVE_ADVANTAGE: "+-", # $18
    NAG_BLACK_DECISIVE_ADVANTAGE: "-+", # $19
    # Zugzwang ($22–$23)
    NAG_WHITE_ZUGZWANG: "⨀",         # $22
    NAG_BLACK_ZUGZWANG: "⨀",         # $23
    # Counterplay ($132–$135): ⇆ explicitly defined for $132; extended to all
    NAG_WHITE_MODERATE_COUNTERPLAY: "⇆",  # $132
    NAG_BLACK_MODERATE_COUNTERPLAY: "⇆",  # $133
    NAG_WHITE_DECISIVE_COUNTERPLAY: "⇆",  # $134
    NAG_BLACK_DECISIVE_COUNTERPLAY: "⇆",  # $135
    # Time pressure ($136–$139): ⨁ explicitly defined for $138; extended to all
    NAG_WHITE_MODERATE_TIME_PRESSURE: "⨁", # $136
    NAG_BLACK_MODERATE_TIME_PRESSURE: "⨁", # $137
    NAG_WHITE_SEVERE_TIME_PRESSURE: "⨁",   # $138
    NAG_BLACK_SEVERE_TIME_PRESSURE: "⨁",   # $139
    # Novelty
    NAG_NOVELTY: "N",                # $146
}


class JsonExporter(BaseVisitor[str]):
    def __init__(
        self,
        *,
        headers: bool = True,
        comments: bool = True,
        variations: bool = True,
        edn: bool = False,
        concise: bool = False,
        board_img_for_black: bool = False,
    ):
        self.headers_flag = headers
        self.comments_flag = comments
        self.variations_flag = variations
        self.edn_flag = edn
        self.board_img_for_black_flag = board_img_for_black
        self.indent = None if concise else 2

        self.reset_game()

    def reset_game(self) -> None:
        self.game_data: dict = {
            "headers": {},
            "moves": [],
            "result": None,
        }
        self.current_variation: List[dict] = self.game_data["moves"]
        self.variation_stack: List[List[dict]] = []
        self.variation_depth: int = 0

    def begin_headers(self) -> None:
        self.game_data["headers"] = {}

    def visit_header(self, tagname: str, tagvalue: str) -> None:
        if self.headers_flag:
            self.game_data["headers"][tagname] = tagvalue

    def end_headers(self) -> None:
        pass

    def begin_variation(self) -> Optional[SkipType]:
        self.variation_depth += 1
        if not self.variations_flag:
            return SKIP
        variation: List[dict] = []
        self.current_variation.append({"variation": variation})
        self.variation_stack.append(self.current_variation)
        self.current_variation = variation
        return None

    def end_variation(self) -> None:
        self.variation_depth -= 1
        if self.variation_stack:
            self.current_variation = self.variation_stack.pop()

    def visit_comment(self, comment: Union[str, List[str]]) -> None:
        if self.comments_flag and self.current_variation:
            comments = _standardize_comments(comment)
            if "comments" not in self.current_variation[-1]:
                self.current_variation[-1]["comments"] = []
            self.current_variation[-1]["comments"].extend(comments)

    def visit_nag(self, nag: int) -> None:
        if self.comments_flag and self.current_variation:
            if "nags" not in self.current_variation[-1]:
                self.current_variation[-1]["nags"] = []
            self.current_variation[-1]["nags"].append({nag: NAG_TO_PGN_STRING.get(nag)})

    def visit_move(self, board: chess.Board, move: chess.Move) -> None:
        board_after = board.copy()
        board_after.push(move)
        orientation = chess.BLACK if self.board_img_for_black_flag else chess.WHITE
        move_entry = {
            "move_number": board.fullmove_number,
            "turn": "white" if board.turn == chess.WHITE else "black",
            "san": board.san(move),
            "uci": move.uci(),
            "fen": board.fen(),
            "board_img_before": chess.svg.board(board, size=250, orientation=orientation).replace('"', '\\"'),
            "board_img_after": chess.svg.board(board_after, size=250, orientation=orientation).replace('"', '\\"'),
        }
        self.current_variation.append(move_entry)

    def visit_result(self, result: str) -> None:
        self.game_data["result"] = result

    @override
    def result(self) -> str:
        if self.edn_flag:
            result_string = to_edn(self.game_data)
        else:
            result_string = json.dumps(self.game_data, indent=self.indent)
        self.reset_game()
        return result_string

    def __str__(self) -> str:
        return self.result()
