# chesstree

A command-line tool for converting chess games between PGN, JSON, EDN, GraphViz DOT, and interactive HTML formats. It accepts PGN or chesstree JSON as input (auto-detected from the file extension) and can output JSON, EDN, PGN, DOT, dothtml, or d3html via the `-f`/`--format` flag. JSON output includes move number, SAN and UCI notation, FEN positions, comments, NAGs, and variations. DOT output models the game tree as a left-to-right digraph suitable for rendering with GraphViz tools. The `dothtml` format wraps the DOT graph in a self-contained browser viewer powered by [d3-graphviz](https://github.com/magjac/d3-graphviz), with pan, zoom, and board images included. The `d3html` format produces a purpose-built interactive D3.js tree viewer with collapsible nodes, variation highlighting, optional hover board images, and a dark-themed layout — no GraphViz dependency required.

## Output format

The tool produces a JSON (or EDN) object with four top-level keys: `schema_version`, `headers`, `moves`, and `result`. Each move entry carries SAN/UCI notation, FEN positions before and after, and optional annotations (comments, NAGs, clock, eval, arrows). Variations appear inline as `{ "variation": [ ... ], "branch_fen": "<FEN>" }` entries.

For the full normative specification — required vs optional fields, exact types, variation placement rules, NAG encoding, comment normalization, fidelity guarantees, and versioning contract — see **[docs/schema.md](docs/schema.md)**.

---

## Installation

### Prerequisites

- Python 3.9 or later
- `pip`

### Install from source (local)

Clone or download the repository, then install with pip:

```bash
git clone <repo-url> chesstree
cd chesstree
pip install .
```

The `chesstree` command will be added to your PATH automatically.

### Install into a virtual environment (recommended)

Using a virtual environment avoids polluting your global Python installation:

```bash
git clone <repo-url> chesstree
cd chesstree

python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate

pip install .
```

The `chesstree` command is available whenever the virtual environment is active.

---

## Usage

```
usage: chesstree [-h] [--version] -i INPUT [-o OUTPUT] [-f {json,edn,pgn,dot,dothtml,d3html}]
                 [--input-format {pgn,json}] [-b] [--images MODE [MODE ...]]
                 [--template FILE] [-a] [--no-move-highlight] [-c]

options:
  -h, --help                                     show this help message and exit
  --version                                      show program's version number and exit
  -i, --input INPUT                              Input file — PGN or chesstree JSON (use '-' for stdin)
  -o, --output OUTPUT                            Output file (default: stdout)
  -f, --format {json,edn,pgn,dot,dothtml,d3html} Output format: json (default), edn, pgn, dot, dothtml, or d3html
  --input-format {pgn,json}                      Override auto-detected input format
  -b, --forblack                                 Board images from Black's perspective (dot/dothtml/d3html)
  --images MODE [MODE ...]                       Image generation mode for dot/dothtml/d3html output (default: variations)
                                                 Choices: none, all, variations, commented.
                                                 'variations' and 'commented' may be combined.
                                                 SVG files are written alongside the output file;
                                                 stdout skips writing SVGs.
                                                 Has no effect on json/edn output.
  --template FILE                                Custom HTML template for dothtml or d3html output.
                                                 Must contain the required placeholders for the chosen format.
                                                 Only used with -f dothtml or -f d3html.
  -a, --hover-for-all-moves                      Embed per-move hover board images (d3html only).
                                                 Mouseover a move to see the board position in a popup.
  --no-move-highlight                            Disable last-move square highlighting on board images.
                                                 By default the from/to squares of the last move are
                                                 coloured on every board image (dot/dothtml/d3html).
  -c, --concise                                  Compact output, no pretty-printing (json/edn output only)
```

The input format is auto-detected from the file extension (`.pgn` → PGN, `.json` → chesstree JSON). Use `--input-format` to override this when reading from stdin or a file with an unusual extension.

Supported conversions:

| Input | `-f` / `--format` | Output |
|-------|-------------------|--------|
| PGN   | `json` (default)  | chesstree JSON |
| PGN   | `edn`             | chesstree EDN  |
| PGN   | `dot`             | GraphViz DOT   |
| PGN   | `dothtml`         | Self-contained d3-graphviz HTML viewer |
| PGN   | `d3html`          | Self-contained D3.js interactive tree viewer |
| JSON  | `pgn`             | PGN            |
| JSON  | `dot`             | GraphViz DOT   |
| JSON  | `dothtml`         | Self-contained d3-graphviz HTML viewer |
| JSON  | `d3html`          | Self-contained D3.js interactive tree viewer |

### Examples

Convert a PGN file to JSON:

```bash
chesstree -i game.pgn -o game.json
```

Convert a PGN file to EDN:

```bash
chesstree -i game.pgn -f edn -o game.edn
```

Print compact JSON to stdout:

```bash
cat game.pgn | chesstree -i - -c
```

Generate board images from Black's perspective (dot/dothtml output):

```bash
chesstree -i game.pgn -f dot -o game.dot -b
```

### Board image modes

The `--images` flag controls which segment nodes carry an SVG image row in DOT/dothtml output. It has no effect on JSON/EDN output (which never contains embedded images — use the `fen_after` field to generate board visuals with any chess library). The following modes are available:

| Mode | Description |
|------|-------------|
| `variations` | *(default)* Images at the last move of each line segment — see below |
| `all` | Every move gets an image |
| `commented` | Only moves that carry a comment get an image |
| `none` | No images at all (smallest output) |

`variations` and `commented` can be combined: `--images variations commented`.

#### The `variations` mode in detail

A chess game tree is naturally divided into **segments** — runs of moves along a single line until the game ends or the tree branches. The `variations` mode places one image at the **last move of each segment**:

- **End of a line** (no further moves) — the final move of the main line or of any variation always gets an image.
- **Branch point** — when a position has multiple continuations (e.g. a main move and one or more alternative variations), the first continuation (the main-line choice at that fork) is the last move of the current segment and gets an image. The alternatives each start their own segment and follow the same rule recursively.

This means images appear at the moments of decision — exactly where a reader is most likely to want to visualise the board — while keeping the output compact compared to `all`.

Generate images only at variation endpoints (default, dot/dothtml only):

```bash
chesstree -i game.pgn -f dot -o game.dot --images variations
```

Generate images for every move:

```bash
chesstree -i game.pgn -f dot -o game.dot --images all
```

Generate images only at commented moves:

```bash
chesstree -i game.pgn -f dot -o game.dot --images commented
```

Generate images at both variation endpoints and commented moves:

```bash
chesstree -i game.pgn -f dot -o game.dot --images variations commented
```

Omit all board images:

```bash
chesstree -i game.pgn -f dot -o game.dot --images none
```

### Last-move square highlighting

By default, board images colour the **from** and **to** squares of the last move, making it easy to see which piece moved. This applies to all image-bearing formats: `dot`, `dothtml`, and `d3html`.

Use `--no-move-highlight` to produce plain boards without any square colouring:

```bash
chesstree -i game.pgn -f dothtml -o game.html --no-move-highlight
chesstree -i game.pgn -f d3html  -o game.html --no-move-highlight
chesstree -i game.pgn -f dot     -o game.dot  --no-move-highlight
```

Convert a chesstree JSON file back to PGN:

```bash
chesstree -i game.json -f pgn -o game_restored.pgn
```

Export a PGN game to a GraphViz DOT file for visualisation:

```bash
chesstree -i game.pgn -f dot -o game.dot
```

Render the DOT file to SVG using GraphViz:

```bash
dot -Tsvg game.dot -o game.svg
```

Export from chesstree JSON to DOT:

```bash
chesstree -i game.json -f dot -o game.dot
```

### dothtml output — d3-graphviz browser viewer

The `dothtml` format produces a self-contained HTML file that renders the game tree interactively in a browser using [d3-graphviz](https://github.com/magjac/d3-graphviz). Board images are written as SVG files alongside the HTML file, which the browser loads by relative path.

```bash
# Generate HTML viewer + SVG images in ./output/
chesstree -i game.pgn -f dothtml -o output/game.html

# Open in browser
open output/game.html
```

The viewer includes a layout-engine selector (Dot, Circo, Fdp, …) and supports pan and zoom.

When writing to **stdout**, image references are included in the HTML but no SVG files are written:

```bash
chesstree -i game.pgn -f dothtml -o -
```

#### Custom HTML template (dothtml)

You can supply your own template with `--template`:

```bash
chesstree -i game.pgn -f dothtml --template my_template.html -o game.html
```

The template is plain HTML with three required placeholders:

| Placeholder | Replaced with |
|-------------|---------------|
| `{{CHESSTREE_TITLE}}` | Game title string (e.g. "White vs Black at 2024.01.01") |
| `{{CHESSTREE_IMAGES}}` | One `.addImage("./name.svg", "144px", "144px")` call per image |
| `{{CHESSTREE_DOT}}` | The raw DOT string — place inside a JS backtick template literal |

All three must be present or generation fails with an error listing the missing ones.

---

### d3html output — interactive D3.js tree viewer

The `d3html` format produces a self-contained HTML file with a purpose-built interactive tree viewer powered by [D3.js v7](https://d3js.org). Unlike `dothtml` it does not require GraphViz: the layout and rendering are done entirely in the browser.

```bash
# Generate HTML viewer + SVG board images in ./output/
chesstree -i game.pgn -f d3html -o output/game.html

# Open in browser
open output/game.html
```

Features of the viewer:

- **Tree view** (default) — a full interactive tree layout:
  - **Dark theme** with colour-coded nodes: main-line segments (blue) are visually distinct from variation segments (purple).
  - **Node headers** show the line type and move range, e.g. "Main line: 1–12" or "Variation: 8–10".
  - **Collapsible nodes** — click any node to hide its variation children while keeping the main-line continuation visible. A badge in the header shows how many nodes are hidden. Ctrl+click collapses all children including the main-line continuation.
  - **Pan and zoom** via scroll and drag.
  - **Drag-to-reposition** individual nodes.
  - **Hover board images** (optional, see `-a` below).
  - **R key / ↺ Reset button** restores the automatic layout.
- **Deck view** — a sequential card-by-card navigator (toggle with the 📇 Deck button):
  - Step through game info and main-line segments one card at a time with ← → arrow keys or on-screen buttons.
  - When a card has variations, clickable buttons appear below showing each variation's first move and optional comment (mirroring the tree's edge labels).
  - Click a variation button to enter it; use ← → to step between sibling variations at the same branch point. Sub-variations are accessible the same way.
  - A breadcrumb trail shows your position in the tree and lets you jump back to any ancestor level. Press Escape to go up one level.
- **Cross-view navigation** — double-click any node in the tree to open it directly in the deck view (with a zoom animation); double-click a deck card to jump back to the tree view centered on that node.
- **Light/dark theme toggle** applies to both views.

#### Board images in d3html

The `--images` flag works the same as for `dot`/`dothtml`:

```bash
# Default: one image per segment endpoint
chesstree -i game.pgn -f d3html -o game.html

# Images at both variation endpoints and commented moves
chesstree -i game.pgn -f d3html -o game.html --images variations commented

# No images (smallest output)
chesstree -i game.pgn -f d3html -o game.html --images none
```

SVG files are written alongside the HTML file. When writing to stdout, image references are included but no SVG files are written.

#### Hover board images (`-a`)

The `-a` / `--hover-for-all-moves` flag embeds a miniature board image for every individual move. Hovering over any move token in the tree shows the board position at that move in a popup:

```bash
chesstree -i game.pgn -f d3html -o game.html -a
```

This significantly increases file size (one small SVG per move) so it is off by default.

#### Custom HTML template (d3html)

```bash
chesstree -i game.pgn -f d3html --template my_d3_template.html -o game.html
```

The d3html template has four required placeholders (different from the dothtml placeholders):

| Placeholder | Replaced with |
|-------------|---------------|
| `{{CHESSTREE_TITLE}}` | Game title string |
| `{{CHESSTREE_TREE_DATA}}` | JSON tree data object (embed inside `JSON.parse(\`...\`)`) |
| `{{CHESSTREE_IMAGES}}` | JS statements that populate the `boardImages` dict, one per SVG file |
| `{{CHESSTREE_HOVER_DATA}}` | JS statements that populate the `hoverImages` dict (empty when `-a` not used) |

All four must be present or generation fails.

### DOT output and board images

The `--images` flag applies to DOT output as well as JSON/EDN. When writing to a file,
`chesstree` generates SVG board images and saves them **in the same directory** as the `.dot` file.
GraphViz then loads the images by path when rendering the DOT:

```bash
# Write game.dot and all SVG images into ./output/
chesstree -i game.pgn -f dot --images variations commented -o output/game.dot
dot -Tsvg output/game.dot -o output/game.svg
```

When writing to **stdout** (or with `-o -`), image references are included in the DOT syntax
but no SVG files are written — useful for piping the DOT string while skipping heavy image generation:

```bash
chesstree -i game.pgn -f dot -o - | dot -Tsvg -o game.svg   # no SVGs written
```

To omit images entirely from DOT output:

```bash
chesstree -i game.pgn -f dot --images none -o game.dot
```

Round-trip a game through JSON:

```bash
chesstree -i game.pgn -o game.json
chesstree -i game.json -f pgn -o game_restored.pgn
```

---

## Development environment

### Setup

```bash
git clone <repo-url> chesstree
cd chesstree

python3 -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

The `-e` flag installs the package in **editable mode**: changes to the source files under `chesstree/` take effect immediately without reinstalling.

### Running tests

```bash
pytest
```

With coverage:

```bash
pytest --cov=chesstree --cov-report=term-missing
```

### Using the CLI during development

Because the package is installed in editable mode, you can run `chesstree` directly from the terminal (with the virtual environment active) and your latest source changes are picked up immediately:

```bash
chesstree -i path/to/game.pgn -o /tmp/out.json
```

Alternatively, you can invoke the module directly without installing:

```bash
python -m chesstree.cli -i path/to/game.pgn
```

## AI assisted development

The project is developed in a supervised AI development manner where I try to keep a close eye on design choices, read and review the generated code, test the output manually etc.
