# Multi-source acquisition plan

Implements steps **3** and **6** of `plans/opening-merge-plan.md` (normalized source-game contract,
wire all sources through it) and then the **Chess.com acquisition plan** section of that document.

Companion plans:
- `plans/opening-merge-plan.md` — the umbrella plan (merge, slicing, leaf labels)
- `plans/opening-end-divider-plan.md` — `chesstree/opening_divider.py` (**landed**)
- `plans/leaf-evaluation-plan.md` — `chesstree/leaf_evaluator.py` (**landed**)

---

## Goal

Make `scripts/merge_openings.py` source-agnostic, then add Chess.com as a second acquisition
source **that can be merged together with Lichess in a single run**.

The purpose of multi-source merge is to see **one player's performance in an opening across
platforms**. The merged tree is the comparison surface: games from every account the player owns
converge on the same variations, so the leaves show how that player actually does in a line
regardless of where they played it. This is the reason the feature exists, not a convenience.

Local-directory acquisition is **not implemented in this slice**, but it is a first-class future
source in the same merge. The acquisition layer must therefore be a **list of source specs**, so
adding a local source later is purely additive — a new adapter plus a new flag, with no rework of
the contract, the merge, or the CLI shape.

## Current state (validated)

- `python -m pytest tests/ -q` → **551 passed, 3 deselected** on `experiment/merge-openings`.
- `chesstree/opening_divider.py` and `chesstree/leaf_evaluator.py` are landed and already wired
  into `scripts/merge_openings.py`. Neither is a blocker for Chess.com.
- `scripts/merge_openings.py` (490 lines) is Lichess-NDJSON shaped end to end. Every function
  below takes a raw Lichess `game_dict`:

  | Function | Lichess coupling | Chess.com reality |
  |----------|------------------|-------------------|
  | `_boards_from_moves` | replays `game["moves"]` SAN string | no `moves` field |
  | `find_filter_ply` | same `moves` string | must replay the parsed PGN |
  | `get_opponent_name` | `players.{white,black}.user.name` / `.userId` | `white.username` / `black.username` |
  | `create_slice` | `game["pgn"]`, `game["id"]`, hardcoded `https://lichess.org/{id}` | `game["pgn"]`, `game["url"]` |
  | `main` variant check | `game["variant"] != "standard"` | `game["rules"] != "chess"` |
  | `--color` | server-side Lichess query param | no server filter; client-side |
  | `--max-games` | server-side `max` param | none; must bound archive walk |
  | `--cache` | JSON list of Lichess dicts | different payload shape |

## Validated API facts

### Chess.com PubAPI

Source: <https://www.chess.com/news/view/published-data-api>, plus live probes of
`/pub/player/hikaru/games/archives` and `/pub/player/hikaru/games/2024/01`.

- Archives index: `GET /pub/player/{username}/games/archives` → `{"archives": [url, ...]}`,
  ascending by month. Hikaru has ~140 entries.
- Monthly archive: `GET /pub/player/{username}/games/{YYYY}/{MM}` → `{"games": [...]}`.
  Hikaru 2024/01 = **1045 games** in one month.
- Per-game keys (probed): `url`, `pgn`, `time_control`, `end_time`, `rated`, `accuracies`,
  `tcn`, `uuid`, `initial_setup`, `fen`, `time_class`, `rules`, `white`, `black`, `eco`.
- **Within an archive, `games` is sorted ascending by `end_time` (oldest first).** Probed on
  hikaru 2024/01: 1045 entries, `ts == sorted(ts)` → `True`, `sorted(reverse=True)` → `False`.
- `white` / `black` are objects with `username`, `rating`, `result`, `uuid`, `@id`.
- **No inline evals.** Probe of all 1045 games in 2024/01: `%eval` present in **0**,
  `%clk` present in **1045**. Chess.com PGN never carries `[%eval ...]`.
- Standard-chess marker is `rules == "chess"`. `initial_setup` gives the start FEN
  (all 1045 were the standard start position).
- Rate limiting, quoted: *"Your serial access rate is unlimited. If you always wait to receive
  the response to your previous request before making your next request, then you should never
  encounter rate limiting."* Parallel requests may return `429`.
- They ask for a **recognizable User-Agent containing contact information**; abnormal activity
  may get an application blocked outright.
- Endpoints cache-refresh at most every 12 hours.

### Lichess

Source: `lichess-org/api` OpenAPI spec, `doc/specs/tags/games/api-games-user-username.yaml`
and the `## Rate limiting` section of `doc/specs/lichess-api.yaml`.

- `/api/games/user/{username}` stream is throttled: **20 games/sec anonymous**,
  **30/sec OAuth**, **60/sec for your own games**. This is server-side pacing, not an error.
- Global rule: *"Only make one request at a time."* On `429`, wait at least one minute.
- The endpoint already supports `since` and `until` query params, in **epoch milliseconds**.

## Design decisions (confirmed with the human)

1. **Refactor first.** Land the source-agnostic contract as its own change, then add Chess.com.
2. **Eval policy.** When a source carries no inline evals and the local engine is unavailable,
   print a loud warning to stderr and continue producing an eval-less merge. Do not fail.
3. **Fetch bounding.** `--since` / `--until` accept `YYYY-MM` and are **optional**. When omitted,
   fall back to a newest-first walk bounded by `--max-games`.
4. **Separate username per platform.** Lichess and Chess.com usernames rarely match even for the
   same person, so each source takes its own username flag. Supplying more than one means fetch
   from all of them and merge the results into one PGN.
5. **Leaf labels do not show the platform.** They stay `vs [{opponent}]({url})` on every source.
   The URL implies the platform; no visible marker is added for now. `SourceGame.source` is still
   carried, but only for warnings and diagnostics.

---

## Part 1 — source-agnostic contract

### The contract

New module `scripts/sources.py` (kept beside the script; not part of the installed `chesstree`
package, matching the "standalone repository script" decision in the umbrella plan).

```python
@dataclass(frozen=True)
class SourceGame:
    game: chess.pgn.Game        # parsed source game
    boards: list[chess.Board]   # [initial, after ply 1, ...]; main line only
    opponent: str               # display name of the non-requesting player
    url: str                    # canonical game URL for the leaf label
    source: str                 # "lichess" | "chesscom" | "local"
    game_id: str                # for warning messages
    has_inline_eval: bool       # True when the PGN carries [%eval ...]
```

`boards` is derived once, from the parsed `game` main line, and reused by both the FEN filter and
`opening_divider.opening_end_ply`. This removes the Lichess-only `moves` SAN string entirely.

### Acquisition interface

Each source exposes a generator so callers stream rather than buffer:

```python
def iter_games(spec: SourceSpec) -> Iterator[SourceGame]: ...
```

Sources own only: HTTP, payload shape, opponent/url extraction, variant filtering, and their own
bounding parameters. Everything downstream is shared.

### Source specs — multiple sources per run

Acquisition is driven by a **list** of source specs built from the CLI, not by a single `--source`
choice:

```python
@dataclass(frozen=True)
class SourceSpec:
    source: str                 # "lichess" | "chesscom" | "local" (local deferred)
    username: str               # the per-platform username (or directory, for local)
    max_games: int | None
    cache_path: Path | None
```

`main` builds `specs: list[SourceSpec]` from whichever username flags were supplied, then:

```python
sources = [g for spec in specs for g in iter_games(spec)]
```

Everything after that point — FEN filter, divider, slice, merge, eval — is unchanged and sees a
single flat list. Adding the deferred local-directory source later means writing one more adapter
and one more flag; nothing downstream moves.

Shared, non-per-source settings (`--fen`, `--color`, `--since`, `--until`, engine flags, output)
stay single flags applied to every spec. `--color` is semantically the same intent on every
platform ("games where the player had this colour"); each adapter resolves it against **its own**
username.

### Refactor of `scripts/merge_openings.py`

| Current | After |
|---------|-------|
| `_boards_from_moves(moves_str)` | deleted; boards built in `sources.py` from the parsed game |
| `find_filter_ply(game_dict, fen)` | `find_filter_ply(boards, fen)` — pure, source-agnostic |
| `get_opponent_name(game_dict, user)` | moves into the Lichess source adapter |
| `create_slice(game_dict, ...)` | `create_slice(src: SourceGame, filter_ply, opening_end_ply)` |
| `fetch_lichess_games` / cache helpers | move into `sources.py` Lichess adapter |
| variant check in `main` | per-source, inside the adapter |
| `Event` header `f"Opening repertoire ({args.username})"` (line 472) | `f"Opening repertoire ({', '.join(f'{s.source}:{s.username}' for s in specs)})"` |
| no-middlegame fallback `opening_end_ply = len(moves_str.split())` | `opening_end_ply = len(src.boards) - 1` |
| leaf label built inline in `create_slice` | `_leaf_label(opponent, url)` helper (see below) |

Two rows need explanation.

**`Event` header.** `scripts/merge_openings.py:472` is the last place downstream of acquisition
that reads the single `args.username`; every other use (`get_opponent_name`, `create_slice`) moves
into the adapters. With `--username` gone it would be a `NameError`. The replacement names the
source alongside the username because two platforms can carry the same username string, and
because the header is metadata about *whose* repertoire this is — unlike leaf labels, which stay
platform-agnostic per human decision 5. Note that the header is set in `main`, i.e. **outside** the
regression pin's stable entry point, so its value must be pinned by a separate small test.

**Leaf label helper.** Extract the currently-inline format into:

```python
def _leaf_label(opponent: str, url: str) -> str:
    return f"vs [{opponent}]({url})" if url else f"vs {opponent}"
```

Output for Lichess and Chess.com is byte-identical to today (both always supply a `url`). The
empty-`url` branch exists so the deferred local-directory source, which has no URL, does not render
a broken markdown link `vs [opp]()` — and does not force a leaf-label format change later, which
would be exactly the downstream rework the "purely additive" claim promises to avoid.

**No-middlegame fallback.** `main` currently derives the fallback ply count from the Lichess
`moves` string. That string is being deleted, so the fallback is re-expressed against `boards`:
`len(boards) - 1` is the main-line ply count, exactly what `len(moves_str.split())` produced
(`_boards_from_moves` prepends the initial board).

### `apply_leaf_evals` — one fix needed

`merge_game_slices` and `extract_eval` are genuinely source-agnostic and move unchanged.
`apply_leaf_evals` is **almost** unchanged but has one real bug that multi-source amplifies.

`scripts/merge_openings.py:282–298` caches the first result per normalized FEN, **including
`None`**. Because transposition handling is deferred, two distinct leaf nodes can share a
normalized FEN. Leaf traversal is a DFS over `stack.pop()` (line 276), so visit order is not
meaningful. In the engine-absent path this means: if a Chess.com leaf (never has an inline eval) is
visited before a same-FEN Lichess leaf (has one), the cache pins `None` and the Lichess eval is
thrown away — non-deterministically.

Fix: the fallback must not let a `None` first visit pin the cache. Prescribed shape — **resolve
then write, in two phases**:

1. **Phase 1, resolve.** Walk every terminal leaf and build `fen -> eval_str`. For the provider
   path, call the provider once per unique normalized FEN (unchanged; that is where the expensive
   engine calls are, and there `None` means the engine genuinely failed on that position). **If the
   provider returns `None` for a FEN, that FEN then resolves via the same inline-eval fallback** —
   a provider failure must not skip the fallback. For the fallback path, a FEN resolves to the
   **first non-`None`** `extract_eval` among *all* leaves sharing that FEN.
2. **Phase 2, write.** Only then annotate every leaf from the resolved map.

Two phases are required, not optional. The current code computes and writes in a single
`stack.pop()` DFS pass, so a single-pass "pin on first non-`None`" would still leave any same-FEN
leaf that was processed *before* the non-`None` value was seen uncovered — i.e. still
order-dependent, and it would fail the both-DFS-orders test in the Test strategy.

Do **not** take the alternative of computing the fallback per leaf with no shared map: that leaves
the eval-less same-FEN leaf uncovered, which is a different leaf-coverage outcome and therefore a
different `N of M` warning count. The two approaches are not equivalent and the plan commits to the
shared-map one.

`merge_game_slices` and `extract_eval` stay as they are — already source-agnostic.
`apply_leaf_evals` stays source-agnostic in shape but needs one bug fix; see below.

### Cache format

The cache currently stores raw Lichess dicts in one file. Because a run can now span several
sources, the cache becomes **per source spec**, not per run. Each cached file stores its raw
source payloads plus the tag identifying what produced them:

```json
{"source": "lichess", "username": "...", "games": [ ...raw payloads... ]}
```

Reading a cache whose `source` or `username` does not match the spec requesting it is a hard error
with a clear message — a cache written for one platform must never be silently replayed as
another. Old-format caches (a bare JSON list) are rejected with a message telling the user to
delete and refetch; they are POC artifacts, not user data.

CLI shape for this: `--lichess-cache FILE` and `--chesscom-cache FILE`, each optional and each
bound to its own source spec.

### Eval-availability warning

The round-1 design computed one global `any(s.has_inline_eval for s in sources)`. Multi-source
broke that, and a per-source `any(...)` breaks the same way one level finer: **Lichess only embeds
`[%eval]` on games it has actually analysed**, so a single analysed game makes the whole Lichess
source look eval-covered while every leaf reached only by unanalysed games silently loses its eval.
Any `any(...)`-shaped check under-warns.

So the warning is keyed on **actual leaf coverage**, measured *after* `apply_leaf_evals` has run.
Count the terminal leaves — the same `all_leaves` set `apply_leaf_evals` iterates — that ended
without an `[%eval ...]` annotation, matched with the existing `_EVAL_RE` so `[%opening_end]` does
not interfere. If that count is non-zero, print:

```
Warning: 47 of 112 leaves have no [%eval] annotation and will not be
         coloured or included in the variation summary. (no local engine: <reason>)
```

The parenthetical reason is present only when the provider was `None`.

**The warning fires whenever the uncovered count is non-zero, regardless of whether the engine was
available.** A leaf can also end up uncovered with the engine present: `provider(board)` returns
`None` on an analyse error, and if that leaf has no inline eval to fall back on it stays bare. The
human's decision was to warn on what actually happened to the output rather than on source
metadata, and that reasoning applies identically here — gating on `provider is None` would
reintroduce exactly the kind of blind spot the decision was made to remove. Silence is reserved for
one case only: full coverage.

Then continue. This satisfies human decision 2 without any blind spot: it covers the mixed
Lichess+Chess.com case, the partially-analysed Lichess case, the Chess.com-only case, and the
engine-present partial-failure case with one mechanism.

`SourceGame.has_inline_eval` is still carried — it is useful diagnostics and keeps the adapters
honest — but it no longer drives the warning.

---

## Part 2 — Chess.com acquisition

### Fetch flow

1. `GET /pub/player/{username}/games/archives` → list of monthly URLs.
2. Select months. `--since` and `--until` are **independently optional**; each bound is applied
   only when present:
   - keep an archive when `month >= since` (if `--since` given), **and**
   - keep an archive when `month <= until` (if `--until` given).
   Both bounds are **inclusive of the whole month**. When neither is given, keep all archives.
3. Walk selected archives **newest first**, strictly serially. **Within each archive, iterate the
   `games` array reversed**, because Chess.com returns it ascending by `end_time` (validated
   above) — without the reverse, a `--max-games`-bounded run would return the *oldest* games of
   the newest month, contradicting the newest-first decision and diverging from Lichess, whose
   default sort is newest-first. Stop early once `--max-games` accepted games have been yielded
   (when `--max-games` is set).
4. For each game in an archive: skip when `rules != "chess"`, when `initial_setup` is present and
   `normalize_fen(initial_setup) != normalize_fen(chess.STARTING_FEN)`, or when `pgn` is
   missing/unparseable (warn on stderr). Use `chesstree.utils.normalize_fen` rather than an exact
   string compare, matching how the rest of the codebase compares positions.
5. Apply the client-side `--color` filter by comparing `white.username` / `black.username`
   case-insensitively against `--username`.
6. Build the `SourceGame`.

### HTTP behaviour

- Strictly serial requests — no threads, no concurrency. This is the documented way to stay
  unlimited.
- User-Agent: `chesstree/merge_openings (https://github.com/benedekfazekas/chesstree)`
  (the existing string already carries contact info).
- On `HTTPError 429`: sleep and retry with backoff, bounded retries, then fail with a clear
  message. On `404` for the archives index: report "no such Chess.com user or no public games".

### Leaf labels

`vs [{opponent}]({url})` — unchanged, on every source. Chess.com supplies `url` directly, so the
format is identical across platforms and a merged cross-platform leaf reads as one uniform list of
opponents. Per human decision 5, **no platform marker is added**: the URL already identifies the
platform, and the merged tree is meant to show the player's performance in the line, not a
per-platform breakdown. `SourceGame.source` is still carried for warnings and diagnostics.

### CLI changes

Per-source flags (at least one username is required; supplying both fetches both and merges):

```
--lichess-username NAME       optional
--chesscom-username NAME      optional
--lichess-max-games N         optional, per source
--chesscom-max-games N        optional, per source
--lichess-cache FILE          optional, per source
--chesscom-cache FILE         optional, per source
```

Shared flags applied to every source:

```
--fen FEN                     required (unchanged)
--color {white,black}         optional; resolved per source against that source's username
--since YYYY-MM               optional
--until YYYY-MM               optional
--output / --engine / --eval-depth / --eval-time   unchanged
```

The old `--username`, `--max-games` and `--cache` flags are **replaced**, not kept as aliases —
`merge_openings.py` is an experimental POC script with no released interface to preserve, and a
bare `--username` is ambiguous once two platforms exist. Supplying no username at all is an
argparse-level error naming both flags.

`--max-games` is deliberately per source rather than a global budget: platform volumes differ
wildly (one busy Chess.com month was 1045 games), and a shared budget would let one platform
starve the other, which defeats the cross-platform comparison the feature exists for.

`--since` / `--until` are independently optional and are **inclusive of the whole named month** on
both sources, so the same flag value selects the same months everywhere:

- **Lichess**: converted to epoch **milliseconds, UTC**, and passed as the `since` / `until` query
  params. `--since YYYY-MM` → `YYYY-MM-01T00:00:00.000Z`. `--until YYYY-MM` → the **last**
  millisecond of that month, `YYYY-MM-{last day}T23:59:59.999Z`. Using the first millisecond for
  `until` would exclude the whole named month, while Chess.com would include it — the two sources
  must not disagree at the range edges.
- **Chess.com**: month selection over the archives index, per Fetch flow step 2.

`--color` stays a single flag: forwarded server-side for Lichess, applied client-side for
Chess.com. `--max-games` stays a single flag: server-side `max` for Lichess, early-stop for
Chess.com.

---

## Test strategy

All new tests use recorded/stubbed payloads. **No live network calls in the test suite** — this
matches the existing `TestFetchLichessGames` pattern, which monkeypatches `urllib.request.urlopen`.

New file `tests/test_sources.py`:

- `SourceGame` construction from a Lichess payload and from a Chess.com payload produce the same
  downstream-visible shape (boards, opponent, url, has_inline_eval).
- Chess.com opponent resolution for both colours, case-insensitive username match.
- Chess.com variant rejection (`rules != "chess"`, non-standard `initial_setup`).
- Chess.com archive month selection: `--since` only, `--until` only, both, and neither;
  newest-first archive ordering; **reversed within-archive ordering** (assert the newest games of
  the newest archive are the ones yielded, not the oldest); `--max-games` early stop (assert later
  archives are never requested).
- `--since`/`--until` → Lichess epoch-millis conversion: `--until YYYY-MM` maps to the last
  millisecond of that month, so the named month is included.
- `429` retry/backoff path with a stubbed opener.
- Cache round-trip including the source tag; a cache whose `source` mismatches raises; a cache
  whose `username` mismatches raises; legacy bare-list cache raises with the documented message.
- Spec building: no username supplied → argparse error naming both flags; one username → one spec;
  both usernames → two specs, each carrying its own username, `max_games` and cache path.

Changes to `tests/test_merge_openings.py`:

- `TestFindFilterPly` moves to the new pure `boards`-based signature.
- `TestGetOpponentName`, `TestCreateSlice`, `TestFetchLichessGames`, `TestLocalCutoffPath`,
  `TestCacheHelpers` updated for the new call shapes; behaviour assertions preserved.
- **Multi-source merge in one run**: stubbed Lichess + Chess.com payloads whose games share an
  opening prefix merge into a single tree, with both platforms' labels accumulating on the same
  leaf where they reach the same position. This is the feature's core purpose and must be pinned.
- **Leaf-coverage eval warning**: with no engine, a mixed run where some leaves get an eval from
  inline Lichess annotations and others (Chess.com, or unanalysed Lichess games) do not → the
  warning reports the correct `N of M leaves` count and the merge still succeeds.
- No engine, **every** leaf uncovered → warning reports `M of M`, merge produced, no `[%eval]` in
  output.
- No engine, **every** leaf covered by inline evals → **no** warning at all, and the existing
  Lichess fallback path still populates the evals (guards against regression).
- Engine present, all leaves resolved → no warning regardless of source mix.
- **Engine present but the provider returns `None` for a position with no inline eval to fall back
  on** → the warning still fires, without the "no local engine" parenthetical. This pins the H2
  decision that the warning is coverage-driven, not provider-gated.
- `apply_leaf_evals` same-FEN fallback: two distinct leaves sharing a normalized FEN, one with an
  inline eval and one without, in **both** DFS visit orders → both resolve to the non-`None` eval.
  This pins the G3 fix against the non-deterministic traversal order.
- `_leaf_label`: non-empty `url` renders `vs [opp](url)` byte-identically to today; empty `url`
  renders `vs opp` with no broken markdown link.
- `Event` header for one source and for two sources.

Acceptance gate: `python -m pytest tests/ -q` must stay green (551 existing tests plus new ones).

## Risks

- **Behaviour drift during the refactor.** Mitigation: Part 1 must produce a byte-identical merged
  PGN for a fixed set of raw Lichess payloads. Write this pin **before** the refactor.
  Important: the pin must **not** go through the on-disk cache, because Part 1 also changes the
  cache format — migrating a cache fixture mid-refactor is exactly the step that could hide real
  drift. Instead:
  1. Capture the golden merged-PGN string from a **pre-refactor** run.
  2. Commit the raw Lichess payloads as an in-repo fixture (a plain list of game dicts).
  3. Assert the **post-refactor** pipeline, fed the identical in-memory payloads through a stable
     entry point (the merge pipeline function, not `main`'s cache loading), produces the same
     string.
  The engine must be absent/stubbed in this test so eval output is deterministic.

  **Boundary, explicitly:** the golden must be captured at the same pipeline boundary on both
  sides, and that boundary **excludes the `Event` header**. `main` sets
  `merged.headers["Event"]` *after* merge and `apply_leaf_evals`, then exports with
  `StringExporter(headers=True)`. The `Event` value is deliberately changed by G1, so a golden
  captured from full pre-refactor `main` output could never match. Either export the merged game
  before the `Event` assignment on both sides, or strip/normalize `Event` on both sides. The
  header's own behaviour is pinned by the separate one-source/two-source test listed under Test
  strategy.
- **Boards from parsed PGN vs from the `moves` string.** Lichess `pgn` and `moves` should agree,
  but the divider is ply-sensitive. The byte-identical regression test above catches any drift.
- **Chess.com volume.** 1045 games/month is normal for an active account. Newest-first plus early
  stop keeps the default case cheap; without `--max-games` and without a range, a full walk is
  genuinely expensive and should print a progress line per archive.
- **Chess.com daily/unfinished games** may have odd or missing PGN. Handled by the skip-and-warn
  path in step 4.
- **`--max-games` counts differ slightly per source.** For Chess.com it counts games *after* the
  variant/pgn skips and the client-side colour filter. For Lichess the server-side `max` is applied
  before our client-side variant skip, so a Lichess run can yield *fewer* than `--max-games`. The
  divergence is marginal for opening corpora (variant games are rare) and is accepted, not fixed.
- **No cross-source game dedup.** `merge_game_slices` accumulates one label per slice with no
  game-identity check, so a game present in two sources would be counted twice at its leaf, mildly
  skewing the frequency picture the feature exists to show. For this slice it is practically
  impossible (a genuinely-played game exists on exactly one platform); it becomes real once
  local-directory acquisition lands and can hold an export of a remote game. **Accepted as a known
  limitation**, with dedup recorded as a follow-up for the local-source slice.
- **Local source needs an identity input.** The `SourceSpec` list is genuinely additive
  *downstream* — filter, slice, merge and eval only ever see plain strings the adapter filled in —
  and the `_leaf_label` helper above already handles the missing-URL case. But local games have no
  inherent "requesting user", so a local adapter will need a player-identity input to resolve which
  side is the opponent. That is an adapter-level concern, not a contract change, but the
  "one adapter plus one flag" claim should be read as "one adapter plus its own flags".

## Out of scope

- Local-directory acquisition. **Deferred implementation, not deferred design**: it is a
  first-class future source in the same merge (see Goal), so the `SourceSpec` list must make it
  additive — one adapter plus one flag, no downstream rework.
- Transposition longest-common-prefix handling (still deferred in the umbrella plan).
- Promoting `merge_openings.py` into the installed `chesstree` package.
- OAuth for Lichess (anonymous 20 games/sec is sufficient).
- Per-platform breakdown in the output (leaf labels stay platform-agnostic, human decision 5).

## Sequencing

Part 1 lands and is green before Part 2 starts. Part 2 adds only a new adapter plus CLI wiring;
it must not touch filter, slice, merge, or eval logic.

---

## Review log

### Round 1 — Grouchy Smurf, verdict `approve-with-fixes`

| Id | Severity | Finding | Resolution |
|----|----------|---------|------------|
| F1 | major | `--until YYYY-MM` boundary undefined; Lichess would exclude the named month while Chess.com included it | **Accepted.** Both bounds now explicitly inclusive-of-month; Lichess `until` maps to the last millisecond of the month, UTC. |
| F2 | major | Newest-first was specified at archive level only; Chess.com returns games oldest-first within an archive, so a `--max-games` run would return the oldest games of the newest month | **Accepted, and independently re-validated** — probe of hikaru 2024/01 (1045 games) confirms `end_time` is strictly ascending. Fetch flow step 3 now requires reversing the within-archive iteration; a test asserts it. |
| F3 | minor | One-sided `--since` / `--until` undefined for Chess.com month selection | **Accepted.** Step 2 now applies each bound independently. |
| F4 | minor | The `opening_end_ply is None` fallback still read the deleted `moves` string | **Accepted.** Refactor table now maps it to `len(src.boards) - 1`. |
| F5 | minor | The regression pin routed through the cache fixture, which Part 1 also changes — could mask drift | **Accepted.** Pin now runs on in-memory raw payloads through a stable entry point, independent of cache format. |
| Q1 | question | Should `initial_setup` be compared exactly or via `normalize_fen`? | **Decided by Brainy:** use `normalize_fen`, matching the existing convention shared by `chesstree/leaf_evaluator.py` and `scripts/merge_openings.py`. Written into Fetch flow step 4. |

No finding was rejected or deferred.

### Round 2 — Grouchy Smurf, verdict `approve`

All of F1–F5 and Q1 confirmed genuinely fixed in the real sections, not just logged. Grouchy
independently verified `len(boards) - 1 == len(moves_str.split())` by running `_boards_from_moves`
on 6-move, 1-move, and empty inputs, and confirmed no contradiction between the Lichess
last-millisecond `until` mapping and the existing query-string builder, nor between the reversed
within-archive iteration, the `--max-games` early stop, and the client-side `--color` filter.

One nit raised, **F6**: `--max-games` counts post-filter for Chess.com but pre-variant-skip for
Lichess. **Accepted as a documented known divergence** (recorded under Risks), not fixed — the
impact is marginal for opening corpora.

### Scope change — human, after round 2

The human corrected a misunderstanding in the plan: Lichess and Chess.com usernames rarely match
for the same person, and more importantly **multi-source merge in one run is the point of the
feature**, not a later nicety. The goal is to see a player's performance in an opening *across
platforms*, and local games are eventually part of that same merge.

Per the rework rules, a human scope change is a fresh start: the plan was re-planned from the new
facts and the review round counter reset to 0. Changes made:

| Area | Before | After |
|------|--------|-------|
| Goal | Chess.com as a second source | cross-platform merge is the stated purpose |
| CLI | `--source {lichess,chesscom}` + `--username` | per-platform `--lichess-username` / `--chesscom-username`; at least one required, both allowed |
| Acquisition | one source per run | `list[SourceSpec]`, flattened into one list of `SourceGame` |
| `--max-games` / `--cache` | single global flags | per source spec |
| Cache validation | source tag must match | source **and** username must match |
| Eval warning | one global `any(has_inline_eval)` | **per source** — the global form was silently wrong in a mixed run |
| Local directory | "contract must not block it" | first-class future source; adding it must be purely additive |
| Leaf labels | unstated | explicitly platform-agnostic (human decision 5) |

The per-source eval warning is the substantive bug this scope change exposed: in a mixed run the
Lichess games carry inline evals, so a global `any(...)` would have stayed silent while every
Chess.com leaf lost its eval.

### Round 1 (fresh cycle) — Grouchy Smurf, verdict `approve-with-fixes`

| Id | Severity | Finding | Resolution |
|----|----------|---------|------------|
| G1 | major | `Event` header at `merge_openings.py:472` still reads the removed `args.username` — the one surviving downstream single-username assumption | **Accepted.** Refactor table now maps it to `source:username` pairs; noted that it lives outside the regression pin's entry point and needs its own small test. |
| G2 | major | The per-source eval warning has the same blind spot one level finer: Lichess only embeds `[%eval]` on **analysed** games, so one analysed game silences the warning for a whole account | **Accepted and escalated to the human, who chose leaf-coverage warning.** The warning now counts leaves that actually ended without `[%eval]` after `apply_leaf_evals` and reports `N of M`. Any `any(...)`-shaped check under-warns; this one cannot. |
| G3 | minor | `apply_leaf_evals` FEN cache pins the **first** result including `None`, so on a same-FEN transposition a Chess.com leaf visited first can throw away a Lichess leaf's eval — non-deterministically, since traversal is `stack.pop()` DFS | **Accepted.** Fallback must not let a `None` first visit pin the cache; test pins both DFS orders. The stale "already source-agnostic" claim for `apply_leaf_evals` was corrected. |
| G4 | minor/question | Local source has no `url` and no natural `opponent`, so "one adapter plus one flag" understates it and an empty `url` would render a broken markdown link | **Accepted, settled now.** Leaf-label formatting extracted into `_leaf_label(opponent, url)`, which drops the link when `url` is empty — remote output stays byte-identical. Recorded under Risks that a local adapter will additionally need a player-identity input. |
| G5 | minor | No cross-source game dedup; a game present in two sources would double-count at its leaf | **Accepted as a documented limitation.** Impossible for Lichess+Chess.com in this slice; recorded as a follow-up for when local acquisition lands. |

Grouchy also confirmed, and I did not re-raise: F1–F6 and Q1 survive the scope change; per-source
`--color` resolution is sound; `merge_game_slices` is multi-source safe; cross-platform display-name
collisions are not misleading because merge is by move path and the URLs differ.

No finding was rejected. G2 was the one escalation; the human chose leaf-coverage counting.

### Round 2 — Grouchy Smurf, verdict `approve-with-fixes`

Grouchy confirmed G1–G5 genuinely resolved in the real sections, and verified `_leaf_label` is
byte-identical to the current inline string at `merge_openings.py:222`, and that an uncovered leaf
is reliably detectable after `apply_leaf_evals` (when `cached is None` the comment is left
untouched, so no `[%eval ...]` can be present) with `M` = the same `all_leaves` set.

| Id | Severity | Finding | Resolution |
|----|----------|---------|------------|
| H1 | major | The G3 fix offered two options, but only one satisfies the both-DFS-orders test the plan itself pins — and the two produce *different* leaf coverage, hence different `N of M` warning counts. Also, a single-pass fix is still order-dependent | **Accepted.** The plan now prescribes exactly one shape: **resolve all FEN evals, then write**, in two phases, with the fallback resolving to the first non-`None` among all same-FEN leaves. The per-leaf alternative is explicitly ruled out. |
| H2 | minor | The warning was gated on `provider is None`, so an engine-present run where the provider returns `None` for a position with no inline fallback left leaves silently uncovered | **Accepted, decided by Brainy.** The warning now fires whenever the uncovered count is non-zero, regardless of provider; the "no local engine" reason becomes an optional parenthetical. This follows directly from the human's choice to warn on actual output coverage rather than on metadata — gating on the provider would reintroduce the same class of blind spot. Pinned by a new test. |
| H3 | minor | The byte-identical F5 pin collides with the deliberately-changed `Event` header, since `main` exports with `headers=True` | **Accepted.** The Risks section now states the pin's boundary explicitly: capture on both sides excluding `Event` (export before the header assignment, or normalize it on both sides). The header is pinned by its own test. |

No finding was rejected.

### Round 3 — Grouchy Smurf, verdict `approve`

Loop A closed. Grouchy verified H1–H3 resolved in the real sections, and specifically traced every
existing `TestApplyLeafEvals` case (`tests/test_merge_openings.py:554–701`) against the two-phase
shape: **none of them fail or need updating**, because the G3/H1 transposition case (two *distinct*
leaves sharing a normalized FEN) is not exercised by any existing test, and the provider-path dedup
those tests pin is preserved. He also confirmed the `Event` header is the only header that diverges
pre/post refactor — `merge_game_slices` builds a fresh `chess.pgn.Game()` with all-default headers
— so excluding `Event` alone is sufficient for byte-identity.

Two non-gating findings, both marked settle-in-implementation:

- **J1** — the phase-1 bullet did not restate that a provider returning `None` for a FEN must still
  fall back to the inline eval. **Folded in** anyway as a one-clause addition, since it was free.
  The behaviour was already specified under the warning section and pinned by the existing
  `test_fallback_to_lichess_when_provider_returns_none`.
- **J2** — nit: the `EngineUnavailable` reason string is produced in the `except` block but is
  needed later at the warning site, so the implementation must stash it. No plan change required.

**The plan is approved and ready to implement.**
