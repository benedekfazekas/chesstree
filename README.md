# chesstree

A command-line tool that converts PGN chess files to JSON or EDN. Each move in the output includes the move number, side to move, SAN notation, UCI notation, FEN position, and SVG board images (before and after the move). Game headers, comments, NAGs (move annotations), and variations are also included.

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

```
usage: chesstree [-h] [--version] -i INPUT [-o OUTPUT] [-b] [-e] [-c]

PGN to JSON/EDN converter

options:
  -h, --help           show this help message and exit
  --version            show program's version number and exit
  -i, --input INPUT    The input PGN file to be processed (use '-' for stdin)
  -o, --output OUTPUT  The output file for results (default: stdout)
  -b, --forblack       Board images are generated from Black's perspective
  -e, --edn            Output EDN instead of JSON
  -c, --concise        Output compact (non-pretty-printed) JSON/EDN
```

### Examples

Convert a PGN file to JSON and write to a file:

```bash
chesstree -i game.pgn -o game.json
```

Convert to EDN and print to stdout:

```bash
chesstree -i game.pgn -e
```

Read from stdin, write compact JSON to a file:

```bash
cat game.pgn | chesstree -i - -o game.json -c
```

Generate board images from Black's perspective:

```bash
chesstree -i game.pgn -o game.json -b
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
