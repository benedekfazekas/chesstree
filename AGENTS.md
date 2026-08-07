# AGENTS.md

Guidelines for AI agents working on the `chesstree` project.

---

## Project overview

`chesstree` is a Python CLI tool that converts chess games between PGN, JSON, EDN, GraphViz DOT,
d3-graphviz HTML (`dothtml`), and d3 hierarchy HTML (`d3html`) formats. It is installed as a single `chesstree` command via
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

### Ask when unsure
If you are unsure about a requirement, an approach, or whether a design decision is correct,
**always ask the user a clarifying question before implementing**. Do not guess and implement
the wrong thing — it wastes iterations and causes unnecessary rollbacks.

### Always run tests after changes
Run `python -m pytest tests/ -q` after every code change. All tests must pass before proceeding.
Never commit or hand off with a failing test suite.

**Acceptance tests** (marked `@pytest.mark.acceptance`) require a local Stockfish binary and are
**excluded from the default run and CI**.  Run them explicitly with:

```bash
pytest -m acceptance
```

They compare local Stockfish evals against the Lichess `analysis` corpus with sign-agreement
tolerance — mismatches are expected to be rare but non-zero (engine version/depth/hardware differ).

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
- if working locally and on the `main` branch the user controls what is staged before committing
- if working on a github issue always put a reference of the issue in the commit message
- never push directly on the `main` branch

### Releasing a new version (CalVer `YYYY.N`)

When cutting a release, update these four locations — all in one commit before tagging:

1. **`pyproject.toml` line 7** — `version = "YYYY.N.dev0"` → `"YYYY.N"`
2. **`CHANGELOG.md`** — promote `## [Unreleased] — YYYY.N.dev0` to `## [YYYY.N] — YYYY-MM-DD`
3. **`tests/test_cli.py`** — two lines in `test_version_format`: the `monkeypatch.setattr` value and the `assert` expected string, both `"YYYY.N.dev0"` → `"YYYY.N"`

After committing, tag and push: `git tag vYYYY.N && git push origin vYYYY.N`.

Then create a GitHub Release from the tag, using the version as the title and the relevant `CHANGELOG.md` section as the body:

```bash
gh release create vYYYY.N \
  --title "YYYY.N" \
  --notes "$(sed -n '/^## \[YYYY\.N\]/,/^## /p' CHANGELOG.md | sed '$d')"
```

After the release, bump `pyproject.toml` to `YYYY.(N+1).dev0` (or `YYYY+1.1.dev0` for a new year) and update the three test locations to match the new dev version.

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
| `d3tree_exporter.py` | `chess.pgn.Game` → D3 hierarchy JSON tree |
| `d3html_exporter.py` | Wraps `export_d3tree`, substitutes into d3html template |
| `leaf_evaluator.py` | Pure core + engine provider for `[%eval ...]` annotation: scope selection (`TERMINAL`/`BRANCHES`/`ALL`), `format_eval`, FEN de-dup, `annotate_evals`, `make_engine_provider`/`EngineUnavailable` |
| `utils.py` | Shared helpers: `has_real_comment()`, `_PGN_COMMAND_ANNOTATION_RE`, `normalize_fen()` (first 4 FEN fields; shared by `leaf_evaluator` and `merge_openings`) |
| `templates/dothtml_default.html` | Default d3-graphviz viewer template |
| `templates/d3html_default.html` | Default d3 hierarchy viewer template |

### `export_dot` return type
Returns `tuple[str, dict[str, str]]` — the DOT string and a filename→SVG-content dict.
The dict is empty when `image_modes` is `frozenset(["none"])` or `frozenset()`.

### `export_dothtml` return type
Same tuple shape. The caller (CLI or scripts) writes SVG files to the output directory.

### `export_d3tree` return type
Returns `tuple[dict, dict[str, str], dict[str, str]]` — the tree dict, a filename→SVG-content
dict for board images, and a nodeId→SVG-content dict for hover images (empty unless `hover=True`).

### `export_d3html` return type
Returns `tuple[str, dict[str, str]]` — the HTML string and the board-image filename→SVG dict.
The caller writes SVG files alongside the HTML output file.

### SVG writing convention
SVGs are written alongside the output file (`.dot` or `.html`) when output is to a **file**.
When output is **stdout** (`output_file.name == "<stdout>"`), image references are included
but no SVG files are written.

### Game comment
The PGN comment before the first move (`game.comment`) is stored in JSON/EDN output as
`headers["Comment"]`. In DOT/dothtml output it appears as an italic row in the root node label.
In both cases `[%...]` annotations are stripped; a comment consisting only of annotations is
silently omitted.

### Eval annotation (`--annotate-eval`)

`_maybe_annotate_evals_from_params(game, annotate_eval, eval_scope, engine, eval_depth, eval_time)`
applies `leaf_evaluator.annotate_evals` before serialization in every conversion function
(`pgn_to_json`, `json_to_pgn`, `pgn_to_pgn`, `game_to_dot`, `game_to_dothtml`, `game_to_d3html`).

CLI flags:

| Flag | Type | Default | Meaning |
|------|------|---------|---------|
| `--annotate-eval` | `store_true` | off | Enable engine evaluation annotation |
| `--eval-scope {leaves,branch-points,all}` | str | `branch-points` | `leaves` = terminal nodes only; `branch-points` = leaves **plus** fork nodes (default); `all` = every node |
| `--engine PATH` | str | `stockfish` | Path to or name of the UCI engine binary |
| `--eval-depth INT` | int | None (uses `DEFAULT_DEPTH=20`) | Fixed search depth |
| `--eval-time FLOAT` | float | None | Wall-clock seconds per position; **takes precedence over `--eval-depth`** when both are given |

On `EngineUnavailable` (binary missing or spawn fails), a warning is printed to stderr and the conversion continues without annotation — it never crashes.

The engine is opened once per invocation (via `leaf_evaluator.make_engine_provider`) and closed after all positions are evaluated. Positions are de-duplicated by normalized FEN so each unique board is evaluated at most once.

### Merge-script eval source / fallback (`scripts/merge_openings.py`)

- `apply_leaf_evals(merged_game, provider)` — annotates merged terminal leaves with engine evals; provider is shared across the run and positions are de-duped by normalized FEN.
- **Prefer local, fall back to Lichess:** one `make_engine_provider` call at startup. On `EngineUnavailable`, a warning is logged once and the script falls back to Lichess-embedded `[%eval]` annotations for every leaf.
- When the engine is available but returns `None` for a specific position (analyse error), that individual leaf falls back to the Lichess `[%eval]` for its source game.
- The leaf-label format (`vs [Opponent](url): **eval**`) is unchanged; only the *source* of the eval string differs.
- `normalize_fen` lives in `chesstree/utils.py` (not in `merge_openings.py`) and is imported from there by both the merge script and `leaf_evaluator.py`.
- `create_slice` embeds `[%result X]` (where X is `1-0`, `0-1`, or `1/2-1/2`) in the leaf node comment alongside `[%opening_end]`, so per-game result is available in the d3tree `result` field on each leaf move. Games with result `*` are silently omitted.

### Image modes
Four modes, combinable: `none`, `all`, `variations` (default), `commented`.
`variations` and `commented` can be specified together.

The `variations` mode places one image at the **last move of each segment** (run of moves between
branch points). At a branch point the image goes on the branching move (main-line choice at the
fork), not the branch position itself. See `json_exporter._collect_image_fens_recursive` and
`dot_exporter._DotBuilder._block_needs_image` for the reference implementations.

---

## d3tree exporter details

### d3tree JSON structure
The root dict has: `type: "root"`, `title`, `headers`, `gameComment`, `varSummaryMode`,
`forBlack`, `children`.

Each segment dict has: `type: "segment"`, `isVariation` (bool), `isMainLine` (bool),
`edgeLabel` (or `null`), `moves` (list), `hoverFens` (dict), `children` (list of segments).

Each move dict has: `num` (e.g. `"7."` for white, `"7\u2026"` for black), `san`, `nag`,
`nagClass`, `fen`, `comment` (stripped of `[%...]`), `eval` (or `null`), `result` (or `null`),
`image` (or `null`).

The `edgeLabel` dict (on variation segments) has: `move` (e.g. `"7. Nc3"` or `"10\u2026 Ng4"`),
`nagClass`, `startingComment` (list of wrapped lines or `null`), `comment` (same).

### Main-line segment layout
`_collect_main_segments_flat()` produces a **flat list** of main-line segments as direct children
of root — they are siblings, not chained. Variation children are attached to the specific
main-line segment where the branch occurs.

### Branching move invariant
**When a segment has variation children, its last move is always the branching move** (the
mainline choice at that fork). Variation children are alternatives to this last move — they do
NOT include it. Sub-variations within a variation segment follow the same rule.

This invariant is essential for reconstructing full move paths: the ancestor moves for any
variation child = `parentSegment.moves[:-1]` plus ancestor moves inherited from above.

### Eval field on moves
`move.eval` is parsed from `[%eval ...]` in the raw PGN comment using `chess.pgn.EVAL_REGEX`.
- `{"cp": int}` — centipawns, white-perspective (positive = white advantage)
- `{"mate": int}` — positive = white mates in N, negative = black mates in abs(N)
- Optional `"depth"` key on either form
- `null` when no eval annotation is present
- The `comment` field is always stripped of `[%...]` annotations; `eval` captures the raw value.

### Result field on moves
`move.result` is parsed from `[%result ...]` in the raw PGN comment by `_RESULT_RE`.
- `"1-0"`, `"0-1"`, or `"1/2-1/2"` — exactly the PGN result string
- `null` when no result annotation is present
- Only leaf moves in merged game trees carry this (embedded by `create_slice` in `merge_openings.py`)
- For single-game files, the result falls back to `treeData.headers.Result` in the template via `_getRowResult(lastMove)`

---

## d3html template

### Views
The d3html output has three views toggled by buttons in the header:
- **Tree** (🌳) — D3 hierarchy SVG with pan/zoom/drag
- **Deck** (📇) — card-by-card navigation through the game tree
- **Summary** (📊) — variation summary table; only shown when `varSummaryMode` is set

View transitions use `animateSwitch(targetView, exitClass, options)`. The `currentView` state
variable tracks which view is active (`'tree'`, `'deck'`, or `'summary'`).

### Placeholders (all four are required)

| Placeholder | Content |
|-------------|---------|
| `{{CHESSTREE_TITLE}}` | Game title, e.g. "White vs Black at 2024.01.01" |
| `{{CHESSTREE_TREE_DATA}}` | JSON tree dict — embedded inside a JS backtick template literal |
| `{{CHESSTREE_IMAGES}}` | JS comment listing SVG filenames (informational only) |
| `{{CHESSTREE_HOVER_DATA}}` | `const hoverEnabled = …; const hoverImages = …;` |

### Security: JS template literal escaping
The tree JSON is embedded as `JSON.parse(\`{{CHESSTREE_TREE_DATA}}\`)`. Before substitution
`_escape_js_template_literal()` escapes `\` → `\\`, `` ` `` → `` \` ``, and `${` → `\${`.

This same function is shared with the dothtml exporter (`dothtml_exporter._escape_js_template_literal`).

Custom templates must contain all four placeholders or `export_d3html` raises `ValueError`.

### Passing configuration via treeData
Feature flags that the template JS needs (`varSummaryMode`, `forBlack`) are embedded directly
in the root dict of the tree JSON rather than as separate placeholders. Access them in JS as
`treeData.varSummaryMode` and `treeData.forBlack`.

### Variation summary JS
`collectVariationRows(mode)` walks the treeData tree and returns rows for the summary table.
The full move path for each variation is reconstructed using `_ancestorMovesForChild()`, which
parses the child's `edgeLabel.move` to determine the split point in the parent's moves array.
`_summaryRows` module-level array stores the last-rendered rows so navigation button handlers
can reference segment data by index.

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
| `test_d3tree_exporter.py` | D3 hierarchy JSON tree export |
| `test_d3html_exporter.py` | d3html HTML export, template validation |
| `test_cli.py` | CLI argument parsing and dispatch |
| `test_functional.py` | End-to-end round-trips using real PGN samples |
| `test_utils.py` | `has_real_comment()` and annotation-stripping logic |
| `test_leaf_evaluator.py` | Pure core + engine provider: scope selection, `format_eval` round-trip, FEN de-dup, `overwrite`, `None` handling, `make_engine_provider` with stubbed/monkeypatched providers (no real Stockfish) |
| `test_leaf_evaluator_acceptance.py` | Real-Stockfish acceptance tests (excluded from default run and CI; gate with `@pytest.mark.acceptance` + `skipif`); compare local evals against Lichess `analysis` corpus with sign-agreement tolerance |

### Helpers
- `_dot(path, **kwargs)` in `TestDotFunctional` returns just the DOT string (unpacks the tuple)
- `_dot_and_images(path, **kwargs)` returns the full tuple
- `_load(path)` reads a `chess.pgn.Game` from a sample PGN path (used across test files)
- `_load_pgn(pgn_str)` in `test_d3tree_exporter.py` reads a game from an inline PGN string
- `_all_segments(node)` in `test_d3tree_exporter.py` recursively collects all segment dicts from a tree

### Adding tests for new output behaviour
When changing exporter output (new rows, changed formatting), always update or add unit tests
before touching the code. Check existing tests first to avoid redundant assertions.

---

## Parallel issue implementation with git worktrees

When multiple issues are independent (no code overlap), implement them in parallel using
git worktrees. Each worktree gets its own branch, venv, and sub-agent.

### Setup

```bash
# From the main repo, create one worktree per issue branching from main
git worktree add ../chesstree-issue-N -b issue-N-slug main

# Each worktree needs its own venv
cd ../chesstree-issue-N
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

### Workflow

1. **Identify independent issues** — verify they touch different code paths and won't produce
   merge conflicts. Check the dependency graph before parallelising.
2. **Create worktrees** — one per issue, each branching from the same base (usually `main`).
3. **Launch sub-agents** — one `general-purpose` background agent per worktree with a detailed
   prompt covering the issue scope, implementation plan, test expectations, and commit message.
   Sub-agents stage and commit directly in their worktree — the "user controls staging" rule
   does not apply here.
4. **Wait for completion** — agents run in parallel. Review results as they finish.
5. **Spot-check** — verify tests pass in each worktree, review diffs for correctness.
6. **Push and create PRs** — push all branches and create PRs in parallel.

### Cleanup

After PRs are merged, remove the worktrees:

```bash
cd /path/to/chesstree
git worktree remove ../chesstree-issue-N
```
