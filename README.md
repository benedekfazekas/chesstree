# chesstree

A command-line tool for converting chess games between PGN, JSON, and EDN. It accepts PGN or chesstree JSON as input (auto-detected from the file extension) and can output JSON, EDN, or PGN via the `-f`/`--format` flag. JSON output includes move number, SAN and UCI notation, FEN position, SVG board images, comments, NAGs, and variations.

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
usage: chesstree [-h] [--version] -i INPUT [-o OUTPUT] [-f {json,edn,pgn}]
                 [--input-format {pgn,json}] [-b] [-c]

options:
  -h, --help                   show this help message and exit
  --version                    show program's version number and exit
  -i, --input INPUT            Input file — PGN or chesstree JSON (use '-' for stdin)
  -o, --output OUTPUT          Output file (default: stdout)
  -f, --format {json,edn,pgn}  Output format: json (default), edn, or pgn
  --input-format {pgn,json}    Override auto-detected input format
  -b, --forblack               Board images from Black's perspective (json/edn output only)
  -c, --concise                Compact output, no pretty-printing (json/edn output only)
```

The input format is auto-detected from the file extension (`.pgn` → PGN, `.json` → chesstree JSON). Use `--input-format` to override this when reading from stdin or a file with an unusual extension.

Supported conversions:

| Input | `-f` / `--format` | Output |
|-------|-------------------|--------|
| PGN   | `json` (default)  | chesstree JSON |
| PGN   | `edn`             | chesstree EDN  |
| JSON  | `pgn`             | PGN            |

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

Generate board images from Black's perspective:

```bash
chesstree -i game.pgn -o game.json -b
```

Convert a chesstree JSON file back to PGN:

```bash
chesstree -i game.json -f pgn -o game_restored.pgn
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
