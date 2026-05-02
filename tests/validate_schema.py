"""Validate chesstree JSON/EDN exporter output against docs/schema.md.

This script checks that the actual output of the JSON and EDN exporters
complies with the normative schema specification. It can be run standalone
or imported as a module for use in integration tests.

Usage:
    python tests/validate_schema.py [PGN_FILE ...]

When invoked without arguments it validates all PGNs in tests/sample_pgns/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import chess.pgn

from chesstree.json_exporter import JsonExporter


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

class SchemaValidator:
    """Accumulates validation errors for a single JSON/EDN document."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def check(self, condition: bool, msg: str) -> None:
        if not condition:
            self.errors.append(msg)

    # -- §1: Top-level object -----------------------------------------------

    def validate_document(self, data: dict[str, Any], label: str) -> None:
        path = label

        self.check(isinstance(data, dict), f"{path}: document should be dict")
        if not isinstance(data, dict):
            return

        self.check("schema_version" in data, f"{path}: missing schema_version")
        self.check("headers" in data, f"{path}: missing headers")
        self.check("moves" in data, f"{path}: missing moves")
        self.check("result" in data, f"{path}: missing result")

        keys = list(data.keys())
        if keys:
            self.check(
                keys[0] == "schema_version",
                f"{path}: schema_version should be first key, got {keys[0]!r}",
            )

        self.check(
            isinstance(data.get("schema_version"), str),
            f"{path}: schema_version should be str",
        )
        self.check(
            data.get("schema_version") == "1.1.0",
            f"{path}: schema_version should be '1.1.0'",
        )

        r = data.get("result")
        self.check(
            r is None or isinstance(r, str),
            f"{path}: result should be str or null",
        )
        if isinstance(r, str):
            self.check(
                r in ("1-0", "0-1", "1/2-1/2", "*"),
                f"{path}: unexpected result value {r!r}",
            )

        headers = data.get("headers", {})
        self.check(isinstance(headers, dict), f"{path}: headers should be dict")
        for k, v in headers.items():
            self.check(isinstance(k, str), f"{path}.headers: key should be str")
            self.check(
                isinstance(v, str),
                f"{path}.headers[{k}]: value should be str",
            )

        if "Result" in headers and r is not None:
            self.check(
                headers["Result"] == r,
                f"{path}: headers['Result']={headers['Result']!r} != result={r!r}",
            )

        self.check(
            isinstance(data.get("moves", []), list),
            f"{path}: moves should be list",
        )
        self._validate_moves(data.get("moves", []), f"{path}.moves")

    # -- §3 / §4: Moves array -----------------------------------------------

    def _validate_moves(self, moves: list[Any], path: str) -> None:
        prev_move: dict[str, Any] | None = None
        for i, entry in enumerate(moves):
            entry_path = f"{path}[{i}]"
            if not isinstance(entry, dict):
                self.check(False, f"{entry_path}: moves entry should be dict, got {type(entry).__name__}")
                continue
            if "variation" in entry:
                self.check(
                    i > 0,
                    f"{entry_path}: variation wrapper must not be first in array",
                )
                self._validate_variation(entry, entry_path, prev_move)
            else:
                self._validate_move(entry, entry_path)
                prev_move = entry

    def _validate_move(self, entry: dict[str, Any], path: str) -> None:
        required = [
            "move_number", "turn", "san", "uci", "fen_before", "fen_after",
        ]
        for field in required:
            self.check(field in entry, f"{path}: missing required field '{field}'")

        if "move_number" in entry:
            self.check(
                isinstance(entry["move_number"], int),
                f"{path}: move_number should be int, got {type(entry['move_number']).__name__}",
            )
        if "turn" in entry:
            self.check(
                entry["turn"] in ("white", "black"),
                f"{path}: turn should be 'white' or 'black', got {entry['turn']!r}",
            )
        for field in ("san", "uci", "fen_before", "fen_after"):
            if field in entry:
                self.check(
                    isinstance(entry[field], str),
                    f"{path}: {field} should be str",
                )

        # -- Optional fields --

        if "comments" in entry:
            self.check(
                isinstance(entry["comments"], list),
                f"{path}: comments should be list",
            )
            self.check(
                len(entry["comments"]) > 0,
                f"{path}: comments should not be empty list (should be absent)",
            )
            for ci, c in enumerate(entry.get("comments", [])):
                self.check(
                    isinstance(c, str),
                    f"{path}.comments[{ci}]: should be str, got {type(c).__name__}",
                )
                self.check(
                    len(c.strip()) > 0,
                    f"{path}.comments[{ci}]: should not be empty string",
                )

        if "nags" in entry:
            self.check(
                isinstance(entry["nags"], dict),
                f"{path}: nags should be dict",
            )
            self.check(
                len(entry["nags"]) > 0,
                f"{path}: nags should not be empty dict (should be absent)",
            )
            for k, v in entry.get("nags", {}).items():
                self.check(isinstance(k, str), f"{path}.nags: key should be str")
                self.check(
                    k.isdigit(),
                    f"{path}.nags: key should be numeric string, got {k!r}",
                )
                self.check(
                    v is None or isinstance(v, str),
                    f"{path}.nags[{k}]: value should be str or null, got {type(v).__name__}",
                )

        if "clock" in entry:
            self.check(
                isinstance(entry["clock"], (int, float)),
                f"{path}: clock should be number, got {type(entry['clock']).__name__}",
            )
        if "emt" in entry:
            self.check(
                isinstance(entry["emt"], (int, float)),
                f"{path}: emt should be number, got {type(entry['emt']).__name__}",
            )

        if "eval" in entry:
            ev = entry["eval"]
            self.check(isinstance(ev, dict), f"{path}: eval should be dict")
            has_cp = "cp" in ev
            has_mate = "mate" in ev
            self.check(
                has_cp or has_mate,
                f"{path}.eval: must have 'cp' or 'mate'",
            )
            self.check(
                not (has_cp and has_mate),
                f"{path}.eval: should not have both 'cp' and 'mate'",
            )
            if has_cp:
                self.check(
                    isinstance(ev["cp"], int),
                    f"{path}.eval.cp: should be int, got {type(ev['cp']).__name__}",
                )
            if has_mate:
                self.check(
                    isinstance(ev["mate"], int),
                    f"{path}.eval.mate: should be int, got {type(ev['mate']).__name__}",
                )
            if "depth" in ev:
                self.check(
                    isinstance(ev["depth"], int),
                    f"{path}.eval.depth: should be int",
                )

        if "arrows" in entry:
            self.check(
                isinstance(entry["arrows"], list),
                f"{path}: arrows should be list",
            )
            self.check(
                len(entry["arrows"]) > 0,
                f"{path}: arrows should not be empty list (should be absent)",
            )
            for ai, a in enumerate(entry.get("arrows", [])):
                self.check(isinstance(a, dict), f"{path}.arrows[{ai}]: should be dict")
                for f in ("tail", "head", "color"):
                    self.check(
                        f in a,
                        f"{path}.arrows[{ai}]: missing '{f}'",
                    )
                    self.check(
                        isinstance(a.get(f, ""), str),
                        f"{path}.arrows[{ai}].{f}: should be str",
                    )

        self.check(
            "board_img_after" not in entry,
            f"{path}: board_img_after should not be present",
        )

    # -- §4: Variation wrapper -----------------------------------------------

    def _validate_variation(
        self,
        entry: dict[str, Any],
        path: str,
        prev_move: dict[str, Any] | None,
    ) -> None:
        self.check("variation" in entry, f"{path}: must have 'variation'")
        self.check("branch_fen" in entry, f"{path}: must have 'branch_fen'")
        self.check(
            isinstance(entry.get("variation", []), list),
            f"{path}: variation should be list",
        )
        self.check(
            len(entry.get("variation", [])) > 0,
            f"{path}: variation should not be empty",
        )
        if "comments" in entry:
            self.check(
                isinstance(entry["comments"], list),
                f"{path}: comments should be list",
            )
            self.check(
                len(entry["comments"]) > 0,
                f"{path}: comments should not be empty list (should be absent)",
            )
            for ci, c in enumerate(entry.get("comments", [])):
                self.check(
                    isinstance(c, str),
                    f"{path}.comments[{ci}]: should be str, got {type(c).__name__}",
                )
                self.check(
                    len(c.strip()) > 0,
                    f"{path}.comments[{ci}]: should not be empty string",
                )

        if prev_move and "branch_fen" in entry and "fen_before" in prev_move:
            self.check(
                entry["branch_fen"] == prev_move["fen_before"],
                f"{path}: branch_fen should equal preceding move's fen_before\n"
                f"  branch_fen={entry['branch_fen']!r}\n"
                f"  prev.fen_before={prev_move['fen_before']!r}",
            )

        var_moves = entry.get("variation", [])
        if var_moves and "branch_fen" in entry:
            first = var_moves[0]
            if "fen_before" in first:
                self.check(
                    entry["branch_fen"] == first["fen_before"],
                    f"{path}: branch_fen should equal first variation move's fen_before",
                )

        self._validate_moves(var_moves, f"{path}.variation")


# ---------------------------------------------------------------------------
# EDN validation
# ---------------------------------------------------------------------------

def validate_edn_keys(edn_str: str, label: str) -> list[str]:
    """Check that EDN output uses hyphenated keywords, not snake_case."""
    errors: list[str] = []

    def chk(condition: bool, msg: str) -> None:
        if not condition:
            errors.append(msg)

    required_keywords = [
        ":schema-version", ":headers", ":moves", ":result",
        ":move-number", ":fen-before", ":fen-after",
        ":san", ":uci", ":turn",
    ]
    for kw in required_keywords:
        chk(kw in edn_str, f"{label}: missing EDN keyword {kw}")

    forbidden_keywords = [
        ":schema_version", ":move_number", ":fen_before", ":fen_after",
    ]
    for kw in forbidden_keywords:
        chk(kw not in edn_str, f"{label}: has snake_case keyword {kw}")

    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_pgn_file(pgn_path: Path) -> list[str]:
    """Validate all export modes for a single PGN file. Returns errors."""
    all_errors: list[str] = []

    with open(pgn_path) as f:
        game = chess.pgn.read_game(f)
    if game is None:
        return [f"{pgn_path.name}: failed to parse PGN"]

    export_configs = [
        ("JSON", {}),
        ("JSON-concise", {"concise": True}),
        ("JSON-no-headers", {"headers": False}),
        ("JSON-no-variations", {"variations": False}),
        ("JSON-no-comments", {"comments": False}),
    ]
    for suffix, kwargs in export_configs:
        label = f"{pgn_path.name}({suffix})"
        json_str = game.accept(JsonExporter(**kwargs))
        data = json.loads(json_str)
        v = SchemaValidator()
        v.validate_document(data, label)
        all_errors.extend(v.errors)

    # EDN key checks
    edn_str = game.accept(JsonExporter(edn=True))
    all_errors.extend(validate_edn_keys(edn_str, f"{pgn_path.name}(EDN)"))

    return all_errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) > 1:
        pgn_paths = [Path(p) for p in sys.argv[1:]]
    else:
        sample_dir = Path(__file__).parent / "sample_pgns"
        pgn_paths = sorted(sample_dir.glob("*.pgn"))

    all_errors: list[str] = []
    for pgn_path in pgn_paths:
        errors = validate_pgn_file(pgn_path)
        all_errors.extend(errors)
        status = "✓" if not errors else f"✗ ({len(errors)} errors)"
        print(f"{status} {pgn_path.name}")

    print(f"\n{'=' * 60}")
    if all_errors:
        print(f"FAILED: {len(all_errors)} errors")
        for e in all_errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
