# Local opening-end divider — implementation plan

## Goal

Own the opening/end-of-opening boundary logic in-repo so we decide when the opening ends for an
individual game, instead of depending on Lichess `division.middle`. This is step 4 of
`plans/opening-merge-plan.md` ("Local opening-end divider plan") and unblocks reuse across Lichess,
Chess.com, and local-directory PGN sources.

Scope of this plan: build and test a source-agnostic divider module, wire it into the existing POC
(`scripts/merge_openings.py`) so the merge flow no longer reads `division.middle`, and expose it on
the `chesstree` CLI as an opt-in single-game `--annotate-opening-end` flag. Leaf evaluation
ownership stays deferred (still read from inline `[%eval ...]`), per the parent plan.

## Reference: upstream algorithm

The source of truth is `scalachess` `core/src/main/scala/Divider.scala`. `Divider.apply(boards)`
takes a list of board states (index 0 = initial position, index i = position after i half-moves)
and returns the first opening-end index:

```
midGame = first index where
    majorsAndMinors(board) <= 10
    || backrankSparse(board)
    || mixedness(board) > 150
```

The endgame threshold (`majorsAndMinors <= 6`) is **out of scope** — we only need the opening end
(`division.middle`).

Heuristic definitions (all operate on bitboards):

- **majorsAndMinors** = popcount(occupied & ~(kings | pawns)) — i.e. count of queens, rooks,
  bishops, knights on the board (both colors).
- **backrankSparse** = (rank 1 & white pieces) popcount < 4 **or** (rank 8 & black pieces)
  popcount < 4. Signals both sides have developed off their back rank.
- **mixedness** = sum over 49 overlapping 2×2 regions of a per-region `score(y, whiteCount,
  blackCount)`. Regions are `0x0303` (squares a1,b1,a2,b2) shifted by `(x + 8*y)` for
  `x ∈ 0..6, y ∈ 0..6`. Region index `i = y*7 + x`; the `score` uses `y = i // 7 + 1` (1..7) and
  the white/black piece counts inside that 2×2 window. The `score` table is a fixed lookup on
  `(whiteCount, blackCount, y)` — port it verbatim from the Scala `match` (values 0..4 for each
  color count).

### Index / ply mapping (main correctness risk)

- `boards[0]` is the **initial position** (0 half-moves played). `boards[i]` is the position after
  `i` half-moves. The returned index is therefore a **0-based ply**: `middle = 0` → opening ends at
  the initial position, `middle = 1` → after White's first move, etc. This matches the semantics
  `scripts/merge_openings.py` already assumes for `division.middle`.
- python-chess bitboard layout is Little-Endian Rank-File (A1 = square 0), identical to scalachess
  `Bitboard`, so the `0x0303 << (x + 8*y)` region masks and rank constants (`chess.BB_RANK_1`,
  `chess.BB_RANK_8`) map over directly with no re-indexing.
- When no board qualifies (game stayed in the opening the whole time), the divider returns `None`.
  Callers fall back to the full game length as the cutoff (last position becomes the leaf) — the
  same semantic the POC already implements for missing `division.middle`.

python-chess equivalents to use:
- `chess.popcount(board.occupied & ~(board.kings | board.pawns))`
- `chess.popcount(chess.BB_RANK_1 & board.occupied_co[chess.WHITE]) < 4` / `BB_RANK_8` + `BLACK`
- `board.occupied_co[chess.WHITE]` / `board.occupied_co[chess.BLACK]` for mixedness region counts

## Deliverables

### 1. New module: `chesstree/opening_divider.py`

Follows repo conventions: `from __future__ import annotations`, full type hints, private helpers
prefixed with `_`, no new dependencies (python-chess only).

Public API:

- `opening_end_ply(game_or_boards) -> int | None`
  Accepts either a `chess.pgn.Game` or a sequence of `chess.Board`. Builds the board list (for a
  game, walk the **main line** from the root, collecting `node.board()` at each node including the
  root/initial position), runs the divider, returns the 0-based opening-end ply, or `None` if the
  opening never ends within the game.

- `boards_from_game(game) -> list[chess.Board]`
  Helper that produces `[initial, after move 1, after move 2, ...]` for the main line. Reused by
  tests and callers.

- `annotate_opening_end(game, ply) -> None` (or return the target node)
  Walks `ply` main-line nodes from the root and appends `[%opening_end]` to that node's comment,
  preserving existing comment text. Mirrors the existing inline logic in
  `scripts/merge_openings.py:create_slice` so that logic can be replaced by a call here.

Private heuristic helpers (faithful ports, kept close to upstream for testable parity):
- `_majors_and_minors(board) -> int`
- `_backrank_sparse(board) -> bool`
- `_mixedness(board) -> int`
- `_mixedness_score(y, white, black) -> int` (the verbatim score table)
- `_MIXEDNESS_REGIONS: tuple[int, ...]` (precomputed 49 region masks)
- `_is_middlegame(board) -> bool` = the `<=10 || sparse || >150` disjunction

Constant threshold values (`10`, `150`, back-rank `4`) named as module constants with a comment
citing `Divider.scala`, so a later deliberate simplification is a one-line change, not a hunt.

### 2. Unit tests: `tests/test_opening_divider.py`

Pin behavior **before** wiring into acquisition (parent plan step 4 requirement). Cover:

- **Acceptance / parity test against real Lichess games (the key validation):** the merge script
  ships a real cached Lichess corpus at `lisperer-games-black.json` (repo root, 336 games), each
  game carrying Lichess's own `division.middle`. The acceptance test loads this file, runs the
  local divider on every game's moves, and asserts our computed opening-end ply **equals** the
  Lichess-provided `division.middle` for that game. Because the port is faithful to `scalachess`,
  this should match exactly for standard chess games — this is the primary proof that our owned
  logic reproduces upstream before we drop the `division.middle` dependency.
  - Compare like-for-like: build the board list from the game's `moves` string, call
    `opening_end_ply`, and compare against `game["division"]["middle"]`.
  - When Lichess omits `division.middle` (game ended in the opening), assert our divider returns
    `None` (or the agreed full-length fallback), matching the "no middlegame reached" semantic.
  - Scope filter: restrict the assertion to **standard** games (skip any non-standard variant in
    the corpus, per the standard-only variant policy); optionally assert the standard subset is
    non-trivially large so the test stays meaningful.
  - Failure reporting: on mismatch, report `game id`, expected `division.middle`, and our computed
    ply so off-by-one or heuristic bugs are immediately diagnosable across the 336-game corpus.
  - This doubles as a regression guard: if `lisperer-games-black.json` is large enough to keep as a
    committed fixture it can live under `tests/` (or be referenced from the repo root); if it is
    considered too big for the suite, trim it to a representative subset that still exercises the
    `<=10`, `backrankSparse`, and `mixedness>150` branches and the `None` fallback.
- **Heuristic units**, each in isolation on hand-built `chess.Board` positions:
  - `majorsAndMinors`: initial position = 14; verify the `<= 10` crossing (e.g. after several
    piece trades).
  - `backrankSparse`: initial = False (8 on each back rank); True once <4 pieces remain on a
    side's back rank.
  - `mixedness`: initial position value (assert it is `<= 150` so the opening does not end at ply
    0); at least one crafted mid-position exceeding 150. Compare against values computed by a
    direct reimplementation in the test to lock the score table.
- **Ply mapping / off-by-one**: build a short game with a known opening-end point and assert the
  returned ply indexes the expected position (e.g. the initial position is never the answer;
  `boards[middle]` is the first qualifying board).
- **No middlegame reached**: a very short game returns `None`; assert callers should fall back to
  full length.
- **`annotate_opening_end`**: appends `[%opening_end]` to the correct node, preserving prior
  comment text, and is idempotent-safe / does not duplicate existing content unexpectedly.
- **Regression fixtures for sample PGNs**: for a couple of games in `tests/sample_pgns/`, record
  the divider output as golden values so unrelated changes cannot silently move the boundary. The
  primary parity guarantee comes from the Lichess corpus test above; these are just local
  regression anchors on the repo's own sample games.

Use existing test helpers/patterns: `_load(path)` for sample games, inline SAN builders like
`_build_game` in `tests/test_merge_openings.py`.

### 3. Wire the divider into `scripts/merge_openings.py`

Replace the Lichess `division.middle` read with the local divider while keeping the POC's Lichess
acquisition and inline-`[%eval]` leaf handling intact (leaf-eval ownership stays deferred).

- Parse each game's moves into a `chess.pgn.Game` (or board list) — the POC already has the SAN
  move string; reuse it to build boards.
- Compute `opening_end_ply = opening_divider.opening_end_ply(...)`.
- Fallback: when the divider returns `None`, use `len(moves_str.split())` (full game length) —
  identical to the current no-`division.middle` branch (`merge_openings.py` lines ~306–321).
- Remove the `division=true` request field and the `division.get("middle")` logic; keep `evals`,
  `moves`, `opening`, `pgnInJson`, `tags`. (Confirm nothing else consumes `division`.)
- `create_slice` already appends `[%opening_end]`; either leave it or delegate to
  `annotate_opening_end` to keep one implementation.
- Update the module docstring (currently "uses Lichess-provided division.middle as the opening
  cutoff") to state the cutoff is computed locally.

Update `tests/test_merge_openings.py` accordingly: tests that construct `division` dicts / rely on
`division.middle` must switch to expecting divider-computed cutoffs (or be replaced by cases that
assert the same slice shape now driven by the divider). Verify the mocked Lichess fetch no longer
needs `division`.

### 4. CLI exposure: `--annotate-opening-end` flag (`chesstree/cli.py`)

The divider module is library-first (importable, reused by the merge script and future acquisition
sources). To also make it usable directly from the `chesstree` command on a single game, add a
small opt-in flag on the existing converter — no subcommand.

Behavior:

- `--annotate-opening-end` (`action="store_true"`, default off). When set, after the input is
  parsed into a `chess.pgn.Game`, call `opening_divider.opening_end_ply(game)` and
  `annotate_opening_end(game, ply)` to append `[%opening_end]` to the cutoff move's comment
  **before** the game is serialized. On `None` (opening never ends), do nothing — no annotation,
  no error (optionally an informational stderr note, matching the POC's info-log style).
- The divider operates on the parsed game's board states, so it is **input-format-agnostic**: it
  applies equally to PGN input and to **chesstree JSON input** (`chesstree/json_parser.py`'s
  `parse_json` returns a `chess.pgn.Game` with move comments). The annotation is inserted on the
  parsed game regardless of source format, so no format-specific guard is needed for the input.
  The flag simply has no effect for output formats that do not carry move comments (it is a no-op
  there rather than an error).
- The annotation flows through naturally to every output that serializes the game's move comments:
  `pgn` (`[%opening_end]` in the move comment), `json`/`edn` (stored in the move's comments), and
  `dot`/`dothtml`/`d3html` (carried as a `[%...]` command annotation). Because it is a `[%...]`
  command annotation, `has_real_comment()` correctly treats it as non-human metadata and it is
  stripped from rendered comment text — confirm that is the desired display behavior; making it
  visible in the tree is a separate rendering decision, out of scope here.

Output-path gaps to close:

- The current CLI dispatch (`cli()`) supports `pgn → json/edn`, `json → pgn`, and
  `pgn/json → dot/dothtml/d3html`, but **not `pgn → pgn`** (and not `json → json`). The most
  useful new passthrough is `pgn → pgn` (`chesstree game.pgn --to pgn --annotate-opening-end`):
  read the game with `chess.pgn.read_game`, apply the annotation when requested, and write it via a
  `chess.pgn.StringExporter` (headers + variations + comments). The annotation is already reachable
  on the existing `json → pgn`, `pgn → json/edn`, and `pgn/json → dot/dothtml/d3html` paths, so
  `pgn → pgn` is the only new path strictly needed to make the flag's primary use case work
  end-to-end. (`json → json` can be added later if wanted, but is not required for this feature.)
- For the existing game-bearing paths (`json → pgn`, `pgn → json/edn`, `pgn/json → dot/dothtml/
  d3html`), thread the flag through so the parsed game is annotated before export. Keep the change
  minimal: annotate right after the game is parsed (`chess.pgn.read_game(...)` or `parse_json(...)`)
  via a shared helper guarded by the flag, so both input formats share one annotation call site.

Tests (`tests/test_cli.py`): flag parsing/default; `pgn → pgn` passthrough emits `[%opening_end]`
on the expected move; a `json → pgn` case confirming annotation works from JSON input; a
`pgn → d3html` case confirming the annotation reaches the parsed game; and a no-op case where the
divider returns `None`. Reuse existing CLI test patterns and sample PGNs/JSON fixtures.

Note: this exposes the divider for **single-game** annotation on the CLI. The multi-game merge flow
stays in `scripts/merge_openings.py` and is not a CLI feature in this slice (consistent with the
parent plan's "standalone script" decision).

## Task breakdown (SQL-tracked once approved)

1. Port heuristics + build `chesstree/opening_divider.py` (module + public API).
2. Write `tests/test_opening_divider.py` (heuristic units, ply mapping, `None` fallback,
   annotation, parity/golden fixtures).
3. Wire divider into `scripts/merge_openings.py`; drop `division` dependence.
4. Update `tests/test_merge_openings.py` for the local-cutoff path.
5. Add `--annotate-opening-end` CLI flag + `pgn → pgn` passthrough; thread into dot/dothtml/d3html
   paths; add `tests/test_cli.py` cases.
6. Run `python -m pytest tests/ -q`; all pass.
7. Update `plans/opening-merge-plan.md` to mark local `opening_end` ownership as landed and point
   the acquisition sections at the new module.

## Validation

- `python -m pytest tests/test_opening_divider.py tests/test_merge_openings.py -q` for the targeted
  loop, then `python -m pytest tests/ -q` before hand-off (AGENTS.md: all tests must pass).
- Manual sanity: run the POC against a cached Lichess sample and confirm produced slices/cutoffs
  are reasonable and `chesstree` still renders `d3html` from the merged PGN (only if visual output
  is in doubt; not regenerating samples unless asked).

## Risks & decisions

- **Off-by-one** between board index and pgn node is the primary risk — pinned by step 2 tests
  before any wiring (parent plan requirement).
- **`mixedness` fidelity** — port the `score` table verbatim first; only consider simplification
  after behavior is validated on fixtures.
- **Variant policy** — standard chess only; Chess960/other variants out of scope. The divider may
  assert / document a standard-start assumption.
- **`boards` construction** — must include the initial position at index 0 so returned plies match
  the existing `division.middle` 0-based convention the merge slice logic depends on.
- **No new dependency** — everything is expressible with python-chess bitboard primitives.

## Out of scope (this slice)

- Endgame boundary (`majorsAndMinors <= 6`).
- Owned leaf evaluation (still read inline `[%eval ...]`).
- Chess.com / local-directory acquisition wiring (they reuse this module later, per parent plan).
- Transposition / longest-common-prefix handling.
