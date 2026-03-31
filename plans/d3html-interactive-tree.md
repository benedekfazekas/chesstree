# Implementation Plan: D3 Interactive Tree (`d3html`) Output Format

## Problem

The current `dothtml` output uses Graphviz's DOT layout engine rendered via d3-graphviz (WebAssembly).
While functional, it produces rigid, non-interactive output: nodes cannot be moved, subtrees cannot
be collapsed/expanded, and the Graphviz HTML-table labels constrain visual styling.

## Prerequisite: Revert Hover Commit

Before starting this work, revert commit `8665095` ("Add per-move hover board images to dothtml
output"). The hover feature adds significant complexity to the DOT/dothtml pipeline (a third
`hover_images` return value threaded through `export_dot`, anchor-based hrefs in DOT labels, a
floating div overlay in the template, and the `-a` CLI flag). This kind of interactive feature is
better suited to the d3html format where it can be implemented natively with D3 event handlers
and foreignObject HTML, rather than bolted onto Graphviz's static layout.

Reverting keeps dothtml lean and focused on what Graphviz does well (static graph layout), and
positions d3html as the clear upgrade path for users who want interactivity. The hover board
feature will be implemented properly in d3html Phase 2 (template).

After the revert:
- `export_dot()` returns `tuple[str, dict[str, str]]` (DOT string + inline images only)
- `export_dothtml()` has no `hover` parameter
- The `-a / --hover-for-all-moves` CLI flag is removed
- `{{CHESSTREE_HOVER_DATA}}` template placeholder is removed

## Proposed Solution

Add a new `d3html` output format that renders chess game trees using D3.js `d3.tree()` with SVG
`<foreignObject>` HTML nodes. This gives us:

- **Collapse/expand** subtrees to focus on specific variations
- **Drag nodes** to rearrange the layout (whole subtree moves together)
- **Zoom/pan** with `d3.zoom()`
- **Rich HTML nodes** with full CSS control — moves, NAGs, comments, board images all rendered as
  native HTML inside each node
- **Animated transitions** when collapsing/expanding or rearranging
- **Hover boards** — per-move board popups, implemented natively with D3 (replaces the reverted
  dothtml hover feature)

The existing `dot` and `dothtml` formats remain unchanged.

## Architecture

```
                          ┌──────────────────────────┐
  chess.pgn.Game ────────▶│  d3tree_exporter.py       │
                          │  Game → JSON tree dict    │
                          │  + image SVG dict         │
                          │  + hover SVG dict         │
                          └──────────┬───────────────┘
                                     │
                                     ▼
                          ┌──────────────────────────┐
                          │  d3html_exporter.py       │
                          │  JSON + template → HTML   │
                          │  placeholder substitution │
                          └──────────┬───────────────┘
                                     │
                                     ▼
                          ┌──────────────────────────┐
                          │  d3html_default.html      │
                          │  D3 tree renderer         │
                          │  (collapse, drag, zoom)   │
                          └──────────────────────────┘
```

Compared to the current dothtml pipeline (`Game → DOT string → d3-graphviz → SVG`), this replaces
the intermediate DOT representation with a JSON tree and replaces the Graphviz layout engine with
D3's `d3.tree()` (Reingold-Tilford algorithm).

## JSON Tree Structure

The D3 renderer consumes a JSON tree embedded in the HTML. Each node represents a **block** — a
run of moves between branch points or comments (same grouping logic the DOT exporter uses).

```json
{
  "type": "root",
  "title": "White vs Black",
  "headers": {
    "White": "Player A", "Black": "Player B",
    "Date": "2025.01.01", "Result": "1-0",
    "Event": "...", "Site": "...", "ECO": "...", "Opening": "..."
  },
  "gameComment": "Introductory comment (PGN command annotations stripped)",
  "children": [
    {
      "type": "segment",
      "isVariation": false,
      "edgeLabel": null,
      "moves": [
        {
          "num": "1.",
          "san": "e4",
          "nag": null,
          "nagClass": null,
          "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        },
        {
          "num": "1…",
          "san": "c6",
          "nag": "!",
          "nagClass": "nag-good",
          "fen": "rnbqkbnr/pp1ppppp/2p5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
        }
      ],
      "comment": "Human-readable comment text (annotations stripped)",
      "image": "n3a8f1c2.svg",
      "hoverFens": { "n3a8f1c2": "fen_string", "n7b2e4d1": "fen_string" },
      "children": [
        { "type": "segment", "isVariation": false, "...": "..." },
        { "type": "segment", "isVariation": true, "edgeLabel": "2. Nc3", "...": "..." }
      ]
    }
  ]
}
```

Key design choices:
- **Blocks, not individual moves** — same as DOT exporter, a node represents a group of consecutive
  moves. Blocks split at comments and branch points.
- **`isVariation`** flag distinguishes main line continuations from alternative branches (controls
  edge styling: solid vs dashed).
- **`edgeLabel`** on variation nodes shows the diverging move on the connecting edge.
- **`image`** is the filename of an SVG board image (or `null`). Same image-mode logic as DOT:
  `variations`, `commented`, `all`, `none`.
- **`hoverFens`** per-node dict of fenhash→FEN for hover board popups (when `--hover-for-all-moves`
  is used). Only populated when hover mode is enabled.
- **NAG classes** use CSS class names (`nag-good`, `nag-blunder`, etc.) instead of inline hex colors,
  giving the template full control over styling.

## Template Placeholders

The D3 HTML template will use these placeholders:

| Placeholder | Content |
|---|---|
| `{{CHESSTREE_TITLE}}` | Game title string (same as dothtml) |
| `{{CHESSTREE_TREE_DATA}}` | JSON tree object, escaped for JS backtick literal |
| `{{CHESSTREE_IMAGES}}` | Image registration calls or metadata |
| `{{CHESSTREE_HOVER_DATA}}` | `hoverEnabled` flag + `hoverImages` dict (d3html only; removed from dothtml by revert) |

The JSON tree data is embedded inside a JS template literal and parsed with `JSON.parse()`:

```javascript
const treeData = JSON.parse(`{{CHESSTREE_TREE_DATA}}`);
```

This requires the same JS template literal escaping as DOT embedding: `\` → `\\`, `` ` `` → `` \` ``,
`${` → `\${`.

## Shared Utilities

Several pieces of logic are needed by both the DOT exporter and the new D3 tree exporter. Currently
these are private to `dot_exporter.py`. Before building the D3 exporter, extract them to shared
locations:

| What | Current Location | Proposed Location |
|---|---|---|
| NAG color/class map | `dot_exporter._NAG_COLORS` | `utils.py` — as both a color map and a CSS-class map |
| NAG priority order | `dot_exporter._ASSESSMENT_NAGS_PRIORITY` | `utils.py` |
| NAG symbol lookup | `dot_exporter._nag_symbol()` | `utils.py` |
| Block grouping | `dot_exporter._group_into_blocks()` | `utils.py` or new `tree_utils.py` |
| Node ID from FEN | `dot_exporter._DotBuilder._node_id()` | `utils.py` |
| SVG board generation | `dot_exporter._DotBuilder._ensure_image()` | `utils.py` or new `board.py` |
| Image mode decision | `dot_exporter._DotBuilder._block_needs_image()` | `utils.py` or new `tree_utils.py` |
| Move number formatting | inline in DOT exporter | `utils.py` |

After extraction, update the DOT exporter to import from the shared location. This is not a
refactor for its own sake — it's a prerequisite for the D3 exporter to reuse this logic without
duplication.

---

## Implementation Phases

### Phase 0: Revert Hover Commit + Extract Shared Utilities

**Step 0a: Revert commit `8665095`**

```bash
git revert 8665095
```

Verify all tests pass after the revert. This removes the hover feature from DOT/dothtml and
simplifies `export_dot` back to returning `tuple[str, dict[str, str]]`.

**Step 0b: Extract shared utilities**

Move reusable logic out of `dot_exporter.py` into shared modules so both DOT and D3 exporters
can use it.

**Files changed:**
- `chesstree/utils.py` — add NAG maps, node ID, move formatting
- `chesstree/dot_exporter.py` — import from `utils.py` instead of private definitions
- Tests must continue to pass after extraction (no behavior change)

### Phase 1: D3 Tree Exporter (`chesstree/d3tree_exporter.py`)

New module that converts `chess.pgn.Game` → JSON tree dict + image dicts.

**Core class:** `_D3TreeBuilder` (mirrors `_DotBuilder` structure)

**Responsibilities:**
- Walk the game tree, splitting main line at branch points
- Group moves into blocks (using shared block-grouping logic)
- Build JSON tree nodes with moves, comments, NAGs, image refs
- Generate board SVG images based on image modes
- Collect hover FENs when hover mode is enabled

**Public function:**
```python
def export_d3tree(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    hover: bool = False,
) -> tuple[dict, dict[str, str], dict[str, str]]:
    """Return (tree_dict, images, hover_images)."""
```

Note: the `hover` parameter and third return value (`hover_images`) exist only on the D3 tree
exporter. After the hover revert, the DOT exporter no longer has this concept — hover boards are
exclusively a d3html feature.

**Tests:** `tests/test_d3tree_exporter.py`
- Tree structure correctness (root, segments, variations, nesting)
- Block grouping produces expected node count
- NAG classes assigned correctly
- Image modes: none/all/variations/commented produce correct `image` fields
- Hover mode populates `hoverFens`
- Comments have PGN command annotations stripped
- Edge labels present on variation nodes
- Node IDs are stable (MD5 of FEN)

### Phase 2: D3 HTML Template (`chesstree/templates/d3html_default.html`)

Self-contained HTML file with embedded D3.js that renders the JSON tree interactively.

**Starting point:** the working POC at `/tmp/chesstree_d3_poc.html`, evolved with:

**Rendering features:**
- `d3.tree()` horizontal (LTR) layout with `nodeSize` tuned for chess content
- SVG `<foreignObject>` nodes containing styled HTML cards
- Move text with move numbers, NAG symbols + CSS coloring
- Italic comments below move blocks
- Board images (`<img>` tags referencing external SVGs)
- Root node with game headers and game-level comment
- Edge labels on variation links
- Variation edges: dashed stroke, accent color

**Interaction features:**
- **Collapse/expand**: click a node to toggle its subtree; smooth animated transitions
- **Drag**: drag a node to reposition its entire subtree; 5px dead-zone to distinguish from click;
  links and edge labels update in real-time
- **Zoom/pan**: `d3.zoom()` on the SVG background; scroll to zoom, drag background to pan
- **Reset layout**: press `R` to re-run the tree layout (undoes all manual drags)
- **Hover boards** (when enabled): mouseover a move shows a board popup near the cursor

**Styling:**
- Dark theme (can be refined later; potentially offer light/dark toggle)
- Node cards: rounded corners, subtle shadow, accent border on hover
- Visual cues: collapsed nodes get dashed border + "▶ N hidden" indicator
- Dragging nodes get a glow effect and `grabbing` cursor
- Help bar at bottom summarising interactions

**Template placeholders:** all four from the table above, validated on load.

### Phase 3: D3HTML Exporter (`chesstree/d3html_exporter.py`)

Thin orchestration module (mirrors `dothtml_exporter.py`).

**Public function:**
```python
def export_d3html(
    game: chess.pgn.Game,
    image_modes: frozenset[str] = frozenset(["variations"]),
    board_img_for_black: bool = False,
    template_path: pathlib.Path | None = None,
    hover: bool = False,
) -> tuple[str, dict[str, str]]:
    """Return (html_string, images_dict). Caller writes SVG files."""
```

**Steps:**
1. Call `export_d3tree()` to get `(tree_dict, images, hover_images)`
2. Load template (custom or default `d3html_default.html`)
3. Validate all required placeholders are present
4. Build substitution values:
   - Title: reuse `_game_title()` (import from `dothtml_exporter` or extract to `utils.py`)
   - Tree data: `json.dumps(tree_dict)` → `_escape_js_template_literal()`
   - Images: build image metadata (filenames for external SVG loading)
   - Hover data: `hoverEnabled` flag + `hoverImages` dict (inline SVG strings)
5. Substitute placeholders and return

**Tests:** `tests/test_d3html_exporter.py`
- Returns valid HTML string
- Title substituted correctly
- Tree data embedded and parseable as JSON
- Custom template support
- Missing placeholder raises `ValueError`
- JS template literal escaping (backticks, `${`, backslashes)
- Hover mode: enabled/disabled flags correct
- Image dict returned for caller to write

### Phase 4: CLI Integration

**File changed:** `chesstree/cli.py`

- Add `"d3html"` to the format choices
- Add dispatch function `game_to_d3html()` (parallel to `game_to_dothtml()`)
- Same flags apply: `--images`, `-b/--forblack`, `--template`
- Add `-a/--hover-for-all-moves` flag — now exclusive to d3html (not available for dot/dothtml)
- When output is a file: write SVGs alongside the HTML (same convention as dothtml)
- When output is stdout: emit HTML only (same convention as dothtml)

**Tests:** update `tests/test_cli.py`
- `d3html` format accepted
- Dispatch calls `export_d3html`
- SVG files written when output is a file
- `--template` flag works with d3html

### Phase 5: Functional / Integration Tests

**File:** `tests/test_functional.py` (extend existing)

- All three sample PGNs (`hillbilly_v3.pgn`, `lisperer_vs_verenitach.pgn`,
  `lichess_study_caro-kann-exchange-sample3.pgn`) produce valid d3html output
- Output contains expected D3 library references
- JSON tree data is valid JSON when extracted from HTML
- Image modes produce correct number of SVG files
- Hover mode embeds hover data in HTML

---

## Layout Considerations

The current DOT exporter forces the main line horizontally using `rank=same`, with variations
branching downward. `d3.tree()` uses the Reingold-Tilford algorithm which produces a standard
hierarchical layout (parent → children, left-to-right for horizontal orientation).

For the initial implementation, use the **standard `d3.tree()` horizontal layout**. This is
natural for chess variations: the main line flows left-to-right, and variations branch off
vertically. The POC demonstrates this works well visually.

A custom "main line spine" layout (main line as a single horizontal row with variations
hanging below) could be explored as a future enhancement if the standard layout proves
insufficient for very wide trees.

## Open Questions

1. **Image embedding strategy**: External SVG files (current approach) vs inline data-URI SVGs
   in the JSON tree. External files keep the HTML smaller but require a directory of SVGs alongside
   it. Inline keeps everything in one file. **Recommendation**: start with external files (matches
   current dothtml behavior), consider an `--inline-images` flag later.

2. **Light/dark theme**: The POC uses a dark theme. Should we offer a toggle, or match dothtml's
   light default? **Recommendation**: ship dark (it looks better for chess boards), add a toggle
   as a follow-up.

3. **Template customisation depth**: Should custom templates be able to override the entire D3
   renderer, or just CSS variables? **Recommendation**: same approach as dothtml — custom templates
   replace the entire HTML, must contain all required placeholders.

---

## Dependency Impact

No new Python dependencies. D3.js v7 is loaded from CDN in the template (same as current dothtml).
The `d3-hierarchy` module is part of the D3 v7 bundle.

## File Summary

| File | Action |
|---|---|
| `chesstree/utils.py` | Extend with shared NAG/block/ID utilities |
| `chesstree/dot_exporter.py` | Import shared utilities (no behavior change) |
| `chesstree/d3tree_exporter.py` | **New** — Game → JSON tree + images |
| `chesstree/d3html_exporter.py` | **New** — JSON tree + template → HTML |
| `chesstree/templates/d3html_default.html` | **New** — D3 interactive tree renderer |
| `chesstree/cli.py` | Add `d3html` format + dispatch |
| `tests/test_d3tree_exporter.py` | **New** — JSON tree exporter tests |
| `tests/test_d3html_exporter.py` | **New** — HTML exporter tests |
| `tests/test_cli.py` | Extend with d3html tests |
| `tests/test_functional.py` | Extend with d3html end-to-end tests |
