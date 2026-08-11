# Big opening repertoire analysis

Make a several-thousand-game repertoire renderable and, more importantly, *actionable*: find the
lines that score badly, then drill down to the individual games behind them.

Supersedes the brainstorm in `plans/big-opening-repertoir-analysis-problem-space.md`.

## Measured facts (validated against `ah14-e4-blitz-rapid-games.json`)

All numbers below were measured, not estimated. They drive every decision in this plan.

- The cache holds **5,266 games**, of which **2,929** are `1.e4` as white. It is *not* 16k — the
  `grep -o '"id"'` count in the brainstorm also matched nested player ids (~3x inflation).
- Merged tree for those 2,929 games: **31,463 nodes / 4,398 segments / 2,747 leaves**.
- Renders fine today: `caro-advanced.pgn` at **843 nodes / 62 leaves**. Chokes today:
  `kingspawn-ah14-blitz-rapid2026.pgn` at **12,011 nodes / 1,088 leaves**.
- **Splitting by black's first reply does not solve this.** Largest shards are `1...e5` at
  9,241 nodes / 1,269 segments and `1...c5` at 7,205 nodes / 1,193 segments — still ~10x over the
  known-good size. That approach is therefore dropped.
- The tree is a hairball of singletons. Nodes reached by >=1 game: 31,463. By >=2 games: **3,236**.
  ~90% of the tree is one-game tails. The median game becomes unique at **ply 12** while the
  divider cuts at median **ply 21** — roughly 9 plies of every game are pure singleton tail
  carrying no repertoire information.
- Frequency pruning is the lever that works:

  | threshold | visible nodes | attach points | max games behind one node | median |
  |---|---|---|---|---|
  | 3 | 1,756 | 1,036 | 19 | 3 |
  | 5 | 957 | 621 | 19 | 5 |
  | **10** | **469** | **321** | **43** | **9** |
  | 20 | 252 | 179 | 62 | 15 |

  At every threshold `games_at_root_stub = 0` — no game is orphaned.
- Payload sizes (minified JSON): game records without line path **169 KB**; full 31k-node skeleton
  with counts **569 KB**; threshold-10 node payload **9 KB**.
- Only **423 of 2,929** games (14.5%) carry an inline `[%eval]` at their opening end, so the
  existing Lichess fallback cannot serve this feature. Local engine evaluation is mandatory.
- Transpositions are a non-issue here: 31,463 trie nodes vs 29,437 distinct positions (~6%
  duplication). Not addressed in this plan.
- Junk games are negligible in volume but do pollute the tree: 1 `noStart`, plus resigns at ply
  2–3. Only 11 games have an opening end below ply 6.
- **The merged tree's mainline is a fetch-order artifact.** `merge_game_slices` puts whichever game
  was inserted first into `variations[0]`, which becomes the mainline. Replaying the merge with
  shuffled input yields a different mainline every time:

  ```
  fetch order : e4 d6 d4 e6 Nc3 g6 …   ← "Rat Defense", 149 games
  shuffle 1   : e4 c5 Nf3 d6 d4 cxd4 …
  shuffle 2   : e4 e6 d4 d5 Nd2 Nf6 …
  shuffle 3   : e4 c5 Nf3 d6 d4 cxd4 …
  ```

  The current mainline is a 149-game sideline that happened to be fetched first, while `1...e5`
  (889 games) is demoted to a variation. `isMainLine` is therefore noise rendered as signal.
- **Opening names are available and well-sized for grouping.** `opening.name` is present on
  **2,928 / 2,930** games (99.9%). Taking the family (text before `:`) gives **35 families** —
  Sicilian 803, Caro-Kann 331, French 279, Scandinavian 228, Vienna 218, Four Knights 186,
  Italian 152. Raw names (215) are too fine; ECO families (15) are too coarse.
- **Families are finer *and* more meaningful than first moves.** `1...e5` — one undifferentiated
  889-game blob under move-grouping — splits into Vienna 216 / Four Knights 183 / Italian 147 /
  Three Knights 106, which are genuinely different prep problems.
- **A family is not a root child.** The opening name is decided deep, not at black's first move:
  `opening.ply` is 8 for 1,084 games, 5 for 522, 6 for 408, 4 for 359, 7 for 341. Only **67 of
  2,927** games (2%) have their name decided by ply 2.
- **Family band anchors** (shallowest family-pure node, ≥90% purity and ≥10 games, after floor-3
  pruning): **28 anchors covering 2,692 / 2,929 games (91.9%)** across 19 families, at
  ply 2 (7 anchors), ply 3 (1), ply 4 (5), ply 5 (4), ply 6 (11).

  ```
  ply2  e4 c5                     Sicilian Defense       802  100%
  ply2  e4 c6                     Caro-Kann Defense      332  100%
  ply2  e4 e6                     French Defense         302   91%
  ply2  e4 d5                     Scandinavian Defense   229  100%
  ply6  e4 e5 Nf3 Nc6 Nc3 Nf6     Four Knights Game      159  100%
  ply5  e4 e5 Nf3 Nc6 Bc4         Italian Game           156   94%
  ply4  e4 e5 Nc3 Nf6             Vienna Game             70  100%
  ```

- **Families are tags, not a partition.** Vienna has 5 anchors, Three Knights 3, Four Knights 2,
  and 8.1% of games fall under no anchor. Grouping must therefore be a facet over rows/regions,
  never a tree split — a split would reintroduce the multi-tree complexity this plan rejects.

## Decisions (settled with the user)

- **Primary goal is statistical**: find weak spots. The tree is the view, not the point.
- **Games are payload, not nodes.** An individual game does not need its own node in the
  tree/deck/PGN, as long as its result, its platform link and its opening-end eval remain
  reachable by drilling down.
- **Frequency pruning is the scaling mechanism.** Multi-tree splitting and a tree selector are
  dropped from scope; they may return later purely as navigation convenience.
- **Emit both formats.** PGN stays the interop wire format; chesstree JSON is the rich format.
  They must not diverge — see *Format strategy*.
- **Two evals, both kept**: the row shows the **node eval** (the pruned line's own end position);
  the drill-down and the barchart use **per-game opening-end evals**. **The two are measured at
  different plies and must be labelled as such** — see *Eval provenance*.
- **A weak spot is score AND eval together, never score alone** — see *Weak-spot definition*.
- **Ranking is by a confidence lower bound, not by the raw mean** — see *Ranking under small
  samples*.
- Threshold is an **absolute game count**: build-time floor **N=3**, client-side slider 3→50,
  default view **10**.
- Score is always from the **repertoire owner's** perspective; repertoire mode **requires
  `--color`**.
- **Repertoire mode is opt-in behind a new `--repertoire` flag.** Counting, pruning, `[%game ...]`
  attachment and the hygiene filters only run when it is given. Validated fact: `--color` today is
  `default=None` (`scripts/merge_openings.py:291`) and is passed by no test and no other script, so
  making it *unconditionally* required would be a silent breaking change for existing single-opening
  merges. Under `--repertoire`, `parser.error` fires if `--color` is absent; without it the script
  behaves exactly as today.
- **Hygiene**: drop `noStart` games and games whose opening end is below ply 6.
- **Eval cache**: SQLite at `~/.cache/chesstree/evals.db`. Key is (normalized FEN, engine id,
  full limit spec) — see *Phase 2* for why depth alone is wrong.
- **Opponent rating is part of the first cut.** Each `[%game ...]` record carries the opponent's
  rating and `stats` exposes the average over rated games. Rating is **optional**: a game with no
  usable rating stores an empty field, is excluded from the average, and is counted separately so
  the UI can say how many games the average is based on. A node where no game has a rating reports
  no average rather than `0`.
- **Group by opening family, and retire the mainline.** `isMainLine` privileging is removed from
  the summary; opening family becomes the organising principle in both the summary table and the
  tree — see *Opening-family grouping*. Bands in the tree ship behind a toggle.

## Opening-family grouping

The brainstorm's instinct — that the mainline is meaningless for repertoire analysis and the tree
should be grouped by opening instead — is correct, and the measured facts above support it more
strongly than the brainstorm assumed. Two changes follow.

### Retire the mainline

`collectVariationRows()` currently special-cases the mainline ("Always include the last main-line
segment's last move") and `_renderSummary` marks rows with `.var-summary-mainline-row`. Since the
mainline is a fetch-order artifact, under `--repertoire` this privileging is **removed**: all lines
are peers, ordered by the ranking rules in *Ranking under small samples*. Non-repertoire output is
unchanged, so single-game and single-opening files keep their mainline.

### Grouping key

The family is `opening.name` truncated at the first `:`. It is carried on each `[%game ...]` record
and promoted into the JSON like every other game field. A node's family is the **majority family of
the games at or below it**, with the share recorded so the UI can show purity.

**Source fallback is required.** `opening.name` is a Lichess field; the Chess.com adapter has no
equivalent, and this merge is multi-source. Resolution order per game:

1. Lichess `opening.name` family.
2. ECO from the PGN `ECO`/`Opening` headers when present.
3. Otherwise `"Unknown"`.

Games in `"Unknown"` must remain fully visible and rankable — they are grouped, not hidden.

### Summary table grouping

Rows are grouped under collapsible family headers. Each header shows the family name, aggregate
game count, aggregate score with its confidence interval, and the worst category present beneath
it. Families are ordered by the same Wilson-lower-bound rule as rows, so the weakest family sorts
to the top. Grouping is a `groupBy` over the existing flat row list — it does not change how rows
are produced.

### Tree bands

A band is a labelled, tinted, collapsible region anchored at a **family anchor node**: the
shallowest node that is ≥90% one family and holds ≥10 games. Measured, that is 28 anchors covering
91.9% of games at plies 2–6.

The tree root stays the filter position; bands are **not** a layer beneath it. Because a family may
have several anchors and 8.1% of games sit under none, bands are region tags drawn over the
existing layout — the tree structure is untouched. Unbanded trunk (e.g. `e5 Nf3 Nc6`, shared by
several families) simply carries no band.

Band rendering ships behind a **toggle in the header, defaulting to on**, alongside the existing
tree/deck/summary buttons. The toggle exists because bands overlay the most fragile part of the
template — collapse, drag, zoom and the prune slider all move nodes, and bands must move with them.
If bands make the tree too busy at low thresholds, or if they fight the existing interactions, the
toggle is the escape hatch and the feature can ship off-by-default without reopening the plan.

Anchor computation is a **pure function** over the tree plus game records, shared by the summary
and the tree, and unit-testable without a DOM.

## Weak-spot definition

The measured data is blitz and rapid. A game's result is decided by the whole game — conversion,
clock, blunders, opponent strength — not by the opening. Score at a node is therefore **not** a
measure of opening quality, and ranking on it alone answers "where do I lose points", not "where is
my prep bad". Those are different questions with different fixes.

The plan already computes both numbers per row: the score aggregate and the node eval. They must be
**crossed**, not merely displayed side by side. Every row is assigned one of four categories from
(score vs the repertoire-wide average score) × (node eval vs equal):

| | eval bad | eval fine |
|---|---|---|
| **score bad** | **prep hole** — the position really is worse and the results agree. Fix the opening. | **conversion** — the position is fine, the points are lost afterwards. Not an opening problem. |
| **score good** | **fragile** — winning from worse positions; works until it doesn't. | **strong suit** — position and results agree. |

The category is the primary signal on the row; the raw score is supporting detail. Strong-suit
detection is the same table read from the other end and carries the same caveats as everything
below.

Thresholds: "eval bad" reuses the existing `_EVAL_DEFAULTS` equal band (`equalLower` = −0.5,
`equalUpper` = +0.5) from the template's eval-category config, sign-adjusted for `forBlack`, so
the user's own configured bands drive the categorisation. "score bad" is below the repertoire-wide
average score across all listed rows, computed at the current threshold.

## Ranking under small samples

At threshold 10 there are **321 attach points** with a **median of 9 games** each; the slider goes
down to 3, where the median is 3. A mean over 9 games is not a measurement — for a player whose
true score is 55%, an observed 30% at n=9 has a 95% interval of **10.2%–61.8%**, a 52-point span
that covers both their best and their worst line at once.

Sorting 321 such rows ascending is an extremum search over 321 noisy draws. Assuming *every line is
equally good* (true 55%, no real weak spots anywhere), the expected number of lines that look like
disasters (≤30% score) purely by luck is:

| threshold | median n | P(a good line looks ≤30%) | expected false weak spots of 321 |
|---|---|---|---|
| 3 | 3 | 9.1% | 29 |
| 10 | 9 | 5.0% | **16** |
| 20 | 15 | 2.5% | 8 |

So the naive default view would put ~16 fabricated weak spots at the top of a clean repertoire, and
dragging the slider down — the direction users will drag it — makes it worse.

Therefore:

- **Rank by the Wilson score lower bound at 95%**, not by the mean. Small samples are pushed down
  in proportion to how little is known about them, which subsumes an arbitrary cutoff.
- **Display `n` and the interval next to the score**, e.g. `22% (n=9, 10–62%)`, so the uncertainty
  is visible rather than hidden behind a decimal.
- The **10-game listing guard remains** as a floor, but it is not sufficient on its own — it only
  removes n<10 and leaves median-9-ish rows still carrying ±50 points. Guard and lower-bound
  ranking are both required.

**This section needs a human re-review once implemented.** Chess scores are ternary (0/0.5/1), not
binomial, so Wilson is an approximation; opponent-rating spread inside a line adds variance beyond
the binomial floor, meaning the table above **understates** the noise. The formula is a defensible
first cut, not a settled answer — revisit it against the real generated file before trusting the
ranking.

## Eval provenance

The two evals are taken at different points in the game and can legitimately disagree:

- The **node eval** is the position at the pruned line's end — `min(divider_ply, prune_boundary)`,
  which for a heavily pruned node is *shallower* than any individual game got.
- The **per-game evals** are each game's own opening-end position at its own divider ply, typically
  deeper.

A row can therefore read `+0.3` while its game bucket clusters at `−1.5`. That gap is itself signal
— the line is fine where it is pruned and the players drift afterwards — but it reads as a
contradiction unless labelled. Both evals must carry their ply in the UI (row eval labelled with the
node's ply, drill-down evals with each game's own), and the drill-down states in one line that the
per-game evals are measured deeper than the row's.

No new field is needed for this: the node's ply is its depth in the tree, and a game's opening-end
ply is its attach-point depth plus the length of the line tail already stored in its record. Derive
both rather than adding a field to `[%game ...]`.

## Format strategy

JSON is the source of truth; PGN carries the same information losslessly via command annotations.

Schema v1.2.0 already added `raw_annotations`, which preserves **all** `[%...]` annotations
verbatim specifically to keep chesstree lossless. This plan reuses that mechanism rather than
inventing a parallel channel:

- The merge script writes one
  `[%game <id>|<opponent>|<url>|<result>|<eval>|<rating>|<line-tail>]` annotation per game on the
  node where that game attaches, alongside the existing `[%opening_end]` and `[%result]`
  annotations. `<rating>` is the opponent's rating, or empty when the source did not supply one.
- Fields are positional and the count is fixed, so a parser must split on `|` with a **known field
  count** and treat the last field as the line tail. Any `|` or `]` occurring inside a field is
  percent-escaped by the formatter (`|` → `%7C`, `]` → `%5D`, `%` → `%25` first) and unescaped by
  the parser. Platform usernames are alphanumeric so this is defensive, but game URLs are outside
  our control.
- `json_parser.py` round-trips them through `raw_annotations` unchanged.
- The JSON exporter **promotes** those annotations into a typed `games: []` array plus a `stats`
  object on the node.

Schema impact is additive (`games`, `stats`, `gameCount` are all new optional fields), which is
backward compatible under the rules in `schema-versioning.md`. Bump to **schema 1.3.0** and add a
`chesstree-schema-changelog.md` entry.

Because the threshold slider re-attaches games client-side, each game record must carry its line
tail. This raises the records payload from the measured 169 KB to roughly 400 KB — acceptable.

## Affected modules

| Module | Change |
|---|---|
| `scripts/sources.py` | Add optional `opponent_rating: int \| None` to `SourceGame`; populate it per source (Lichess `players.<side>.rating`, Chess.com `<side>.rating` / PGN `WhiteElo`/`BlackElo`); `None` when absent or unrated. Add `opening_family: str` resolved via the fallback chain in *Opening-family grouping* |
| `scripts/merge_openings.py` | New `--repertoire` flag gating the whole feature; count games per node; prune at floor N=3; attach `[%game ...]` records at prune boundaries; apply hygiene filters; require `--color` when `--repertoire` is set |
| `chesstree/leaf_evaluator.py` | Add persistent SQLite eval cache behind the existing provider interface |
| `chesstree/json_exporter.py` | Promote `[%game ...]` annotations into typed `games` / `stats`; bump schema to 1.3.0 |
| `chesstree/json_parser.py` | Verify `[%game ...]` survives the round-trip via `raw_annotations` |
| `chesstree/d3tree_exporter.py` | Carry `games`, `stats`, `gameCount` onto segments/moves; carry each node's majority `family` and its purity share |
| `chesstree/templates/d3html_default.html` | Threshold slider; game-count/score/avg-rating columns; row drill-down; rework `_subtreeResultScore` and `_renderEvalBarchart`; family grouping in the summary; band anchoring and band rendering in the tree behind a header toggle; remove mainline privileging under `--repertoire` |
| `chesstree/utils.py` | Parser/formatter for the `[%game ...]` annotation, including the percent-escaping above |
| `chesstree/utils.py` | Parser/formatter for the `[%game ...]` annotation, including the percent-escaping above |

## Approach

### Phase 1 — counting and pruning (merge script)

Count games through every node. Slice each game to `min(divider_ply, prune_boundary)` rather than
to the divider ply alone; this is what kills the singleton tails and cuts eval cost by roughly 10x.
Prune at the build-time floor N=3. Attach each game's record to the deepest surviving node on its
line.

### Phase 2 — eval cache

Wrap the existing `make_engine_provider` in a SQLite-backed cache. The provider interface does not
change, so `annotate_evals` and `apply_leaf_evals` are untouched.

Cache-key rules, all forced by the current signature
`make_engine_provider(engine_path, limit, *, multipv)`:

- **The key must encode the whole limit, not just depth.** `merge_openings.py:452–455` builds
  `Limit(time=…)` when `--eval-time` is given and `Limit(depth=…)` otherwise, with time taking
  precedence. A depth-only key would store a 0.1-second eval under a null depth and later serve it
  for a depth-20 request. Serialize the limit into the key as a canonical string over every set
  field (`time`, `depth`, `nodes`, `mate`), plus `multipv`.
- **A time-limited eval is not reproducible.** Wall-clock results vary with machine load, so a
  `time=` key must additionally record the engine id and be treated as best-effort. Store it, but
  a `--no-eval-cache` escape hatch must exist for re-runs that need fresh numbers.
- **Store the score in a perspective-independent form.** The provider returns a `chess.engine.PovScore`,
  which is relative to the side to move. Persist white-perspective cp/mate and rebuild the `PovScore`
  for the queried board's turn on read, so a cached entry cannot flip sign.
- **Never cache `None`.** The provider returns `None` on engine error (`leaf_evaluator.py`
  provider `except` branch). Negative caching would make one transient failure permanent.

Evaluate the ~469 node positions (row evals) and the ~2,677 per-game opening-end positions. First
build is 45–90 minutes; subsequent builds are near-free.

### Phase 3 — schema and exporters

Promote annotations to typed fields, thread `games` / `stats` / `gameCount` through the d3tree
exporter.

### Phase 4 — template

Threshold slider (build-time floor 3, slider 3→50, default 10) with client-side re-attachment; the
chosen threshold persists to `localStorage` under its own key, following the existing
`chesstree_eval_config` precedent.

Summary table gains a **category** column (*prep hole* / *conversion* / *fragile* / *strong suit*,
per *Weak-spot definition*), plus `games`, `score` and average-opponent-rating columns. The score
cell shows the mean, `n`, and the 95% interval. Default sort is by **Wilson lower bound ascending**,
with a **minimum of 10 games** required before a row is eligible to be listed as a weak spot (rows
below the guard stay reachable but are not ranked). The average-rating column renders as "—" when no
game on the row carries a rating.

Both evals are labelled with the ply they were measured at (*Eval provenance*). Each row expands to
its game list with result, per-game opening-end eval, opponent rating and an outbound link, headed
by one line noting that per-game evals are measured deeper than the row eval. Barchart buckets games
rather than lines.

To make client-side re-attachment testable, the re-attachment algorithm lives in one small pure JS
function taking `(gameRecords, threshold)` and returning a node→games map, with no DOM access — see
the parity test below. The Wilson lower bound, the four-way categorisation and the family-anchor
computation are likewise pure functions, unit-testable without a DOM.

### Phase 5 — opening-family grouping

Summary rows are grouped under collapsible family headers ordered by Wilson lower bound, and the
mainline privileging in `collectVariationRows()` is removed under `--repertoire`. The tree gains
family bands anchored per *Opening-family grouping*, behind a header toggle defaulting to on.

Phase 5 depends on the family field reaching the template (Phases 1 and 3) but is otherwise
independent of the slider and the barchart, so it can be built in parallel with the rest of Phase 4.

## Risks

- **Eval cost is the schedule risk.** 2,677 positions at depth 20 is 45–90 minutes uncached. If the
  cache lands late, every iteration is painful. Build Phase 2 before Phase 4.
- **`_subtreeResultScore` silently returns nothing** if results are not re-sourced from `games[]`.
  It walks `moves[].result`, which no longer exists for payload games. A silent empty aggregate is
  the most likely defect in this whole change — hence the explicit test below.
- **Client-side re-attachment drift**: the browser's re-attachment at threshold T must agree with
  what the merge script would have produced at threshold T. Divergence here is silent and
  misleading. Two implementations of one algorithm across a language boundary — covered by the
  parity test below, which is the only thing standing between this risk and production.
- Threshold 10 giving 469 nodes is inferred to render acceptably from the `caro-advanced.pgn`
  baseline (843 nodes). This is an inference from a size comparison, not a measured render. Verify
  early with a real generated file.
- **Statistical noise is only damped, not removed.** The Wilson lower bound and the 10-game guard
  reduce false weak spots; they do not eliminate them, and the noise model understates reality
  (ternary scores, opponent spread). Flagged for human re-review once a real file exists — see
  *Ranking under small samples*.
- **Bands overlay the most fragile code in the template.** Collapse, drag, zoom and the prune
  slider all move nodes, and a band must track its anchor through every one of them. A band that
  drifts from its subtree is worse than no band, because it mislabels lines. The header toggle is
  the mitigation: if bands cannot be made to track reliably, ship them off by default rather than
  destabilising the tree view.
- **Band anchors move when the threshold moves.** Anchors are computed after pruning, so dragging
  the slider can add, remove or re-site them. Anchors must be recomputed on threshold change, not
  cached from the build — a stale anchor set would label the wrong regions.
- **`opening.name` is Lichess-only.** Without the ECO fallback, every Chess.com game lands in
  `"Unknown"`, which would make grouping look broken on multi-source repertoires. The fallback
  chain is not optional.
- **Family purity is not guaranteed.** The 90% anchor threshold means a band can contain up to 10%
  foreign games, and 8.1% of games sit under no anchor at all. The UI must show purity rather than
  imply the band is exhaustive.

## Known limitations (documented, not implemented)

- **Pruning hides *which* continuation is bad.** A poor score at a pruned node may come from one bad
  sub-line among several, but the pruned subtree is gone and the drill-down jumps straight from the
  region to individual games. The intended workaround is the threshold slider: drag it down to
  expose the sub-structure under a suspicious row. This is a real gap in localisation and is
  accepted for this cut — no code change is planned for it. Worth revisiting only if the slider
  turns out not to serve the workflow in practice.

## Test strategy

Each test below names the specific failure it must catch.

- `test_merge_openings.py` — pruning: given a synthetic set where one line has 2 games and another
  has 5, at floor 3 assert the 2-game line's nodes are **absent** from the tree and both its games
  appear in the parent's `games` list. Catches: pruning dropping games instead of re-attaching them.
- `test_merge_openings.py` — attachment depth: assert each game attaches to the **deepest** node on
  its line with count >= floor, not to the root. Catches: over-aggressive attachment collapsing
  everything to one node.
- `test_merge_openings.py` — hygiene: a `noStart` game and a 4-ply resign are excluded; a 20-ply
  resign is kept. Catches: the filter silently dropping legitimate short decisive games.
- `test_merge_openings.py` — mode gate: without `--repertoire` the merged output for a fixture set
  is byte-identical to today's and contains no `[%game ...]`; with `--repertoire` but no `--color`
  the script exits non-zero. Catches: the new feature changing existing single-opening merges, and
  a repertoire build silently scoring from the wrong side.
- `test_utils.py` — `[%game ...]` parse/format round-trip, including an opponent name containing
  `|` and `]`, a URL containing `%`, and an **empty rating field**. Catches: delimiter collision
  corrupting records, and an absent rating shifting every later field by one.
- `test_json_exporter.py` — a node with 3 `[%game ...]` annotations produces `games` of length 3
  and `stats.games == 3`; `schema_version` is `1.3.0`. Catches: promotion dropping or duplicating
  records.
- `test_json_exporter.py` — rating aggregation: 3 games with ratings 1800, 2000 and *absent* gives
  `stats.avgOpponentRating == 1900` over a rated count of 2, not 1266 over 3; 3 games with no
  rating at all give no average rather than `0`. Catches: missing ratings being silently counted
  as zero and dragging every average down.
- `test_json_parser.py` — PGN → JSON → PGN leaves `[%game ...]` byte-identical. Catches: the
  lossless-round-trip guarantee regressing.
- `test_leaf_evaluator.py` — cache hit returns the stored score **without** calling the provider
  (assert provider call count is 0 on second call); a different depth is a cache **miss**. Catches:
  stale shallow evals being served for a deeper request.
- `test_leaf_evaluator.py` — key completeness: a `Limit(time=0.1)` entry and a `Limit(depth=20)`
  entry for the same FEN do not collide, and differing `multipv` is a miss. Catches: a time-limited
  eval being served for a depth request, which a depth-only key would do silently.
- `test_leaf_evaluator.py` — a cached entry read back for a board where **black** is to move returns
  the same white-perspective evaluation as when it was written from a white-to-move board. Catches:
  a `PovScore` being persisted relative to the mover and flipping sign on read.
- `test_leaf_evaluator.py` — a provider returning `None` writes no row, and the next call reaches
  the provider again. Catches: negative caching making one transient engine error permanent.
- `test_d3tree_exporter.py` — `games`, `stats`, `gameCount` reach the segment dicts. Catches: the
  exporter silently discarding the new fields.
- Re-attachment parity — the pure JS re-attachment function is executed under `node` against a
  committed fixture of game records, and its node→games map at thresholds 3, 10 and 20 is compared
  against the merge script's own output for the same fixture at the same thresholds. Catches: the
  browser showing a different set of games at a threshold than the pipeline would have produced —
  the silent-drift risk above. If `node` is unavailable the test skips rather than passes.
- Score aggregation: for a node with games `1-0, 0-1, 1/2-1/2` and `forBlack=false`, assert the
  aggregate is `1.5/3`. Catches the silent-empty-aggregate risk above.
- Score aggregation, payload-only: a node whose results exist **solely** in `games[]`, with no
  `moves[].result` anywhere in the subtree, still aggregates non-empty. Catches: `_subtreeResultScore`
  being left walking `moves[].result` (template line 2342) and returning a silent empty result for
  every pruned node.
- Wilson lower bound — for 2 points from 9 games assert the bound is ≈0.102 (mean 0.222), and assert
  a row with 8/10 ranks **below** (worse than) a row with 80/100 despite the identical mean. Catches:
  the sort key silently falling back to the raw mean, which is the exact defect that would put
  fabricated small-sample weak spots back at the top of the default view.
- Categorisation — with the default equal band (±0.5), assert a row with below-average score and
  node eval −1.2 is `prep hole`, the same score with eval +0.1 is `conversion`, above-average score
  with eval −1.2 is `fragile`, and above-average with +0.1 is `strong suit`; then assert every one
  of those flips correctly under `forBlack=true`. Catches: the eval sign not being flipped for a
  black repertoire, which would label every genuine prep hole a strong suit.
- Eval provenance — a row whose node eval comes from ply 12 and whose games' evals come from plies
  18–24 renders **both** ply labels, and they differ. Catches: the two evals being presented as
  interchangeable, which makes a legitimate row/bucket disagreement look like a bug.
- Family resolution — a Lichess game with `opening.name = "Sicilian Defense: Najdorf"` resolves to
  family `Sicilian Defense`; a Chess.com game with no `opening` field but an `ECO` header resolves
  via the ECO fallback; a game with neither resolves to `Unknown` and is still present in the
  output. Catches: Chess.com games silently collapsing into `Unknown` on multi-source repertoires,
  and `Unknown` games being dropped rather than grouped.
- Family anchoring — on a fixture where one family is 100% pure at ply 2 and another only becomes
  pure at ply 6, assert both are anchored at the correct ply, and assert a node that is 85% one
  family is **not** anchored (below the 90% threshold). Catches: anchors being placed at the root
  child regardless of where the family actually resolves, which is the exact mistake the measured
  `opening.ply` data rules out.
- Anchor recomputation — assert the anchor set at threshold 5 differs from the set at threshold 20
  on a fixture built to move one anchor. Catches: anchors being computed once at build time and
  going stale when the slider moves.
- Mainline retirement — under `--repertoire`, assert `collectVariationRows()` returns no row marked
  as mainline and that row order is driven purely by the ranking key. Catches: the fetch-order
  artifact continuing to be rendered as signal.

All work is gated on `python -m pytest tests/ -q` passing.

## Out of scope

- Splitting the repertoire into multiple trees with a selector. Note that *opening-family grouping*
  delivers the navigational benefit the brainstorm wanted from splitting, without a partition:
  families are tags over one tree, so transpositions and unbanded trunk stay representable.
- Transposition merging (measured at ~6% duplication). Note the consequence: because the same
  position reached by two move orders counts as two trie nodes, a line's true frequency can be
  split across them and fall under the threshold, hiding it. At ~6% duplication this is rare, but
  a line that disappears at threshold 10 and reappears at 5 may be a transposition artefact rather
  than a genuinely rare line.
- Endgame/middlegame analysis beyond the existing opening divider.

## Implementation todos

Dependency-ordered. A fresh session can rehydrate its todo tracker from this table directly.
"Ready" means all dependencies are done; the three with no dependencies can start immediately and
are independent enough for parallel worktrees.

| id | task | depends on |
|---|---|---|
| `game-annotation` | `[%game ...]` parse/format helpers in `chesstree/utils.py`, with percent-escaping of `%`, `\|` and `]` and a fixed field count. Must survive opponent names containing `\|` and `]`, and an empty rating field. | — |
| `eval-cache` | SQLite eval cache at `~/.cache/chesstree/evals.db`, key (normalized FEN, engine id, canonical limit spec incl. `multipv`), wrapping `make_engine_provider`. Store white-perspective scores; never cache `None`; add `--no-eval-cache`. Provider interface unchanged. | — |
| `merge-counting` | Per-node game counts; slice to `min(divider_ply, prune_boundary)`; prune at floor N=3. | — |
| `source-rating` | Add optional `opponent_rating` to `SourceGame` and populate it from Lichess and Chess.com; `None` when absent or unrated. | — |
| `merge-mode-gate` | New `--repertoire` flag gating the whole feature; `parser.error` when it is set without `--color`; without it, output is unchanged from today. | `merge-counting` |
| `merge-attach` | Attach each game record to the **deepest** surviving node on its line, including the opponent rating field. | `game-annotation`, `merge-counting`, `source-rating` |
| `merge-hygiene` | Drop `noStart` and sub-6-ply games. | `merge-counting`, `merge-mode-gate` |
| `render-spike` | Generate a real threshold-10 d3html and confirm it renders. Validates the plan's core premise. | `merge-counting` |
| `schema-promote` | Promote annotations to typed `games` / `stats` / `gameCount`, including `stats.avgOpponentRating` over rated games only; bump schema to 1.3.0 + changelog entry. | `game-annotation`, `merge-attach` |
| `schema-roundtrip` | PGN → JSON → PGN leaves `[%game ...]` byte-identical. | `schema-promote` |
| `d3tree-fields` | Thread `games`, `stats`, `gameCount` onto segment/move dicts. | `schema-promote` |
| `tpl-score-agg` | Rewrite `_subtreeResultScore` to sum `node.games[].result`. **Highest-risk change.** | `d3tree-fields` |
| `tpl-barchart` | Bucket individual games by per-game opening-end eval instead of rows by `lastMove.eval`. | `d3tree-fields`, `eval-cache` |
| `tpl-stats` | Pure JS Wilson 95% lower bound + four-way score×eval categorisation, reusing the `_EVAL_DEFAULTS` equal band and honouring `forBlack`. No DOM. **Needs human re-review of the statistics once a real file exists.** | `tpl-score-agg` |
| `tpl-columns` | `category` / `games` / `score` (mean, n, interval) / avg-opponent-rating columns, both evals labelled with their ply, sort by Wilson lower bound asc with a 10-game listing guard, row drill-down. | `tpl-score-agg`, `tpl-stats` |
| `tpl-slider` | Client-side threshold slider 3–50 (default 10, persisted to `localStorage`) with re-attachment from stored line tails, extracted as a pure `(gameRecords, threshold)` function. | `tpl-columns` |
| `reattach-parity` | Parity test running the pure JS re-attachment under `node` against the merge script's output at thresholds 3, 10 and 20. | `tpl-slider` |
| `family-resolve` | Resolve each game's opening family: Lichess `opening.name` truncated at `:`, ECO-header fallback, then `Unknown`. Add `opening_family` to `SourceGame` and carry it on the `[%game ...]` record. | `game-annotation`, `source-rating` |
| `family-node` | Compute each node's majority family and purity share; thread `family` and its share through `json_exporter` and `d3tree_exporter`. | `family-resolve`, `d3tree-fields` |
| `tpl-family-groups` | Group summary rows under collapsible family headers showing aggregate games, score with interval and worst category; order families by Wilson lower bound. | `family-node`, `tpl-columns` |
| `tpl-mainline-retire` | Remove mainline privileging from `collectVariationRows()` and the mainline row class under `--repertoire`; leave non-repertoire output unchanged. | `tpl-family-groups` |
| `tpl-band-anchor` | Pure JS family-anchor computation (shallowest node ≥90% one family and ≥10 games), recomputed on threshold change. No DOM. | `family-node` |
| `tpl-bands` | Render family bands as labelled, tinted, collapsible regions over the tree, tracking their anchors through collapse, drag, zoom and slider changes; header toggle defaulting to on. | `tpl-band-anchor`, `tpl-slider` |

Suggested build order: `eval-cache` and `render-spike` early — the first removes a 45–90 minute
penalty from every later iteration, the second validates the premise before the template work is
committed to. `tpl-bands` is the most fragile item and the one most likely to be deferred
off-by-default; nothing else depends on it.

## Resolved decisions (formerly open questions)

1. **Threshold slider persistence** — yes, persist to `localStorage` under its own key, matching
   the existing `chesstree_eval_config` precedent.
2. **Average opponent rating in `stats`** — yes, in the first cut, with absent ratings handled
   explicitly: excluded from the average, counted separately, and rendered as "—" when no game on
   a row is rated.
3. **Min-games guard for weak-spot ranking** — **10**. Rows below it remain visible and reachable
   but are not eligible for the ranked weak-spot list.
