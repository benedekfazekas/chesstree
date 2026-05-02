# chesstree JSON/EDN Schema Specification

**Schema version:** `1.1.0`

This document is the normative specification for the JSON and EDN output produced
by `chesstree`. It defines every field, its type, whether it is required or
optional, and the semantic rules that govern the data. External consumers should
rely on this specification — not on implementation details in the source code —
when building parsers or tools that read chesstree output.

The EDN serialisation is structurally identical to JSON; only the surface syntax
differs. All rules in this document apply to both formats. See
[§9](#9-edn-serialisation-differences) for a complete list of EDN-specific
differences.

---

## Table of contents

1. [Top-level object](#1-top-level-object)
2. [Headers](#2-headers)
3. [Move entry](#3-move-entry)
4. [Variation wrapper](#4-variation-wrapper)
5. [NAGs](#5-nags)
6. [Comments](#6-comments)
7. [Command annotations](#7-command-annotations)
8. [Fidelity rules](#8-fidelity-rules)
9. [EDN serialisation differences](#9-edn-serialisation-differences)
10. [Schema versioning and compatibility](#10-schema-versioning-and-compatibility)

---

## 1. Top-level object

The top-level value is a JSON object (EDN map) with four required fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | string | **yes** | SemVer version of this schema (currently `"1.1.0"`). |
| `headers` | object | **yes** | PGN header tag pairs. May be empty (`{}`) if headers were suppressed. |
| `moves` | array | **yes** | Ordered list of [move entries](#3-move-entry) and [variation wrappers](#4-variation-wrapper). |
| `result` | string \| null | **yes** | Game termination marker: `"1-0"`, `"0-1"`, `"1/2-1/2"`, `"*"`, or `null`. |

**Field ordering.** `schema_version` is always the first key. The remaining
keys follow in the order shown above. Consumers should not depend on key
ordering.

**EDN key names.** In EDN, keys are Clojure-style keywords with hyphens
replacing underscores: `:schema-version`, `:headers`, `:moves`, `:result`.

### `result` vs `headers["Result"]`

Both fields carry the game result. They are intentionally redundant:

- `headers["Result"]` is present when headers are included in the export and
  the PGN contains a `Result` tag. It faithfully mirrors the PGN header.
- `result` is always present (it may be `null` only when the PGN has no
  termination marker). It is a convenience field for consumers that do not
  want to inspect headers.

When both are present they will have the same value. When headers are
suppressed (`headers: {}`), `result` is the only source.

### Unknown top-level keys

Consumers **must** ignore top-level keys they do not recognise. Future minor
versions may add new optional top-level fields.

---

## 2. Headers

`headers` is a JSON object whose keys and values are both strings. The keys
correspond to PGN tag names (`Event`, `Site`, `White`, `Black`, etc.) and
the values to their tag values.

| Property | Rule |
|----------|------|
| Key set | Arbitrary. The PGN Seven Tag Roster (`Event`, `Site`, `Date`, `Round`, `White`, `Black`, `Result`) is conventional but not mandatory. Any tag present in the source PGN may appear. |
| Value type | Always `string`. |
| Empty headers | Permitted. An empty object `{}` means headers were suppressed during export. |

### The `Comment` header

The PGN comment that precedes the first move (the "game comment") is stored as
`headers["Comment"]`. This is not a PGN tag — it is a chesstree convention for
preserving game-level commentary that has no standard PGN header slot.

- Present only when the PGN has a comment before move 1 **and** comments are
  enabled during export.
- The value is the raw comment string. PGN command annotations (e.g. `[%clk]`)
  within a game comment are preserved as-is — they are **not** stripped at the
  game-comment level (unlike move-level comments; see §6).

---

## 3. Move entry

Each element of the `moves` array (and of nested variation arrays) is either a
**move entry** or a [variation wrapper](#4-variation-wrapper). A move entry is
a JSON object with the following fields:

### Required fields

Every move entry contains these six fields:

| Field | Type | Description |
|-------|------|-------------|
| `move_number` | integer | PGN move number (fullmove counter). |
| `turn` | string | `"white"` or `"black"`. |
| `san` | string | Standard Algebraic Notation for the move (e.g. `"Nf3"`, `"O-O"`, `"e8=Q"`). |
| `uci` | string | UCI notation for the move (e.g. `"g1f3"`, `"e1g1"`, `"e7e8q"`). |
| `fen_before` | string | FEN of the board position **before** this move is played. |
| `fen_after` | string | FEN of the board position **after** this move is played. |

### Optional fields

These fields are present only when the move carries the corresponding
annotation. When absent, the consumer should treat the value as "not
available" — **not** as an empty list or zero.

| Field | Type | Condition |
|-------|------|-----------|
| `comments` | array of strings | Present when the move has human-readable commentary. See [§6](#6-comments). |
| `nags` | object | Present when the move has NAG annotations. See [§5](#5-nags). |
| `clock` | number (float) | Present when a `[%clk]` annotation exists. Value is seconds remaining. |
| `emt` | number (float) | Present when a `[%emt]` annotation exists. Value is elapsed seconds. |
| `eval` | object | Present when a `[%eval]` annotation exists. See [§7](#7-command-annotations). |
| `arrows` | array of objects | Present when `[%csl]` / `[%cal]` annotations exist. See [§7](#7-command-annotations). |

### Unknown keys on move entries

Consumers **must** ignore keys they do not recognise. Future minor versions
may add new optional fields to move entries.

---

## 4. Variation wrapper

A variation wrapper is a JSON object that appears **inline** in the `moves`
array (or in a nested variation array). It represents an alternative line
branching from the position before the preceding move entry.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `variation` | array | **yes** | A list of move entries and nested variation wrappers. |
| `branch_fen` | string | **yes** | FEN of the board position from which this variation's moves are played. |
| `comments` | array of strings | no | Comments that appear before the first move of this variation. See [§6](#6-comments). |

### Placement rules

1. A variation wrapper **must not** be the first element of any moves array.
   It must always follow a move entry (or another variation wrapper that itself
   follows a move entry).

2. A variation wrapper represents an alternative to the **preceding move entry**
   in the same array. It branches from the position before that move — i.e.
   `branch_fen` equals the `fen_before` of the preceding move entry.

3. Multiple variation wrappers may follow the same move entry (representing
   multiple alternatives at the same branch point).

### Invariant

For any variation wrapper `v` at position `i` in an array, let `m` be the
nearest preceding move entry in the same array (at position `j < i`). Then:

```
v["branch_fen"] == m["fen_before"]
v["variation"][0]["fen_before"] == m["fen_before"]
```

### Nesting

Variation wrappers may contain further variation wrappers, to any depth. The
same placement and branching rules apply recursively.

---

## 5. NAGs

Numeric Annotation Glyphs are encoded as a single JSON object (EDN map) on the
move entry under the `nags` key.

### Shape

```json
"nags": {
  "<code>": "<symbol>" | null
}
```

- **Keys** are NAG codes as **strings** (e.g. `"1"`, `"14"`, `"146"`). JSON
  requires object keys to be strings; integer NAG codes are serialised to their
  decimal string form.
- **Values** are either a human-readable Unicode symbol string or `null` when
  no standard symbol exists for the given code.

### Standard NAG symbols

The following mappings are built into chesstree. NAG codes not listed here
produce `null` as the symbol value.

| Code | Symbol | Meaning |
|------|--------|---------|
| 1 | `!` | Good move |
| 2 | `?` | Mistake |
| 3 | `!!` | Brilliant move |
| 4 | `??` | Blunder |
| 5 | `!?` | Speculative move |
| 6 | `?!` | Dubious move |
| 7 | `□` | Forced / only move |
| 10 | `=` | Drawish position |
| 13 | `∞` | Unclear position |
| 14 | `⩲` | White slight advantage |
| 15 | `⩱` | Black slight advantage |
| 16 | `±` | White moderate advantage |
| 17 | `∓` | Black moderate advantage |
| 18 | `+-` | White decisive advantage |
| 19 | `-+` | Black decisive advantage |
| 22 | `⨀` | White zugzwang |
| 23 | `⨀` | Black zugzwang |
| 132 | `⇆` | White moderate counterplay |
| 133 | `⇆` | Black moderate counterplay |
| 134 | `⇆` | White decisive counterplay |
| 135 | `⇆` | Black decisive counterplay |
| 136 | `⨁` | White moderate time pressure |
| 137 | `⨁` | Black moderate time pressure |
| 138 | `⨁` | White severe time pressure |
| 139 | `⨁` | Black severe time pressure |
| 146 | `N` | Novelty |

### Omission rule

When a move has no NAG annotations, the `nags` key is absent from the move
entry — it is **not** present as an empty object.

### Round-trip note

Because JSON keys are strings, a consumer that needs the integer NAG code must
parse the key (e.g. `int("14")` → `14`). The `json_parser` module handles this
automatically.

---

## 6. Comments

Human readable comments are stored as a list of strings under the `comments` key on both
move entries and variation wrappers.

### Shape

```json
"comments": ["First comment.", "Second comment."]
```

Each string is one normalized comment string in source order.

### Omission rule

When a move entry or variation wrapper has no comments of the relevant kind, the
`comments` key is **absent**. It is never present as an empty list `[]`.

### Normalization rules by context

#### Move-entry comments

For move entries, each string corresponds to one comment block from the PGN
source after normalization:

1. **PGN command annotations are stripped.** Any `[%...]` token (e.g.
   `[%clk 0:05:00]`, `[%eval 0.5]`, `[%csl Gd4]`) is removed from the
   comment text before storing. If stripping leaves an empty string, that
   comment element is dropped entirely.

2. **Whitespace is trimmed.** Leading and trailing whitespace is removed from
   each comment string after annotation stripping.

3. **Command annotation data is extracted separately.** The structured data
   from `[%clk]`, `[%eval]`, `[%emt]`, `[%csl]`, and `[%cal]` annotations
   is not discarded — it is placed into dedicated fields on the move entry
   (`clock`, `emt`, `eval`, `arrows`). See [§7](#7-command-annotations).

#### Variation-wrapper comments

On a variation wrapper, `comments` contains the comments that occur before the
first move of that variation (the PGN position modeled by python-chess as
`starting_comment`).

- Each string is kept in source order.
- Leading and trailing whitespace is trimmed.
- No command-annotation side-channel fields are emitted on variation wrappers.
- With current `python-chess`, adjacent variation-start comment blocks may
  already be merged into a single string before `chesstree` receives them.

### Multiple comments

A single move or variation start may carry multiple comment blocks. When they
are exposed separately by the parser, they are collected into the same
`comments` list in order of appearance.

---

## 7. Command annotations

PGN command annotations embedded in comments (`[%clk]`, `[%emt]`, `[%eval]`,
`[%csl]`, `[%cal]`) are extracted into dedicated structured fields on the move
entry. The original annotation text is stripped from the `comments` list (see
§6).

### `clock`

| Type | Description |
|------|-------------|
| number (float) | Seconds remaining on the player's clock, from `[%clk H:MM:SS]`. |

Example: `[%clk 0:05:00]` → `"clock": 300.0`

### `emt`

| Type | Description |
|------|-------------|
| number (float) | Elapsed move time in seconds, from `[%emt H:MM:SS]`. |

Example: `[%emt 0:00:03]` → `"emt": 3.0`

### `eval`

An object with one of two mutually exclusive shapes:

**Centipawn evaluation:**

```json
"eval": { "cp": 30, "depth": 20 }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cp` | integer | **yes** (in this variant) | Evaluation in centipawns from White's perspective. PGN stores decimal pawns; the exporter converts to integer centipawns (e.g. `0.30` → `30`). |
| `depth` | integer | no | Search depth, when present in the PGN annotation. |

**Mate evaluation:**

```json
"eval": { "mate": 3, "depth": 15 }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mate` | integer | **yes** (in this variant) | Moves to mate. Positive = White mates; negative = Black mates. |
| `depth` | integer | no | Search depth, when present in the PGN annotation. |

### `arrows`

An array of arrow/circle objects, extracted from `[%csl]` (colored squares) and
`[%cal]` (colored arrows) annotations.

```json
"arrows": [
  { "tail": "f3", "head": "e5", "color": "green" },
  { "tail": "d4", "head": "d4", "color": "red" }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `tail` | string | Source square in algebraic notation (`"a1"` – `"h8"`). |
| `head` | string | Target square. When `tail == head`, this is a colored square highlight (circle), not an arrow. |
| `color` | string | Color name (e.g. `"green"`, `"red"`, `"blue"`, `"yellow"`). |

### Omission rules

Each command annotation field is present only when the corresponding PGN
annotation exists on that move. Absent means "no data" — not zero, not empty
array.

---

## 8. Fidelity rules

The chesstree JSON/EDN format is a **normalized, structured projection** of PGN
data. It is not a lossless archive format. This section documents what is
preserved, what is transformed, and what is discarded.

### Preserved

| PGN element | JSON/EDN representation |
|-------------|-------------------------|
| Header tags (Seven Tag Roster and others) | `headers` object, key-value string pairs. |
| Move notation | `san` (SAN) and `uci` (UCI) on every move entry. |
| Board positions | `fen_before` and `fen_after` on every move entry. |
| Move order | Array ordering in `moves` and nested `variation` arrays. |
| Variations and nesting | Inline variation wrappers with `branch_fen`. |
| NAGs | `nags` dict with code → symbol mapping. |
| Move comments | Move-entry `comments` list (after stripping command annotations). |
| Variation-start comments | Variation-wrapper `comments` list. |
| Game result | `result` field and `headers["Result"]`. |
| Game-level comment | `headers["Comment"]`. |
| Clock annotations (`[%clk]`) | `clock` field (float seconds). |
| Elapsed time (`[%emt]`) | `emt` field (float seconds). |
| Engine evaluation (`[%eval]`) | `eval` object (`cp` or `mate`, optional `depth`). |
| Colored squares/arrows (`[%csl]`, `[%cal]`) | `arrows` array of `{tail, head, color}` objects. |

### Transformed

| PGN element | Transformation |
|-------------|----------------|
| Command annotations in move comments | Extracted into structured fields (`clock`, `emt`, `eval`, `arrows`) and stripped from move-entry `comments`. |
| FEN | Computed from the game tree and stored on each move entry, even if the PGN did not contain a FEN tag. |
| UCI notation | Computed from the move and board state; not present in PGN. |
| Comment grouping | Multiple PGN comment blocks associated with the same move or variation start are collected into a single `comments` list. |

### Discarded

| PGN element | Reason |
|-------------|--------|
| Unrecognised `[%...]` command annotations | Stripped from comments. No structured field is created for unknown commands. The raw text is lost. |
| Exact original segmentation of adjacent variation-start comment blocks | Current `python-chess` may merge adjacent comments before `chesstree` receives them, so a wrapper `comments` list can contain fewer elements than the source brace blocks. |

### Round-trip fidelity

A PGN → JSON → PGN round-trip through `chesstree` preserves: headers, all
moves (mainline and variations), NAGs, human comment text, clock/eval/arrow
annotations. The PGN output from a round-trip is
semantically equivalent to the original, though formatting (whitespace, line
breaks, and exact variation-start comment segmentation may differ.

---

## 9. EDN serialisation differences

The EDN output is structurally identical to JSON — same fields, same nesting,
same semantics. The differences are purely syntactic, arising from the EDN
data format conventions.

### Key naming

JSON keys use `snake_case` strings. In EDN, keys are Clojure-style **keywords**
with hyphens replacing underscores:

| JSON key | EDN key |
|----------|---------|
| `"schema_version"` | `:schema-version` |
| `"move_number"` | `:move-number` |
| `"fen_before"` | `:fen-before` |
| `"fen_after"` | `:fen-after` |
| `"branch_fen"` | `:branch-fen` |

Single-word keys become keywords directly (e.g. `"headers"` → `:headers`,
`"san"` → `:san`, `"clock"` → `:clock`).

Header tag names also become keywords: `"White"` → `:White`, `"Result"` →
`:Result`, `"Comment"` → `:Comment`. Note that header keywords preserve the
original PGN capitalisation.

### NAG keys

In JSON, NAG codes are string keys (e.g. `"14"`). In EDN, they are rendered as
**integer keys** since EDN supports non-string map keys natively:

```edn
;; JSON: "nags": { "14": "⩲", "1": "!" }
;; EDN:
:nags {14 "⩲" 1 "!"}
```

### Null values

JSON `null` becomes EDN `nil`:

```edn
;; JSON: "nags": { "8": null }
;; EDN:
:nags {8 nil}
```

### Boolean values

JSON `true`/`false` become EDN `true`/`false` (same literals, different format
context).

### String values

JSON strings use double quotes (`"..."`). EDN strings also use double quotes —
no difference.

### Collections

| JSON | EDN |
|------|-----|
| `{ ... }` (object) | `{ ... }` (map) |
| `[ ... ]` (array) | `[ ... ]` (vector) |

JSON uses commas between elements; EDN uses whitespace.

### Result field

The `result` field is a string in both formats. A JSON `null` result becomes
EDN `nil`.

### No structural differences

There are no fields that exist in one format but not the other. Every field
documented in §1–§8 appears in both JSON and EDN output with identical
semantics. The `schema_version` value is the same string in both formats.

---

## 10. Schema versioning and compatibility

### Version field

Every chesstree JSON/EDN document contains a `schema_version` field as the
first key of the top-level object. The value is a [SemVer 2.0.0](https://semver.org/)
string (e.g. `"0.1.0"`, `"1.1.0"`).

### Current version

The current schema version is **`1.1.0`**.

### Stability

The schema is **stable** as of `1.1.0`. The backward compatibility contract
below is now in effect.

### Version numbering rules

| Change type | Version bump | Examples |
|-------------|-------------|----------|
| Breaking: remove, rename, or retype a field | **MAJOR** | Removing `uci`, renaming `fen_before` → `fen` |
| Non-breaking: add optional field | **MINOR** | Adding a new optional field to move entries |
| Bug fix: correct a wrong value | **PATCH** | Fixing an incorrect FEN computation |

### Compatibility contract

1. **New optional fields may appear** in any minor release. Consumers **must**
   ignore keys they do not recognise (open content model).

2. **Existing fields will not be removed or renamed** without a major version
   bump. Deprecated fields will be documented for at least one minor release
   before removal.

3. The `schema_version` field itself will always be present as the first key
   of the top-level object.

4. The `json_parser` module will support the current major version and the
   previous major version, emitting a deprecation warning for the old one.

### Pre-versioned documents

Documents produced before the `schema_version` field was introduced lack the
field entirely. The `json_parser` module treats absent `schema_version` as
legacy (`"0.0.0"`) and parses them on a best-effort basis.

---

## Appendix A: Complete example

The following is a representative example generated from an annotated PGN game.
Optional fields are shown where they occur naturally.

```json
{
  "schema_version": "1.1.0",
  "headers": {
    "Event": "Dortmund Sparkassen",
    "Site": "Dortmund GER",
    "Date": "1997.07.04",
    "Round": "1",
    "White": "Vladimir Kramnik",
    "Black": "Anatoly Karpov",
    "Result": "1-0",
    "ECO": "A15",
    "Opening": "English Opening: Anglo-Indian Defense",
    "Comment": "This English Opening was played in Dortmund in 1997."
  },
  "moves": [
    {
      "move_number": 1,
      "turn": "white",
      "san": "Nf3",
      "uci": "g1f3",
      "fen_before": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
      "fen_after": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1"
    },
    {
      "move_number": 1,
      "turn": "black",
      "san": "Nf6",
      "uci": "g8f6",
      "fen_before": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1",
      "fen_after": "rnbqkb1r/pppppppp/5n2/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 2 2"
    },
    {
      "move_number": 2,
      "turn": "white",
      "san": "c4",
      "uci": "c2c4",
      "fen_before": "rnbqkb1r/pppppppp/5n2/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 2 2",
      "fen_after": "rnbqkb1r/pppppppp/5n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R b KQkq - 0 2"
    },
    {
      "move_number": 2,
      "turn": "black",
      "san": "b6",
      "uci": "b7b6",
      "fen_before": "rnbqkb1r/pppppppp/5n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R b KQkq - 0 2",
      "fen_after": "rnbqkb1r/p1pppppp/1p3n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R w KQkq - 0 3",
      "comments": ["Entering the Queen's Indian structure."]
    },
    {
      "move_number": 3,
      "turn": "white",
      "san": "g3",
      "uci": "g2g3",
      "fen_before": "rnbqkb1r/p1pppppp/1p3n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R w KQkq - 0 3",
      "fen_after": "rnbqkb1r/p1pppppp/1p3n2/8/2P5/5NP1/PP1PPP1P/RNBQKB1R b KQkq - 0 3",
      "nags": { "1": "!" },
      "comments": ["The fianchetto approach."]
    },
    {
      "variation": [
        {
          "move_number": 3,
          "turn": "white",
          "san": "d4",
          "uci": "d2d4",
          "fen_before": "rnbqkb1r/p1pppppp/1p3n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R w KQkq - 0 3",
          "fen_after": "rnbqkb1r/p1pppppp/1p3n2/8/2PP4/5N2/PP2PPPP/RNBQKB1R b KQkq - 0 3",
          "comments": ["The main alternative."]
        }
      ],
      "branch_fen": "rnbqkb1r/p1pppppp/1p3n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R w KQkq - 0 3",
      "comments": ["A quieter alternative for White."]
    }
  ],
  "result": "1-0"
}
```

> **Note:** this example is abridged for readability. A real export of a full
> game contains all moves, and optional fields appear only where the PGN source
> provides the corresponding annotations.

### EDN equivalent (excerpt)

```edn
{:schema-version "1.1.0"
 :headers {:Event "Dortmund Sparkassen"
           :White "Vladimir Kramnik"
           :Black "Anatoly Karpov"
           :Result "1-0"
           :Comment "This English Opening was played in Dortmund in 1997."}
 :moves [{:move-number 1
          :turn "white"
          :san "Nf3"
          :uci "g1f3"
          :fen-before "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
          :fen-after "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1"}
         {:move-number 1
          :turn "black"
          :san "Nf6"
          :uci "g8f6"
          :fen-before "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 1 1"
          :fen-after "rnbqkb1r/pppppppp/5n2/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 2 2"}]
 :result "1-0"}
```

---

## Appendix B: Move entry with command annotations

This example shows a move carrying clock, eval, and arrow annotations alongside
a human comment.

```json
{
  "move_number": 21,
  "turn": "black",
  "san": "Qd7",
  "uci": "e7d7",
  "fen_before": "3rr2k/p1p1qpp1/1pn1p2p/4P2P/3PRBQ1/b1PN2P1/P4P2/3R2K1 b - - 1 21",
  "fen_after": "3rr2k/p1pq1pp1/1pn1p2p/4P2P/3PRBQ1/b1PN2P1/P4P2/3R2K1 w - - 2 22",
  "nags": { "6": "?!" },
  "arrows": [
    { "tail": "f8", "head": "f8", "color": "green" },
    { "tail": "a3", "head": "f8", "color": "green" }
  ],
  "comments": [
    "Black opens a line for the bishop to retreat and protect the king, but it loses time and allows white to take the initiative."
  ]
}
```
