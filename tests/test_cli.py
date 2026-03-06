from __future__ import annotations

import io
import json
import sys

import pytest

from chesstree.cli import pgn_to_json

SIMPLE_PGN = """\
[Event "Test Game"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 1-0
"""

EMPTY_PGN = ""  # empty input → read_game returns None


def _make_input(text: str, name: str = "<test>") -> io.StringIO:
    f = io.StringIO(text)
    f.name = name
    return f


def _make_output(name: str = "<stdout>") -> io.StringIO:
    f = io.StringIO()
    f.name = name
    return f


class TestPgnToJson:
    def test_basic_conversion_produces_valid_json(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=False, edn=False)
        output_f.seek(0)
        data = json.loads(output_f.read())
        assert data["headers"]["White"] == "Alice"
        assert data["result"] == "1-0"

    def test_edn_output(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=False, edn=True)
        output_f.seek(0)
        result = output_f.read()
        assert ":headers" in result
        assert ":moves" in result

    def test_concise_output(self):
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=False, edn=False, concise=True)
        output_f.seek(0)
        # Trim trailing newlines added by print(..., end="\n\n")
        result = output_f.read().strip()
        assert "\n" not in result

    def test_forblack_flag_accepted(self):
        """Smoke test that the forblack flag doesn't raise."""
        output_f = _make_output()
        pgn_to_json(_make_input(SIMPLE_PGN), output_f, forblack=True, edn=False)
        output_f.seek(0)
        data = json.loads(output_f.read())
        assert len(data["moves"]) > 0

    def test_empty_pgn_exits_with_error(self):
        output_f = _make_output()
        with pytest.raises(SystemExit) as exc_info:
            pgn_to_json(_make_input(EMPTY_PGN), output_f, forblack=False, edn=False)
        assert exc_info.value.code == 1
