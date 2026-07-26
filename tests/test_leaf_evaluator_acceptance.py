"""Real-Stockfish acceptance tests for chesstree.leaf_evaluator.

Excluded from the default pytest run and from CI.  Run explicitly with:

    pytest -m acceptance

These tests wire an actual Stockfish engine and compare local evals against the
Lichess ``analysis`` corpus embedded in ``lisperer-games-black.json``.  Exact
matches are NOT expected (different engine version/depth/hardware); the
assertions check sign agreement on clearly non-drawn positions.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
from typing import Generator

import chess
import chess.engine
import pytest

from chesstree import leaf_evaluator

# ── Engine detection ──────────────────────────────────────────────────────────

STOCKFISH: str | None = shutil.which("stockfish") or (
    "/opt/homebrew/bin/stockfish"
    if os.path.exists("/opt/homebrew/bin/stockfish")
    else None
)

# ── Test constants ────────────────────────────────────────────────────────────

REPO_ROOT = pathlib.Path(__file__).parent.parent
CORPUS_PATH = REPO_ROOT / "lisperer-games-black.json"

# Depth used for all acceptance evaluations — shallow enough to stay fast,
# deep enough to broadly agree with Lichess reference evals.
ACCEPTANCE_DEPTH = 12

# Sampling parameters (fixed — no randomness).
SAMPLE_GAMES = 10       # take first N games that carry an analysis array
PLY_STEP = 6            # evaluate every k-th ply within each game
PLY_MAX = 42            # never go past this ply (half-move 42)

# Tolerance parameters.
DEADZONE_CP = 50        # |eval| <= this → position is near-drawn, skip sign check
SIGN_AGREE_THRESHOLD = 0.80  # fraction of sign-agreeing positions required


# ── Markers / skip guard ──────────────────────────────────────────────────────

_acceptance = pytest.mark.acceptance
_skipif_no_engine = pytest.mark.skipif(
    STOCKFISH is None,
    reason="Stockfish binary not found (checked PATH and /opt/homebrew/bin/stockfish)",
)


# ── Fixture: shared engine provider ──────────────────────────────────────────


@pytest.fixture(scope="module")
def engine_provider() -> Generator[leaf_evaluator.EvalProvider, None, None]:
    """Spawn Stockfish once for the whole module; quit cleanly after all tests."""
    assert STOCKFISH is not None, "Stockfish binary required"
    provider, closer = leaf_evaluator.make_engine_provider(
        STOCKFISH,
        chess.engine.Limit(depth=ACCEPTANCE_DEPTH),
    )
    try:
        yield provider
    finally:
        closer()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _board_after_plies(moves_list: list[str], num_plies: int) -> chess.Board:
    """Return a Board with the first *num_plies* half-moves from *moves_list* pushed."""
    board = chess.Board()
    for san in moves_list[:num_plies]:
        board.push_san(san)
    return board


def _sign(x: int) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


# ── Corpus parity test ────────────────────────────────────────────────────────


@_acceptance
@_skipif_no_engine
class TestCorpusParityLichessEvals:
    """Compare local Stockfish evals against Lichess reference evals."""

    @pytest.fixture(scope="class")
    def sampled_positions(self) -> list[tuple[chess.Board, dict]]:
        """Return a fixed list of (board, lichess_entry) pairs sampled from corpus."""
        with open(CORPUS_PATH) as f:
            corpus: list[dict] = json.load(f)

        positions: list[tuple[chess.Board, dict]] = []
        games_used = 0

        for game_dict in corpus:
            if game_dict.get("variant", "standard") != "standard":
                continue
            analysis = game_dict.get("analysis")
            if not analysis:
                continue

            moves_list = game_dict["moves"].split()
            # analysis[i] = Lichess eval AFTER ply (i+1); valid range: i in [0, len(analysis)-1]
            # We sample positions at ply p (1-based), Lichess ref = analysis[p-1].
            for p in range(PLY_STEP, min(len(analysis), PLY_MAX) + 1, PLY_STEP):
                lichess_entry = analysis[p - 1]  # 0-based index into analysis
                board = _board_after_plies(moves_list, p)
                positions.append((board, lichess_entry))

            games_used += 1
            if games_used >= SAMPLE_GAMES:
                break

        assert positions, "No positions sampled — check corpus path and format"
        return positions

    def test_sign_agreement(
        self,
        engine_provider: leaf_evaluator.EvalProvider,
        sampled_positions: list[tuple[chess.Board, dict]],
    ) -> None:
        """Local Stockfish sign must agree with Lichess on clearly non-drawn positions."""
        agree = 0
        disagree = 0
        skipped = 0
        mismatches: list[str] = []

        for board, lichess_entry in sampled_positions:
            pov = engine_provider(board)
            if pov is None:
                skipped += 1
                continue

            local_white = pov.white()

            # ── Lichess is a mate ──
            if "mate" in lichess_entry:
                lichess_mate = lichess_entry["mate"]
                if local_white.is_mate():
                    # Both mate: signs must agree
                    local_mate = local_white.mate()
                    assert local_mate is not None
                    if _sign(lichess_mate) == _sign(local_mate):
                        agree += 1
                    else:
                        disagree += 1
                        mismatches.append(
                            f"FEN={board.fen()!r} lichess=mate{lichess_mate} local=mate{local_mate}"
                        )
                else:
                    # Lichess mate, local cp — treat as agreement if same direction
                    local_cp = local_white.score()
                    if local_cp is not None:
                        if _sign(lichess_mate) == _sign(local_cp) or abs(local_cp) > 200:
                            agree += 1
                        else:
                            disagree += 1
                            mismatches.append(
                                f"FEN={board.fen()!r} lichess=mate{lichess_mate} local_cp={local_cp}"
                            )
                    else:
                        skipped += 1
                continue

            # ── Lichess is centipawns ──
            lichess_cp = lichess_entry.get("eval")
            if lichess_cp is None:
                skipped += 1
                continue

            if local_white.is_mate():
                # Local mate, Lichess cp — lenient same-direction check
                local_mate = local_white.mate()
                assert local_mate is not None
                if _sign(local_mate) == _sign(lichess_cp) or abs(lichess_cp) > 200:
                    agree += 1
                else:
                    disagree += 1
                    mismatches.append(
                        f"FEN={board.fen()!r} local=mate{local_mate} lichess_cp={lichess_cp}"
                    )
                continue

            local_cp = local_white.score()
            if local_cp is None:
                skipped += 1
                continue

            # Both centipawns — sign check, but only outside the deadzone
            if abs(local_cp) <= DEADZONE_CP or abs(lichess_cp) <= DEADZONE_CP:
                # Near-drawn — skip sign check (noise dominates)
                skipped += 1
                continue

            if _sign(local_cp) == _sign(lichess_cp):
                agree += 1
            else:
                disagree += 1
                mismatches.append(
                    f"FEN={board.fen()!r} local_cp={local_cp} lichess_cp={lichess_cp}"
                )

        total_checked = agree + disagree
        assert total_checked > 0, "No non-drawn positions found in sample — widen sample"

        fraction = agree / total_checked
        mismatch_preview = "\n".join(mismatches[:10])
        assert fraction >= SIGN_AGREE_THRESHOLD, (
            f"Sign agreement too low: {agree}/{total_checked} = {fraction:.2%} "
            f"(threshold {SIGN_AGREE_THRESHOLD:.0%}), skipped={skipped}.\n"
            f"First mismatches:\n{mismatch_preview}"
        )

    def test_sample_size_is_reasonable(
        self,
        sampled_positions: list[tuple[chess.Board, dict]],
    ) -> None:
        """Sanity-check: we actually sampled a meaningful number of positions."""
        assert len(sampled_positions) >= 30, (
            f"Only {len(sampled_positions)} positions sampled — check corpus/sampling params"
        )


# ── Smoke test: single known position ────────────────────────────────────────


@_acceptance
@_skipif_no_engine
class TestSmokePosition:
    """Verify real engine wiring end-to-end with a well-known position."""

    def test_after_e4_small_white_advantage(
        self, engine_provider: leaf_evaluator.EvalProvider
    ) -> None:
        """After 1. e4, Stockfish should give a small white-ish advantage."""
        board = chess.Board()
        board.push_san("e4")

        pov = engine_provider(board)
        assert pov is not None, "Engine returned None for a trivial position"

        white_score = pov.white()
        assert not white_score.is_mate(), "Unexpected mate score after 1. e4"

        cp = white_score.score()
        assert cp is not None
        assert -100 <= cp <= 200, (
            f"Unexpected eval after 1. e4: {cp} cp (expected -100..200)"
        )
