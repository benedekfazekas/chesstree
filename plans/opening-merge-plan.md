# Opening-PGN merge plan

This file mirrors the working plan in the session plan file so the design can also live under `plans/`.

## Scope

Build a standalone repository script that can fetch or read source games, filter them for a requested starting position, and combine the surviving games into one PGN:
- each input game becomes a variation
- each variation is cut at the locally computed opening/end-of-opening marker
- each leaf comment lists the source games for that leaf
- leaf-evaluation enrichment is deferred until after local `opening_end` ownership lands *(now implemented — see `chesstree/leaf_evaluator.py` and `plans/leaf-evaluation-plan.md`)*

The merged PGN starts from move 1. The pre-filter moves form a linear preamble; branching begins at
the filter position (where filtered games diverge in opening play). In the common case all filtered
games share the same move sequence up to the filter FEN, so the preamble is unambiguous. The rare
transposition edge case (different move orders reaching the same filter FEN) is noted below.

The immediate focus is owning `opening_end` locally and reusing that logic across lichess.org, Chess.com, and local-directory PGNs.

Before that longer-term ownership work, we will build a narrow Lichess-only POC that still uses
Lichess-provided `division` and leaf evaluation so we can validate the concept quickly and inspect
an early `d3html` output. This is a sequencing step, not a change to the long-term decisions below.

The expected downstream use is `d3html` visualization, so the merged PGN should preserve standard PGN variations and move comments that the existing D3 export path can already render.

## Chosen direction

Implement the first version as a standalone repository script.

## Early Lichess POC

This POC exists to validate the end-to-end concept early, before replacing remote metadata with
owned logic.

### POC must include

- Lichess acquisition only
- filtering games by the requested FEN
- optional `color` filter (`white`/`black`) passed directly to the Lichess API; omitted when not specified
- cutting each filtered game to the requested slice: start at the matched filter position and end
  at the temporary Lichess-provided `opening_end` cutoff
- temporarily using Lichess-provided `division` for `opening_end`; annotating the Lichess division
  ply with `[%opening_end]` even in the POC, for output-format consistency
  - `division.middle` is **0-based**: ply 0 = initial position, ply 1 = after white's first move, etc.
  - when `division.middle` is absent (game ended during the opening phase), fall back to the full
    game length as the opening cutoff — the last position of the game becomes the leaf; this is the
    correct semantic and must be kept in the final implementation
- leaf evaluation: Lichess embeds `[%eval ...]` annotations inline in the PGN move comments when
  `pgnInJson=true` and `evals=true` are requested; copy those comments as-is; if eval is absent at
  the leaf, it is simply absent — no separate handling of the top-level `analysis` array is needed
  in the POC
- the actual merge logic that combines the sliced source PGNs into one merged PGN
- the POC outputs the merged PGN; `d3html` is produced by running `chesstree` on it manually
- transposition handling (POC): if games reach the filter FEN via different move orders, pick one
  move order and keep all matching games (brush over the order difference); proper
  longest-common-prefix handling is a deferred improvement after the POC

### POC can defer

- Chess.com acquisition
- local-directory acquisition
- local ownership of `opening_end`
- local ownership of leaf evaluation — **landed** (`chesstree/leaf_evaluator.py`; see `plans/leaf-evaluation-plan.md`)
- move-prefix filtering, if FEN filtering is already sufficient for the POC
- broader cleanup or generalization work beyond what is needed to prove the concept

### POC outcome

- use the POC output to validate merge shape, leaf comment formatting, and general usability; run
  `chesstree` on the merged PGN to inspect the `d3html` output
- after the POC, keep the long-term plan unchanged: replace both remote division and remote
  leaf-evaluation dependence with logic owned in-repo

## Why this is feasible

- the project already uses `python-chess` game trees and variation APIs
- no existing module owns multi-game merge logic, so a dedicated script is a good first home
- `d3html` can keep working as long as the merged output stays a normal PGN with standard variations and comments
- the only missing piece on the acquisition side is client-side filtering for the requested starting position
- the filter should support both move-prefix and FEN input, with FEN treated as the more important first-class form
- FEN matching should use normalized position comparison rather than exact full-FEN equality
- Chess.com's public API is suitable for retrieving all public user games via an archives index plus monthly archive payloads that include `pgn`
- Lichess `lila` already computes the opening/middlegame split from board states alone, so the same logic can be reimplemented locally instead of being treated as remote metadata
- `python-chess` can compute the full board sequence and FENs for every move without adding a new dependency
- the same parsed-game contract can support remote APIs and local-directory PGNs once `opening_end` is computed in-repo

## Local opening-end divider plan

This section is the source of truth for how `opening_end` should be computed. The acquisition sections below should refer to this logic rather than to Lichess `division.middle`.

> **Status: LANDED.** The local divider is implemented in `chesstree/opening_divider.py`
> (`opening_end_ply`, `boards_from_game`, `annotate_opening_end`) as a faithful port of
> `scalachess Divider.scala` (opening/middlegame boundary only). Parity is verified against the
> 336-game Lichess corpus (`lisperer-games-black.json`): computed `opening_end_ply` matches
> `division.middle` exactly for every standard game, including the 8 games with no middlegame
> (both return `None`). See `tests/test_opening_divider.py`. The POC
> `scripts/merge_openings.py` now computes the cutoff via this module (no longer reads
> `division.middle`; `division=true` dropped from the Lichess request), and the `chesstree` CLI
> exposes it via the opt-in `--annotate-opening-end` flag (with a new `pgn → pgn` passthrough).
> Refer to `chesstree/opening_divider.py` from every acquisition source below.

### Current state

- the local divider (`chesstree/opening_divider.py`) is now the in-repo source of `opening_end`; the acquisition sources below reuse it
- the current codebase is otherwise centered on single-game parsing/exporting through `python-chess`
- `chesstree/json_exporter.py`, `chesstree/json_parser.py`, and `chesstree/dot_exporter.py` already show the patterns this feature will need: traversing PGN trees, deriving board/FEN states, attaching annotations/comments, and serializing normal PGN variations back out
- the previous version of this plan deferred local-directory acquisition and routed non-Lichess sources through Lichess to obtain division metadata

### Upstream research

- Lichess `lila` does not define the opening/middlegame boundary itself; `modules/game/src/main/Divider.scala` only caches and invokes `scalachess.Divider`
- the real logic lives in `scalachess/core/src/main/scala/Divider.scala` and works from board states alone, not from external opening metadata
- for the first split (`division.middle` / opening end), the first qualifying board ends the opening:
  - `majorsAndMinors(board) <= 10`
  - or `backrankSparse(board)`
  - or `mixedness(board) > 150`
- the later endgame threshold (`majorsAndMinors(board) <= 6`) is separate and stays out of scope for now
- upstream only considers some variants "division sensible"; the explicit variant policy for the
  first implementation here is **standard chess only** — Chess960 and other variants are out of scope

### Proposed approach

- introduce a small source-agnostic divider module (for example `chesstree/opening_divider.py`) that accepts a parsed game or a sequence of board states and returns the first `opening_end` ply/node
- variant policy: standard chess only; Chess960 and other variants are explicitly out of scope for the first implementation
- port the Lichess opening heuristics into `python-chess`, keeping the first implementation close to upstream so parity is testable before any simplification
- expose convenience helpers for:
  - computing `opening_end` from a game or move list
  - annotating the cutoff move with `[%opening_end]`
  - reusing the same detector from remote sources and local-directory PGNs
- change the acquisition flow so every source normalizes to "parsed PGN + metadata", then runs the local divider; no source should depend on Lichess `division.middle`
- remove the previous "import to Lichess to recover division" dependency from the Chess.com path
- explicitly defer leaf-evaluation sourcing so this slice can focus on local `opening_end` ownership and reuse across sources

### Notes and risks

- the main correctness risk is off-by-one mapping between upstream board indices and `python-chess` move nodes; unit tests for the divider (written as part of step 4 in Planned work) should pin this down before the divider is wired to any acquisition source
- `mixedness` is the least obvious heuristic, so the safest first step is a faithful port, then simplification only if behavior remains acceptable on representative fixtures
- the current repository dependencies are minimal (`python-chess` plus test tooling), so the plan should avoid introducing a new dependency just to compute `opening_end`

## Lichess acquisition plan

### POC-first exception

- for the initial proof of concept only, request NDJSON (not plain PGN), because `division` is
  only exposed in JSON; request fields: `moves`, `evals`, `division`, `opening`, `pgnInJson`, `tags`
- support an optional `color` parameter (`white`/`black`) forwarded directly to the Lichess API;
  omit from the request when not specified so both sides are returned by default
- use the Lichess-provided `division.middle` ply (0-based) as the opening cutoff; annotate it with
  `[%opening_end]` for output-format consistency with the post-POC approach
- when `division.middle` is absent, the game ended before reaching the middlegame; use the full
  game length as `opening_end_ply` so the last position becomes the leaf (do not skip these games)
- leaf evaluation: copy inline `[%eval ...]` annotations already embedded in the PGN move comments
  by Lichess; if eval is absent for a particular leaf, omit it silently — no separate use of the
  top-level `analysis` array
- in the POC, also implement the FEN filter, slice each filtered game from the matched position to
  the temporary cutoff, and run the real merge logic on those slices
- use this temporary path to produce an early merged PGN quickly
- once the concept is validated, replace this temporary dependence with the local divider and owned
  leaf-evaluation plan described elsewhere in this document *(both have since landed: divider in
  `chesstree/opening_divider.py`, leaf evaluation in `chesstree/leaf_evaluator.py`; see
  `plans/leaf-evaluation-plan.md`)*

### Post-POC Lichess plan

- use `GET /api/games/user/{username}` as the first acquisition path
- request a format that gives us PGN plus any useful source metadata; `division` is no longer required because the cutoff is computed by the local opening-end divider plan above
- stream the response and normalize each line independently
- filter client-side for the requested starting position
- compute `opening_end` locally using the divider section above
- then pass the normalized games into the merge logic

## Chess.com acquisition plan

- fetch archive URLs from `/pub/player/{username}/games/archives`
- fetch each monthly archive JSON
- parse each game's embedded `pgn`
- filter client-side for the requested starting position
- compute `opening_end` locally using the divider section above
- pass the filtered and normalized games directly into the merge logic; no Lichess import/re-export step is needed

## Local-directory acquisition plan

- accept PGN files from a local directory as another source type
- parse each game through the same normalization path as remote sources
- reuse the same starting-position filter and local opening-end divider
- pass the normalized games into the merge logic without any source-specific cutoff handling

## Planned work

1. Build a Lichess-only POC that uses Lichess `division` and leaf evaluation to validate the
   merged PGN shape and produce early `d3html` output
2. Within that POC, implement FEN-based filtering, slice each filtered game from the matched start
   position to the temporary cutoff, and merge those slices into one PGN
3. Define the normalized source-game contract, including source label and locally computed cutoff ply
4. Implement the local opening-end divider plan described above, including unit tests for the
   divider heuristics (off-by-one mapping, `mixedness`, `backrankSparse`) before wiring to any
   acquisition source — **done** (`chesstree/opening_divider.py`, `tests/test_opening_divider.py`;
   wired into `scripts/merge_openings.py` and exposed on the CLI via `--annotate-opening-end`)
5. Define the starting-position filter format and matching rules, supporting both move-prefix and FEN input with FEN as the priority
6. Wire Lichess, Chess.com, and local-directory sources through the same parsed-game contract before merge
7. Normalize each accepted source PGN into an opening slice ending at the locally computed cutoff node
8. Merge slices into one shared PGN tree with variations
9. Aggregate source-game labels at each merged leaf
10. Serialize the merged game back to PGN
11. Add integration tests covering acquisition normalization, branching, duplicate leaves, invalid
    input handling, and `d3html` compatibility of the merged PGN (divider unit tests are in step 4)

## Current decisions

- first version lives as a standalone repository script
- the opening cutoff is marked on the cutoff move via a dedicated PGN command annotation, e.g. `[%opening_end]`
- if some games do not fully share the intended opening, merge from the true common prefix when possible; otherwise skip those games with a warning
- keep leaf annotations inside standard PGN move comments so the existing `d3html` exporter can visualize them without a new metadata channel
- local `opening_end` logic is owned in-repo and reused for Lichess, Chess.com, and local-directory PGNs; Lichess `division.middle` is no longer a dependency
- variant policy: standard chess only; Chess960 and other variants are out of scope for the first implementation
- support both move-prefix and FEN filters; prioritize FEN support first
- for FEN matching, ignore bookkeeping-only differences such as move counters rather than comparing raw FEN strings verbatim
- keep Chess.com acquisition in scope, but compute the cutoff locally after filtering rather than through Lichess enrichment
- leaf-evaluation sourcing: implemented — locally computed via a UCI engine (Stockfish) in
  `chesstree/leaf_evaluator.py`; `scripts/merge_openings.py` prefers local engine eval and falls
  back to Lichess-embedded `[%eval ...]` when the engine is unavailable; CLI flags
  `--annotate-eval`, `--eval-scope`, `--engine`, and `--eval-depth` / `--eval-time` wired in
  `chesstree/cli.py`; see `plans/leaf-evaluation-plan.md`

## Visualization note

Because the end goal is likely `d3html`, leaf-comment formatting is part of the feature design rather than a cosmetic detail. The combined PGN should stay compact and readable enough that long source-game lists do not make the rendered tree unusable.

## Deferred work

> **Done — leaf-evaluation sourcing:** locally computed via a UCI engine (Stockfish) in
> `chesstree/leaf_evaluator.py` (pure core + convenience engine provider);
> `scripts/merge_openings.py` now prefers local engine eval and falls back to the
> Lichess-embedded `[%eval ...]` when the engine is unavailable; CLI flags `--annotate-eval`,
> `--eval-scope`, `--engine`, and `--eval-depth` / `--eval-time` are wired in `chesstree/cli.py`.
> Tracked in full in `plans/leaf-evaluation-plan.md`.

- transposition edge case: proper longest-common-prefix handling when games reach the filter FEN
  via different move orders (the POC picks one move order and keeps all matching games)
- leaf comment formatting: the final shape of the `Sources:` comment and whether long lists need
  truncation or special rendering will be assessed from the POC `d3html` output

## Open detail

No blocking design decision remains for the current planning slice. The main implementation details still to settle are the exact warning/error behavior for unsupported or partially matching games.
