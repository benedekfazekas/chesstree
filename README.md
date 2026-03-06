# chesstree

A command-line tool for converting chess games between PGN and JSON/EDN. The `export` subcommand converts a PGN file to JSON or EDN — each move in the output includes move number, side to move, SAN and UCI notation, FEN position, SVG board images (before and after the move), comments, NAGs (move annotations), and variations. The `import` subcommand reads a chesstree JSON file and converts it back to PGN, making round-trips fully supported.

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
      "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
      "board_img_before": "<svg ...>",
      "board_img_after":  "<svg ...>"
    },
    ...
  ],
  "result": "1-0"
}
```

Variations appear inline as `{ "variation": [ ... ] }` entries within the `moves` array.

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

`chesstree` has two subcommands: **export** (PGN → JSON/EDN) and **import** (JSON → PGN).

### export — Convert PGN to JSON or EDN

```
usage: chesstree export [-h] -i INPUT [-o OUTPUT] [-b] [-e] [-c]

options:
  -h, --help           show this help message and exit
  -i, --input INPUT    The input PGN file to be processed (use '-' for stdin)
  -o, --output OUTPUT  The output file for results (default: stdout)
  -b, --forblack       Board images are generated from Black's perspective
  -e, --edn            Output EDN instead of JSON
  -c, --concise        Output compact (non-pretty-printed) JSON/EDN
```

### import — Convert chesstree JSON back to PGN

```
usage: chesstree import [-h] -i INPUT [-o OUTPUT]

options:
  -h, --help           show this help message and exit
  -i, --input INPUT    The input JSON file produced by 'chesstree export'
  -o, --output OUTPUT  The output PGN file (default: stdout)
```

### Examples

Convert a PGN file to JSON and write to a file:

```bash
chesstree export -i game.pgn -o game.json
```

Convert to EDN and print to stdout:

```bash
chesstree export -i game.pgn -e
```

Read from stdin, write compact JSON to a file:

```bash
cat game.pgn | chesstree export -i - -o game.json -c
```

Generate board images from Black's perspective:

```bash
chesstree export -i game.pgn -o game.json -b
```

Convert a chesstree JSON file back to PGN:

```bash
chesstree import -i game.json -o game.pgn
```

Round-trip a game through JSON (useful for scripting):

```bash
chesstree export -i game.pgn -o game.json
chesstree import -i game.json -o game_restored.pgn
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
chesstree export -i path/to/game.pgn -o /tmp/out.json
```

Alternatively, you can invoke the module directly without installing:

```bash
python -m chesstree.cli export -i path/to/game.pgn
```
