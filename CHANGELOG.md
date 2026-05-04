# chesstree Changelog

All notable changes to the **chesstree tool** are documented here.
This changelog tracks the **tool version** (the `version` field in `pyproject.toml`),
not the JSON/EDN schema version.

> **Schema changes** are tracked separately in
> [`chesstree-schema-changelog.md`](chesstree-schema-changelog.md).
> A tool version bump does not imply a schema version bump, and vice versa.
> The schema version is reported by `chesstree --version` alongside the tool version.

The format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [2026.1] — 2026-05-04

First public release on PyPI.

### Added

- **Output formats**: PGN → JSON, EDN, GraphViz DOT, and interactive HTML (`dothtml`)
- **JSON/EDN exporter**: full game tree with moves, variations, NAGs, comments, FENs,
  and structured PGN command annotations (`clock`, `emt`, `eval`, `arrows`)
- **JSON parser**: round-trips chesstree JSON back to a `chess.pgn.Game` object
- **DOT exporter**: move tree as a GraphViz `digraph`; moves grouped into blocks,
  NAG symbols coloured per severity, comments on edge labels
- **dothtml exporter**: self-contained interactive HTML viewer powered by d3-graphviz:
  the game tree is rendered as a left-to-right digraph
- **d3html exporter**: self-contained interactive HTML viewer built on d3 hierarchy —
  includes tree view and animated deck view with pinch-to-zoom
  a separate layout engine from dothtml that renders the game tree as a collapsible
  D3 tree; supports per-move hover board images (`--hover-for-all-moves`)
- **Board image modes**: `none`, `all`, `variations` (default), `commented` —
  controlable per export; SVG boards generated via `python-chess`
- **`--version`**: reports tool version and current schema version
- **CalVer**: version scheme `YYYY.N[.devN]` adopted (`2026.1.dev0`)
- **GitHub Actions CI**: runs the full test suite on every push and pull request

### Schema

The tool ships with schema **1.2.0**. See
[`chesstree-schema-changelog.md`](chesstree-schema-changelog.md) for the full
schema history (`0.1.0` → `1.0.0` → `1.1.0` → `1.2.0`).

### Security

- JS template-literal content in dothtml output is escaped to prevent PGN
  comments or player names from injecting JavaScript into generated HTML files
- HTML special characters in DOT node/edge labels are escaped
