# AGENTS.md

Guidelines for AI agents working on the `chesstree` project.

---

## Project overview

`chesstree` is a Python CLI tool that converts chess games between PGN, JSON, EDN, GraphViz DOT,
and d3-graphviz HTML (`dothtml`) formats. It is installed as a single `chesstree` command via
`pip install -e .` and uses the `python-chess` library for PGN parsing and SVG board generation.

---

## Development environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run tests:
```bash
python -m pytest tests/
```

There is no separate lint or build step. All tests must pass before committing.

---

## Workflow conventions

### Always run tests after changes
Run `python -m pytest tests/ -q` after every code change. All tests must pass before proceeding.
Never commit or hand off with a failing test suite.

### Regenerate HTML samples only when explicitly asked
Only regenerate the sample HTML files in `/tmp/chesstree.samples/` when the user explicitly
requests it, or when a change significantly alters the visual output (e.g. a new layout feature,
template redesign). Do **not** regenerate for small bug fixes or refactors.

When regeneration is needed, each game gets a subdirectory with three HTMLs:

| Filename | Image modes |
|----------|-------------|
| `{name}.html` | `variations + commented` |
| `{name}_variations.html` | `variations` only |
| `{name}_commented.html` | `commented` only |

Sample PGNs are in `tests/sample_pgns/`: `hillbilly_v3.pgn`, `lisperer_vs_verenitach.pgn`,
`lichess_study_caro-kann-exchange-sample3.pgn`.

Use `chesstree.dothtml_exporter.export_dothtml` directly (not the CLI) when scripting bulk
regeneration.

### Planning significant features
For non-trivial features: analyse the codebase, propose a plan, confirm with the user before
implementing. Save the plan to the session state `plan.md`. Break the plan into SQL-tracked todos.

### Git commits
- Title + one sentence body (or a short bullet list for multi-fix commits)
- Do **not** mention Copilot or AI in the message
- Stage files first; the user controls what is staged

---

## Code style

### Python
- `from __future__ import annotations` at the top of every module
- Type hints on all public and internal functions
- Use `frozenset[str]` for image modes parameters (not `list`)
- Prefer `pathlib.Path` over string paths
- No commented-out debug code in committed files
- Keep private helpers prefixed with `_`

### JavaScript (in HTML templates)
- Use `const`/`let`, not `var`
- `logEvents(false)` — never ship with `true`
- No dead variables (e.g. unused padding variables)
- Template literals preferred over string concatenation for multi-part strings

---

## Architecture

### Module responsibilities

| Module | Role |
|--------|------|
| `cli.py` | Argument parsing, format dispatch, file I/O, SVG writing |
| `json_exporter.py` | PGN → JSON/EDN; `collect_image_fens()` for image mode logic |
| `json_parser.py` | chesstree JSON → `chess.pgn.Game` |
| `dot_exporter.py` | `chess.pgn.Game` → DOT string + `{filename: svg}` dict |
| `dothtml_exporter.py` | Wraps `export_dot`, substitutes into HTML template |
| `utils.py` | Shared helpers: `has_real_comment()`, `_PGN_COMMAND_ANNOTATION_RE` |
| `templates/dothtml_default.html` | Default d3-graphviz viewer template |

### `export_dot` return type
Returns `tuple[str, dict[str, str]]` — the DOT string and a filename→SVG-content dict.
The dict is empty when `image_modes` is `frozenset(["none"])` or `frozenset()`.

### `export_dothtml` return type
Same tuple shape. The caller (CLI or scripts) writes SVG files to the output directory.

### SVG writing convention
SVGs are written alongside the output file (`.dot` or `.html`) when output is to a **file**.
When output is **stdout** (`output_file.name == "<stdout>"`), image references are included
but no SVG files are written.

### Game comment
The PGN comment before the first move (`game.comment`) is stored in JSON/EDN output as
`headers["Comment"]`. In DOT/dothtml output it appears as an italic row in the root node label.
In both cases `[%...]` annotations are stripped; a comment consisting only of annotations is
silently omitted.

### Image modes
Four modes, combinable: `none`, `all`, `variations` (default), `commented`.
`variations` and `commented` can be specified together.

The `variations` mode places one image at the **last move of each segment** (run of moves between
branch points). At a branch point the image goes on the branching move (main-line choice at the
fork), not the branch position itself. See `json_exporter._collect_image_fens_recursive` and
`dot_exporter._DotBuilder._block_needs_image` for the reference implementations.

---

## DOT exporter details

### Node structure
Each node is a GraphViz `shape=plaintext` with an HTML `<<table>>` label.
Moves are grouped into **blocks** — a block ends after any move that has a **real human comment**
(PGN command annotations such as `[%clk]`, `[%eval]`, `[%csl]`/`[%cal]` do not count).
Each block is one `<tr>` row; image rows follow immediately after the block row they belong to.

### PGN command annotation filtering
All `[%...]` PGN command annotations (clock, eval, arrows, etc.) are stripped before rendering
comment text in node labels, edge labels, and the root node game comment.
The shared utility `chesstree.utils.has_real_comment(comment)` returns `True` only when the
comment contains text beyond these annotations. Use it wherever "has a comment" is checked.

### NAG coloring
NAG symbols are appended directly to the SAN (`e4?`, `Nxg5?!`). Only the SAN+NAG is wrapped
in a `<font color="...">` tag — **never** the move-number prefix (e.g. `7. ..`).

### Node IDs
`"n" + md5(fen)[:8]` — stable and reproducible from the board FEN.

### Image rows in DOT HTML labels
```
<tr><td href="./filename.svg" border="0" fixedsize="TRUE" height="100" width="100">
  <IMG src="./filename.svg"/>
</td></tr>
```

---

## dothtml template

### Placeholders (all three are required)

| Placeholder | Content |
|-------------|---------|
| `{{CHESSTREE_TITLE}}` | Game title, e.g. "White vs Black at 2024.01.01" |
| `{{CHESSTREE_IMAGES}}` | `.addImage("./name.svg", "144px", "144px")` calls, one per line |
| `{{CHESSTREE_DOT}}` | DOT string — embedded inside a JS backtick template literal |

### Security: JS template literal escaping
The DOT string is escaped before substitution via `_escape_js_template_literal()`:
- `\` → `\\` (first, to avoid double-escaping)
- `` ` `` → `` \` ``
- `${` → `\${`

This prevents PGN content (comments, player names) from breaking out of the JS backtick
string and injecting JavaScript into generated HTML files.

Custom templates must contain all three placeholders or `export_dothtml` raises `ValueError`
listing the missing ones.

---

## Testing conventions

### Test files

| File | Covers |
|------|--------|
| `test_json_exporter.py` | JSON/EDN export, `collect_image_fens` |
| `test_dot_exporter.py` | DOT export, image dict, NAG coloring |
| `test_dothtml_exporter.py` | HTML export, template validation, JS escaping |
| `test_cli.py` | CLI argument parsing and dispatch |
| `test_functional.py` | End-to-end round-trips using real PGN samples |
| `test_utils.py` | `has_real_comment()` and annotation-stripping logic |

### Helpers
- `_dot(path, **kwargs)` in `TestDotFunctional` returns just the DOT string (unpacks the tuple)
- `_dot_and_images(path, **kwargs)` returns the full tuple
- Use `_load(path)` to read a `chess.pgn.Game` from a sample PGN path

### Adding tests for new output behaviour
When changing exporter output (new rows, changed formatting), always update or add unit tests
before touching the code. Check existing tests first to avoid redundant assertions.
