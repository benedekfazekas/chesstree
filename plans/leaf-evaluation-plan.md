# Leaf-evaluation plan

Owned, local, engine-based evaluation of positions, to replace the merge POC's read-through of
Lichess-embedded `[%eval ...]` and to give `chesstree` a standalone "annotate any PGN with evals"
capability. This is the deferred *leaf-evaluation sourcing* item from
`plans/opening-merge-plan.md`.

## Decisions (settled with the user)

- **Nature:** engine-based. Run a UCI engine (Stockfish) on positions and record a centipawn/mate
  score, white-perspective, as a standard `[%eval ...]` PGN move-comment annotation.
- **Engine client:** use `python-chess`'s `chess.engine` module. It is already a project dependency
  and already imported in the codebase (`chesstree/json_parser.py` uses
  `chess.engine.PovScore` / `Cp` / `Mate`). No new pip dependency is added. The only new runtime
  requirement is a **Stockfish binary on PATH** (or a configurable path). Do **not** hand-roll UCI.
- **Home:** a new `chesstree` module (`chesstree/leaf_evaluator.py`), following the
  `chesstree/opening_divider.py` precedent (source-agnostic reusable logic pulled into the core
  package and reused by both the CLI and the merge script).
- **Design shape — synthesis (pure core + convenience provider):**
  - a **pure, injectable core** that walks a game tree, selects target positions, calls an injected
    `evaluate(board) -> chess.engine.PovScore | None` provider, and writes `[%eval ...]` — fully
    unit-testable with a stub provider, no subprocess, deterministic (matches the divider test
    convention).
  - a **thin convenience provider factory** in the same module that wraps
    `chess.engine.SimpleEngine.popen_uci(...)` + `engine.analyse(board, Limit(...))`. The CLI and the
    merge script call the convenience; tests call the pure core with a stub.
  - engine-spawn code is therefore centralized in `leaf_evaluator.py` (not duplicated across
    `cli.py` and the script).
- **Merge-script eval policy:** prefer local engine eval; **fall back** to the Lichess-embedded
  `[%eval ...]` when the engine is unavailable (binary missing / spawn fails / analyse errors).
- **Standalone-feature scope (which nodes get an eval):** configurable via the CLI, three modes,
  with **leaves + branch points** as the default:
  1. terminal leaves only
  2. terminal leaves + branch points (**default**)
  3. every node
  The merge use-case only needs terminal leaves regardless of this setting.
- **Variant policy:** standard chess only, consistent with the divider.

## Why python-chess `chess.engine` (background)

`chess.engine` is a full UCI/XBoard **client**; it does not bundle an engine binary.

- `chess.engine.SimpleEngine.popen_uci("stockfish")` — spawn the engine subprocess (context-manager
  and async variants exist; `engine.quit()` closes it).
- `engine.analyse(board, chess.engine.Limit(depth=...))` — returns an `InfoDict` whose `score` is a
  `PovScore` (plus `depth`, `pv`, `nodes`, …).
- `chess.engine.Limit(depth=/time=/nodes=)` — search budget.
- `PovScore` / `Cp` / `Mate` — score types; `.white()` gives the white-POV `Score`, `.is_mate()`,
  `.mate()`, `.score()` for centipawns.

These score types are exactly what `json_parser` already consumes and what serializes cleanly back
to `[%eval 0.43]` / `[%eval #-3]`, so the round-trip is already understood by the codebase.

## Module design — `chesstree/leaf_evaluator.py`

Public API (names indicative; finalize during implementation):

- `EvalProvider = Callable[[chess.Board], chess.engine.PovScore | None]`
- Selection helper: given a game and a scope mode, yield the set of target nodes.
  - `TERMINAL = "leaves"`, `BRANCHES = "branch-points"`, `ALL = "all"` (compose as needed so the
    default is leaves + branch points).
  - "branch point" = a node with more than one variation (a fork); "terminal leaf" = a node with no
    variations (`node.is_end()`), including the ends of variation lines.
- `annotate_evals(game, provider, *, scope, overwrite=False) -> int`
  - pure: walks the tree, selects target nodes per `scope`, calls `provider` on each target board,
    formats the score, appends `[%eval ...]` to that node's comment (skipping nodes that already
    carry an `[%eval ...]` unless `overwrite=True`), returns the count annotated.
  - **de-duplicates by normalized FEN**: evaluate each unique position once and reuse the score for
    all target nodes sharing it (relevant for merged trees where leaves can coincide). Reuse
    `merge_openings.normalize_fen` semantics (first 4 FEN fields) — factor the shared helper if
    convenient.
  - a `None` score from the provider means "no eval available" → leave that node unannotated.
- `format_eval(score: chess.engine.PovScore) -> str`
  - white-POV. Mate → `#<n>` (e.g. `#3`, `#-3`); centipawns → decimal pawns with the sign
    convention already used in output (positive = white advantage), e.g. `0.43`, `-1.20`.
  - This is the inverse of the parsing already done in `json_exporter` / `d3tree_exporter`; keep it
    consistent so an annotated-then-parsed round-trip is stable.
- `make_engine_provider(engine_path="stockfish", limit=None, *, multipv=None) -> tuple[EvalProvider, Closer]`
  - convenience wrapping `SimpleEngine.popen_uci` + `analyse`; default `Limit(depth=<DEFAULT_DEPTH>)`.
  - returns the provider plus a closer/`quit` handle (or expose it as a context manager) so the
    engine subprocess is opened once and reused across all positions, then cleanly shut down.
  - raises a clear, catchable error (e.g. `EngineUnavailable`) when the binary is missing or spawn
    fails, so callers can implement the fallback policy.
- Module constants: `DEFAULT_DEPTH` (proposed 20) and `DEFAULT_ENGINE = "stockfish"`.

### Engine lifecycle

Open the engine once per run, evaluate all unique positions, then quit. Never spawn per-position.
Guard all engine interaction so a missing binary or analyse failure degrades gracefully instead of
crashing the caller.

## CLI integration

Mirror the existing `--annotate-opening-end` wiring in `chesstree/cli.py`:

- New flags:
  - `--annotate-eval` (store_true) — enable engine evaluation annotation.
  - `--eval-scope {leaves,branch-points,all}` — default `branch-points` meaning **leaves + branch
    points** (name the default choice so it reads as the combined set; finalize the exact choice
    strings during implementation).
  - `--engine PATH` (default `stockfish`).
  - `--eval-depth INT` / `--eval-time FLOAT` (map to `chess.engine.Limit`; pick one precedence rule).
- Add a `_maybe_annotate_evals(game, args)` helper alongside `_maybe_annotate_opening_end`, applied
  in the same conversion functions (`pgn_to_json`, `json_to_pgn`, `pgn_to_pgn`, `game_to_dot`,
  `game_to_dothtml`, `game_to_d3html`). This makes `--annotate-eval` work for the existing
  `pgn → pgn` passthrough as well as all render targets, so d3html/d3tree eval badges light up for
  PGNs that had no evals.
- CLI builds the engine provider via `make_engine_provider`, passes it to `annotate_evals`, and
  quits the engine after. On `EngineUnavailable`, print a clear stderr warning and continue without
  annotation (do not crash the conversion).

## Merge-script integration (`scripts/merge_openings.py`)

- Replace the current leaf-eval read-through with: **prefer local, fall back to Lichess**.
  - Build one engine provider for the run via `make_engine_provider`. If it raises
    `EngineUnavailable`, log once to stderr and use the existing `extract_eval` Lichess path as the
    fallback for every leaf.
  - When the engine is available: evaluate each merged **terminal leaf** position once (dedup by
    normalized FEN) via `leaf_evaluator`, and build the leaf label from the local eval. Only when a
    given leaf's local eval is `None` (analyse failed for that position) fall back to that game's
    Lichess `[%eval]`.
- Keep the leaf-label format (`vs [Opponent](url): **eval**`) unchanged; only the *source* of the
  eval string changes.
- Sequencing: evaluate **after** the merge (on the merged tree's leaves), so shared leaves are
  evaluated once, rather than evaluating each slice separately.
- Close the engine at the end of the run.

## Testing plan

Follow the divider testing convention (`tests/test_opening_divider.py`) — a dedicated
`tests/test_leaf_evaluator.py` exercising the **pure core with a stub provider** (no Stockfish
needed in CI):

- scope selection: leaves-only / branch-points+leaves / all pick the correct node sets on a game
  with variations and forks.
- `format_eval`: cp and mate, both signs, round-trip against the existing eval parser in
  `json_exporter` / `d3tree_exporter`.
- annotation: appends `[%eval ...]` preserving existing comment text; respects `overwrite`; skips
  nodes that already have an eval when not overwriting.
- de-dup: a provider that records calls is invoked once per unique normalized FEN even when a
  position repeats across leaves.
- `None` provider result → node left unannotated.
- CLI: `--annotate-eval` with an injected/stub provider annotates the passthrough PGN; graceful
  warning path when the engine is unavailable (monkeypatch `make_engine_provider` to raise).
- Merge: with a stub local provider, leaves take local eval; when the provider yields `None` for a
  leaf, that leaf falls back to the Lichess `[%eval]`.

Do **not** require a real Stockfish binary in the unit tests. If any end-to-end engine smoke test is
added, gate it on binary availability (skip when absent).

## Risks / notes

- **Non-determinism:** real engine output varies with engine version, depth/time, and hardware.
  Keep all correctness tests on the pure core with stub providers; never assert exact engine scores.
- **Performance:** engine analysis is slow; dedup by FEN and a single long-lived engine process are
  important. Depth default should balance quality vs. runtime.
- **Binary availability:** Stockfish is not pip-installable as a binary; document the requirement
  and make the missing-binary path a graceful, well-signposted fallback/warning, never a crash.
- **Sign/format consistency:** the one subtle correctness point is that `format_eval` must be the
  exact inverse of the existing `[%eval]` parsing (white-POV pawns, `#n` mate). Pin with round-trip
  tests before wiring.
- **Scope creep:** the endgame boundary and multi-pv/lines are out of scope; single best-score eval
  only for the first version.

## Planned work

1. Create `chesstree/leaf_evaluator.py` with the pure core (`annotate_evals`, scope selection,
   `format_eval`, FEN de-dup) and the `EvalProvider` type — no engine yet.
2. Add `tests/test_leaf_evaluator.py` covering the pure core with a stub provider (scope selection,
   formatting round-trip, dedup, overwrite, `None` handling). Land 1–2 together, tests first per repo
   convention.
3. Add `make_engine_provider` (+ `EngineUnavailable`, `DEFAULT_DEPTH`, `DEFAULT_ENGINE`) wrapping
   `chess.engine.SimpleEngine.popen_uci` / `analyse` with clean lifecycle and error handling.
4. Wire the CLI: `--annotate-eval`, `--eval-scope` (default leaves+branch-points), `--engine`,
   `--eval-depth`/`--eval-time`; add `_maybe_annotate_evals` across all conversion functions; add
   CLI tests with a stubbed provider and the engine-unavailable warning path.
5. Wire the merge script: prefer-local-with-Lichess-fallback, evaluate merged terminal leaves once
   (dedup), single engine per run, graceful fallback; keep label format unchanged.
6. Update docs: `AGENTS.md` (new module row, CLI flags, eval-source/fallback semantics) and, if the
   merge behavior is user-facing, a note in the merge script docstring.
7. Update `README.md`: document the new `--annotate-eval` feature and its flags, and add a section
   on how to install Stockfish locally on macOS and Linux (the required engine binary).
8. Update `plans/opening-merge-plan.md`: move leaf-evaluation from *Deferred work* to done/linked,
   pointing at this plan and `chesstree/leaf_evaluator.py`.
9. Add a **real-Stockfish acceptance test** (like the divider's Lichess-corpus parity test) that
   wires an actual engine against the existing `lisperer-games-black.json` cache. 250 of its 336
   games carry inline `[%eval ...]` and a top-level `analysis` array from Lichess, giving a ready
   corpus of positions with reference evals. The test computes local Stockfish evals for those
   positions and compares against the Lichess evals. **Excluded from CI** (no Stockfish dependency
   in the pipeline for now): gate it behind a marker (e.g. `@pytest.mark.acceptance`) and/or a
   `skipif` on Stockfish-binary availability, and document how to run it manually (e.g.
   `pytest -m acceptance`) in the README/AGENTS.md. **Caveat:** Lichess and local Stockfish evals
   will not match exactly (different engine version, depth, hardware, and eval is inherently
   noisy) — assert an approximate/tolerance-based agreement (e.g. sign agreement and/or a centipawn
   band, special-casing mate scores), never exact equality.

## Open details (to settle during implementation, not blocking)

- Exact `--eval-scope` choice strings and how the default encodes "leaves + branch points".
- Default engine `Limit` (proposed `depth=20`) and the `--eval-depth` vs `--eval-time` precedence.
- Whether to expose `overwrite` on the CLI or always skip pre-existing `[%eval]`.
- Whether to factor `normalize_fen` into a shared helper (e.g. `chesstree/utils.py`) now that both
  the merge script and the evaluator need it.
