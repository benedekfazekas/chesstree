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

## [Unreleased] — 2026.2.dev0

### Added

- **d3html collapse/expand all toggle**: a single smart toolbar button lets users collapse or
  expand the entire tree at once. Its label and icon track the current state — `⊟ Collapse All`
  (all expanded), `⊞ Expand All` (all collapsed), or `◑ Collapse All` (mixed, after manual
  per-node adjustments). Clicking from a mixed state always collapses all. The button is hidden
  in deck view.

- **d3html orientation toggle**: the tree view now has a **↔ LR / ↕ TB** layout button
  group in the toolbar, letting users switch between left-to-right (default) and
  top-to-bottom tree orientations interactively in the browser. Manual node-drag positions
  are kept separately per orientation. No CLI or exporter changes required.

- **d3html root node removed**: the synthetic root node (which duplicated the page
  header's game metadata) is no longer rendered in the tree or deck views. All game
  information — White, Black, date, event, result — is shown in the page header only.

- **d3html game comment overlay**: when the PGN contains a game-level comment, a 💬
  button appears next to the title in the header. Clicking it (or clicking the overlay
  itself) toggles a full-width overlay showing the comment text.

- **d3html main-line sibling connectors**: consecutive main-line segment nodes are now
  joined by a visible continuation line, making the forward flow of the game clear even
  after the root node was removed.

- **d3html make ↕ TB layout default** the d3 only tree view defaults to the top to bottom
  layout

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
