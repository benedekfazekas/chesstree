# Opening-PGN merge plan

This file mirrors the working plan in the session plan file so the design can also live under `plans/`.

## Scope

Build a standalone repository script that can fetch or read source games, filter them for a requested starting position, and combine the surviving games into one PGN:
- each input game becomes a variation
- each variation is cut at the supplied opening/end-of-opening marker
- each leaf comment lists the source games for that leaf and the engine evaluation for the leaf position

The immediate focus is lichess.org acquisition. Chess.com and local-directory acquisition remain deferred.

The expected downstream use is `d3html` visualization, so the merged PGN should preserve standard PGN variations and move comments that the existing D3 export path can already render.

## Chosen direction

Implement the first version as a standalone repository script.

## Why this is feasible

- the project already uses `python-chess` game trees and variation APIs
- move-level eval annotations already round-trip through the JSON exporter/parser path
- no existing module owns multi-game merge logic, so a dedicated script is a good first home
- `d3html` can keep working as long as the merged output stays a normal PGN with standard variations and comments
- lichess user-game export can return NDJSON with full PGN, analysis data, opening metadata, and `division` plies marking where the opening ends
- the only missing piece on the acquisition side is client-side filtering for the requested starting position

## Lichess acquisition plan

- use `GET /api/games/user/{username}` as the first acquisition path
- request NDJSON rather than plain PGN, because `division` is only exposed in JSON
- request enough fields to normalize games in one pass: `moves`, `evals`, `division`, `opening`, `pgnInJson`, and `tags`
- stream the response and normalize each line independently
- map `division.middle` to the opening cutoff ply
- map the eval for that ply from the `analysis` array
- filter client-side for the requested starting position
- then pass the normalized games into the merge logic

## Planned work

1. Define the normalized source-game contract, including source label, cutoff ply, and leaf eval extraction
2. Design the lichess acquisition path around streamed NDJSON export
3. Define the starting-position filter format and matching rules
4. Normalize each accepted source PGN into an opening slice ending at the cutoff node
5. Merge slices into one shared PGN tree with variations
6. Aggregate source-game labels and evals at each merged leaf
7. Serialize the merged game back to PGN
8. Add targeted tests for acquisition normalization, branching, duplicate leaves, invalid input handling, and `d3html` compatibility of the merged PGN

## Current decisions

- first version lives as a standalone repository script
- the opening cutoff is marked on the cutoff move via a dedicated PGN command annotation, e.g. `[%opening_end]`
- if several games reach the same leaf and somehow disagree on eval, retain the per-game eval differences in the leaf comment
- if some games do not fully share the intended opening, merge from the true common prefix when possible; otherwise skip those games with a warning
- keep leaf annotations inside standard PGN move comments so the existing `d3html` exporter can visualize them without a new metadata channel
- for lichess, use the NDJSON export path rather than plain PGN, because it includes both engine analysis and the opening/middlegame division metadata

## Visualization note

Because the end goal is likely `d3html`, leaf-comment formatting is part of the feature design rather than a cosmetic detail. The combined PGN should stay compact and readable enough that long source-game lists or eval summaries do not make the rendered tree unusable.

## Deferred acquisition work

- chess.com acquisition plan
- local-directory PGN acquisition plan
