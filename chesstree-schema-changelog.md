# chesstree Schema Changelog

All notable changes to the chesstree JSON/EDN schema are documented here.
This changelog tracks the **schema version** (the `schema_version` field in
the output), not the chesstree tool version.

The format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [1.0.0] — 2026-05-01

Schema declared **stable**. The backward compatibility contract defined in
[docs/schema.md §10](docs/schema.md#10-schema-versioning-and-compatibility)
is now in effect.

### Added
- Normative schema specification (`docs/schema.md`) covering all fields,
  types, variation semantics, NAG encoding, comment normalization, command
  annotations, fidelity rules, EDN differences, and versioning contract.
- Schema validation script (`tests/validate_schema.py`).

### No structural changes
The schema shape is identical to `0.1.0`. The version bump signals that
the specification is finalized and the stability contract applies.

## [0.1.0] — 2026-03-25

Initial versioned schema, introduced after the breaking design changes in
issues #4–#7.

### Added
- `schema_version` field as the first key in every JSON/EDN document.
- `fen_before` and `fen_after` on every move entry (replaced the old `fen`
  field). (#4)
- `branch_fen` on variation wrappers. (#5)
- `nags` as a single `{ code: symbol }` dict (replaced the old list-of-dicts
  encoding). (#7)
- Structured command annotation fields: `clock`, `emt`, `eval`, `arrows`
  (extracted from PGN `[%...]` comments).

### Removed
- `board_img_after` from move entries — board images are no longer embedded
  in JSON/EDN output. (#6)
- `fen` field (replaced by `fen_before` + `fen_after`). (#4)

### Changed
- NAG encoding from `[{code: symbol}]` list to `{code: symbol}` dict. (#7)
