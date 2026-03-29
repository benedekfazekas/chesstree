# chesstree

A command-line tool for converting chess games between PGN, JSON, EDN, GraphViz DOT, and interactive HTML formats. It accepts PGN or chesstree JSON as input (auto-detected from the file extension) and can output JSON, EDN, PGN, DOT, or dothtml via the `-f`/`--format` flag. JSON output includes move number, SAN and UCI notation, FEN positions, comments, NAGs, and variations. DOT output models the game tree as a left-to-right digraph suitable for rendering with GraphViz tools. The dothtml format wraps the DOT graph in a self-contained browser viewer powered by [d3-graphviz](https://github.com/magjac/d3-graphviz), with pan, zoom, and board images included.

## Output format

The tool produces a JSON (or EDN) object with three top-level keys:

```json
{
  "headers": { "White": "Alice", "Black": "Bob", "Result": "1-0", ... },
  "moves": [
    {
      "move_number": 1,
      "turn": "white",
      "san": "e4",
      "uci": "e2e4",
      "fen_before": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
      "fen_after": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    },
    ...
  ],
  "result": "1-0"
}
```

Variations appear inline as `{ "variation": [ ... ], "branch_fen": "<FEN>" }` entries within the `moves` array, where `branch_fen` is the board position from which the variation's moves are played.

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
usage: chesstree [-h] [--version] -i INPUT [-o OUTPUT] [-f {json,edn,pgn,dot,dothtml}]
                 [--input-format {pgn,json}] [-b] [--images MODE [MODE ...]]
                 [--template FILE] [-a] [-c]

options:
  -h, --help                              show this help message and exit
  --version                               show program's version number and exit
  -i, --input INPUT                       Input file — PGN or chesstree JSON (use '-' for stdin)
  -o, --output OUTPUT                     Output file (default: stdout)
  -f, --format {json,edn,pgn,dot,dothtml} Output format: json (default), edn, pgn, dot, or dothtml
  --input-format {pgn,json}               Override auto-detected input format
  -b, --forblack                          Board images from Black's perspective (dot/dothtml)
  --images MODE [MODE ...]                Image generation mode for dot/dothtml output (default: variations)
                                          Choices: none, all, variations, commented.
                                          'variations' and 'commented' may be combined.
                                          SVG files are written alongside the output file;
                                          stdout skips writing SVGs.
                                          Has no effect on json/edn output.
  --template FILE                         Custom HTML template for dothtml output.
                                          Must contain {{CHESSTREE_TITLE}}, {{CHESSTREE_IMAGES}},
                                          {{CHESSTREE_DOT}}, and {{CHESSTREE_HOVER_DATA}} placeholders.
                                          Only used with -f dothtml.
  -a, --hover-for-all-moves               Enable per-move hover board popups in dothtml output.
                                          Each move becomes hoverable — mousing over it shows a
                                          floating board image. Only meaningful with -f dothtml.
  -c, --concise                           Compact output, no pretty-printing (json/edn output only)
```

The input format is auto-detected from the file extension (`.pgn` → PGN, `.json` → chesstree JSON). Use `--input-format` to override this when reading from stdin or a file with an unusual extension.

Supported conversions:

| Input | `-f` / `--format` | Output |
|-------|-------------------|--------|
| PGN   | `json` (default)  | chesstree JSON |
| PGN   | `edn`             | chesstree EDN  |
| PGN   | `dot`             | GraphViz DOT   |
| PGN   | `dothtml`         | Self-contained d3-graphviz HTML viewer |
| JSON  | `pgn`             | PGN            |
| JSON  | `dot`             | GraphViz DOT   |
| JSON  | `dothtml`         | Self-contained d3-graphviz HTML viewer |

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

### dothtml output — interactive browser viewer

The `dothtml` format produces a self-contained HTML file that renders the game tree interactively in a browser using [d3-graphviz](https://github.com/magjac/d3-graphviz). Board images are written as SVG files alongside the HTML file, which the browser loads by relative path.

```bash
# Generate HTML viewer + SVG images in ./output/
chesstree -i game.pgn -f dothtml -o output/game.html

# Open in browser
open output/game.html
```

The viewer includes a layout-engine selector (Dot, Circo, Fdp, …) and supports pan and zoom.

#### Per-move hover board images

Add `--hover-for-all-moves` (or `-a`) to make every move in the graph interactive — mousing over any move cell shows a floating board image popup:

```bash
chesstree -i game.pgn -f dothtml -a -o output/game.html
```

The hover SVGs are inlined directly in the HTML (no extra files needed). The flag is independent of `--images`: you can combine them to have both per-node inline images at variation branch points and per-move hover popups.

When writing to **stdout**, image references are included in the HTML but no SVG files are written:

```bash
chesstree -i game.pgn -f dothtml -o -
```

#### Custom HTML template

You can supply your own template with `--template`:

```bash
chesstree -i game.pgn -f dothtml --template my_template.html -o game.html
```

The template is plain HTML with four required placeholders:

| Placeholder | Replaced with |
|-------------|---------------|
| `{{CHESSTREE_TITLE}}` | Game title string (e.g. "White vs Black at 2024.01.01") — use in `<title>` and any heading |
| `{{CHESSTREE_IMAGES}}` | One `.addImage("./name.svg", "144px", "144px")` call per image, one per line |
| `{{CHESSTREE_DOT}}` | The raw DOT string — place this inside the JS backtick template literal assigned to `dot` |
| `{{CHESSTREE_HOVER_DATA}}` | JS declarations for hover feature: `const hoverEnabled = …` and `const hoverImages = {…}`. Always present; only populated when `--hover-for-all-moves` is on. |

All four placeholders must be present in the template or generation will fail with an error listing which are missing. The built-in template at `chesstree/templates/dothtml_default.html` in the project source is a good starting point for customisation.

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
