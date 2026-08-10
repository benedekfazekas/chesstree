# Smurf Agent Team

Four custom Copilot agents for `chesstree`: one orchestrator, one architect, one builder, one
reviewer. The roles are split so that **thinking is expensive and rare**, while **routing is cheap
and constant**.

## The team

| Agent | File | Role | Model |
|-------|------|------|-------|
| 🧠 **Brainy Smurf** | `brainy-smurf.agent.md` | **Orchestrator.** Routes work, runs mechanical checks, tracks rework rounds, talks to the human. Does no planning, no triage, no code review. | `claude-haiku-4.5` |
| 📐 **Architect Smurf** | `architect-smurf.agent.md` | **Architect.** Authors plans, does root-cause analysis, triages review findings, acts as final gate. Invoked rarely. | `claude-opus-5` |
| 🔨 **Handy Smurf** | `handy-smurf.agent.md` | **Developer.** Implements and tests what the Architect specifies. | `claude-sonnet-4.6` |
| 😠 **Grouchy Smurf** | `grouchy-smurf.agent.md` | **Reviewer** (tester + technical writer). Semantic review of plans and diffs. Invoked selectively. | `claude-opus-4.8` |

## Why the architect and orchestrator are split

A post-mortem of the team's first feature measured where the money went:

| Role | Share of spend | Turns |
|---|---|---|
| Architect + orchestrator (combined, on `claude-opus-5`) | **52.7%** | 196 |
| Reviewer | 28.9% | 185 |
| Developer | **18.4%** | 175 |

Four-fifths of the cost went to *talking about* code rather than writing it, and most of the
combined architect/orchestrator turns were postman work — deliver a message, read a report, update
a todo. Splitting the role puts a cheap model on the frequent, mechanical turns and reserves the
expensive model for the handful of turns that need real judgement.

The other two findings that shaped this setup:

- **Cost is dominated by re-sent context**, not by thinking — roughly **102 input tokens per output
  token**. Every handoff rebuilds a context, so briefs cite files and sections instead of pasting
  them.
- **Six review rounds on a plan document** were the single largest line item, and produced a plan
  longer than the diff it described. Plan review is now capped at **one round**.

## Flow

```
human ⇄ Brainy Smurf ──▶ Architect Smurf   (plan, root-cause, triage, final gate)
                     ──▶ Handy Smurf       (implementation, rework)
                     ──▶ Grouchy Smurf     (review)
```

- **Brainy is the only agent that talks to the human** in orchestrated mode.
- **Brainy relays verbatim.** He never authors, summarises, triages, or judges. Assignments are
  written by Architect Smurf already addressed to their recipient.
- **Grouchy's findings go to Architect Smurf, never to Handy.** Handy only ever receives a decided
  work list.
- Typical cycle: Architect plans → Grouchy reviews the plan **once** → Handy implements →
  Brainy runs mechanical checks → Grouchy reviews → Architect triages → Handy fixes → Grouchy
  re-checks the fixed parts → Architect's final gate → Brainy reports.

## Division of labour

| Work | Who |
|---|---|
| Plan, root-cause, finding triage, final gate | **Architect** |
| Routing, round counting, todo tracking, status to human | **Brainy** |
| `pytest`, diff scope, vacuous-assertion greps, convention greps | **Brainy** (free — keeps them off Grouchy) |
| Logic tracing, edge cases, mutation-testing pins, plan/code divergence | **Grouchy** |
| Implementation, tests, rework | **Handy** |

## Match the ceremony to the risk

The full loop is for changes where a silent bug is expensive. It is not the default for everything.

| Full loop | Straight to Handy |
|---|---|
| Ordering, caching, concurrency, persistence formats | Docstring and comment fixes |
| Public contracts, data migrations, security surfaces | Renames, moves, mechanical refactors |
| Anything where a wrong result is silent | Changes fully covered by existing tests |
| New acquisition/IO adapters | Single-file, obvious, reversible edits |

## Standalone mode

**Architect, Handy and Grouchy can each be used directly, without orchestration.** For small tasks
this is the cheaper and faster path — a handoff costs a full context rebuild in each direction.

```bash
copilot --agent architect-smurf   # design question, plan, or bug diagnosis
copilot --agent handy-smurf       # small, well-scoped implementation
copilot --agent grouchy-smurf     # one-off review
```

In standalone mode the agent talks to the human directly, skips the ceremony (no plan file, no
todo tracking, no review loop), and runs its own checks. Each agent knows when to stop and
recommend the full team instead — typically when the task turns out to touch a high-risk surface
or grows well beyond what was asked.

## Unhappy path — the rework loops

Reviews finding problems is the **normal** case. Two loops handle it.

### Loop A — plan rework (capped at **one** round)

```
Architect plans ──▶ Grouchy reviews once ──findings──▶ Architect triages & revises ──▶ build
```

### Loop B — implementation rework (capped at **3** rounds)

```
Handy implements ──▶ Brainy checks ──▶ Grouchy reviews ──findings──▶ Architect triages
                 ──decided list──▶ Handy fixes ──▶ Grouchy re-checks fixed parts ──▶ …
```

The Architect triages **every** finding into one of three outcomes and says which:

| Outcome | Meaning |
|---------|---------|
| **Accept** | Finding is right → becomes a work item with evidence and a definition of "fixed". |
| **Reject** | Finding is wrong → send back the validated fact that disproves it. Evidence required, opinion not allowed. |
| **Escalate** | Facts cannot settle it → to the human with options and a recommendation. |

### Rules for both loops

- **Findings have stable ids** and carry across rounds with a status (open / fixed / rejected /
  escalated / withdrawn). Nothing silently disappears.
- **Disputes are settled by evidence or by the human** — never by whoever argues hardest.
- **Scope discipline.** Rework fixes the findings. New ideas become new work items.
- **If the plan itself was wrong**, Loop B stops and drops back to Loop A.
- **Brainy owns the round counter** and states the round number in every assignment.
- **Grouchy approves when it is genuinely good.** Hard to please, not impossible to please.

### Fidelity rules

From real post-mortems — each of these was a defect that actually happened:

- **The plan outranks the assignment.** The Architect cites the plan file and section instead of
  restating it, and copies any exact literal verbatim. Handy reads the plan section himself; if the
  assignment is thinner than or disagrees with the plan, the plan wins and he flags it. Grouchy
  reviews against the **plan** and treats a plan/assignment divergence as a finding against the
  assignment. *(A lost `f"Opening repertoire (…)"` wrapper regressed a user-visible title.)*
- **Surgical edits only.** Handy edits the lines that change rather than regenerating whole files.
- **Tests must be able to fail.** The Architect states what a test must detect; Handy builds
  fixtures that exercise those exact properties; Grouchy mutation-tests the load-bearing pins —
  break the behaviour, confirm the test goes red, revert. *(This found two tests that could never
  fail.)*
- **No duplicate reviews.** When Grouchy is queued, the Architect's pre-review is a cheap sanity
  check only; his real review is the final gate after Grouchy reports.
- **No model guessing.** Agents cannot introspect their own runtime model. Silence means "as
  pinned"; only an actually observed fallback gets reported.

### Round limit — hard stop at 3

Loop B is capped at **3 rounds** (a round = one review + one rework). At the end of round 3 without
approval, **Brainy halts and goes to the human.** No agent may start round 4 on its own authority.

Brainy presents: where we are, what is still open (findings by id + evidence), what has been tried,
and the Architect's honest **diagnosis of why the loop is not converging** — wrong plan, ambiguous
requirement, missing context, unvalidated assumption, oversized scope, or a dispute only the human
can settle — plus options with a recommendation.

| Human decision | Effect |
|----------|--------|
| **Carry on** | Human grants N extra rounds. Cap becomes N; same rules on exhaustion. Agents never grant themselves rounds. |
| **Stop** | Work ends. Brainy reports the final state, including anything left broken or uncommitted. |
| **Change something** | New context, revised requirement, narrower scope → re-plan, counter resets to 0. |

Escalation **before** the cap is encouraged whenever it is already clear the loop will not
converge — round 3 is the last resort, not the intended trigger.

## Three hard rules

**1. No assumptions.** Every decision rests on either a *validated fact* (read the code, ran the
tests, reproduced the behaviour — and said how) or a *human decision*. When a call is hard,
ambiguous, or subjective, the team stops and asks the human.

**2. Brainy authors nothing.** Routing, checking and counting only. Judgement always goes to the
Architect. This is what makes the cheap-orchestrator split work instead of producing a second-rate
architect.

**3. Models are pinned.** Each agent always runs its assigned model. If a fallback happens for any
reason, it must be reported to the human — expected model, actual model, and why. No silent
substitution.

## Observability — session cost reporting

Brainy logs every orchestration event to the per-session SQL database and the runtime records
exact token and time data automatically. Together they give a full cost picture for any session.

### What is logged and where

| Store | Written by | Contents |
|---|---|---|
| `~/.copilot/session-store.db` | Runtime (automatic) | Token counts (`input`, `cache_read`, `cache_write`, `output`, `reasoning`), `duration_ms`, model, per API call |
| `~/.copilot/session-state/<id>/session.db` | Brainy (via `sql` tool) | `run_log` — workflow events: who was dispatched, to which phase, what round, what came back |

### The `run_log` table

Brainy inserts a row **before** every agent delegation (`action='dispatched'`) and **after** every
return (`action='returned'`), plus rows for mechanical check results, escalations, and halts.
Each row carries: `run_id`, `phase`, `round`, `agent`, `model`, `action`, `detail`, `ts`.

### Reading the report

```bash
python3 .github/agents/session_cost.py --list          # list recent sessions
python3 .github/agents/session_cost.py <session-id>    # full report for one session
```

The report shows:
- Token breakdown by model: input, cache read/write, output, reasoning
- Wall time per model and total
- Cache hit % (fraction of input served from cache — the main context-pressure signal)
- Orchestration timeline from the `run_log` (orchestrated sessions only)

Since each agent runs a distinct model, **model = agent** is unambiguous in the token table.

## Style

Brainy reports to the human in **simple language that stays technically precise**, and uses
[caveman mode](../instructions/caveman.instructions.md) when active. Relayed messages pass through
verbatim and are never caveman-ified. Code, commits, PRs, plans, and written documentation are
always in normal language.

## Usage

```bash
copilot --agent brainy-smurf     # orchestrated work — start here
/agent brainy-smurf              # inside a session
```

Start with Brainy for anything multi-step; he pulls in the others. For a small task, call the
specialist directly. See `AGENTS.md` in the repo root for project conventions all four agents
follow.
