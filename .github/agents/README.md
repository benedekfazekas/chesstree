# Smurf Agent Team

Three custom Copilot agents for `chesstree`. Lean setup: one planner, one builder, one reviewer.
Only the architect talks to the human.

## The team

| Agent | File | Role | Model |
|-------|------|------|-------|
| 🧠 **Brainy Smurf** | `brainy-smurf.agent.md` | Principal architect & orchestrator. Plans changes, does root-cause analysis, delegates, reviews everyone, reports to the human. | `claude-opus-5` |
| 🔨 **Handy Smurf** | `handy-smurf.agent.md` | Principal developer. Implements and tests what Brainy assigns. | `claude-sonnet-4.6` |
| 😠 **Grouchy Smurf** | `grouchy-smurf.agent.md` | Principal reviewer (tester + technical writer). Reviews plans *and* code changes. | `claude-opus-4.8` |

## Flow

```
human  ⇄  Brainy Smurf ──assign──▶ Handy Smurf ──report──▶ Brainy
                       ──assign──▶ Grouchy Smurf ──report──▶ Brainy
```

- Brainy is the **only** agent that talks to the human.
- Handy and Grouchy take assignments from Brainy and report back to Brainy.
- Brainy reviews all work — Handy's code *and* Grouchy's reviews — and is the final gate.
- Typical cycle: plan → Grouchy reviews plan → Handy implements → Grouchy reviews diff → Brainy final review → report to human.

## Unhappy path — the rework loops

Reviews finding problems is the **normal** case. Two loops handle it.

### Loop A — plan rework

```
Brainy plans ──▶ Grouchy reviews ──findings──▶ Brainy triages ──▶ Brainy revises ──▶ Grouchy re-reviews ──▶ …
```

Brainy triages **every** finding into one of three outcomes and says which:

| Outcome | Meaning |
|---------|---------|
| **Accept** | Finding is right → fix the plan. |
| **Reject** | Finding is wrong → send back the validated fact that disproves it. Evidence required, opinion not allowed. |
| **Escalate** | Facts cannot settle it → take it to the human with options and a recommendation. |

The revised plan states how each finding was resolved. Grouchy re-reviews the changed parts, checks
each finding by id, and hunts for new inconsistencies the revision introduced.

### Loop B — implementation rework

```
Handy implements ──▶ Grouchy reviews ──findings──▶ Brainy triages ──assignment──▶ Handy fixes ──▶ Grouchy re-reviews ──▶ …
```

- **Brainy never forwards a raw review to Handy.** Handy gets a filtered, decided list of work
  items — accepted findings with evidence, plus which findings were dismissed and why.
- Handy fixes the cause (not the symptom), adds a test that would have caught it, re-runs
  `python -m pytest tests/ -q`, and reports back per finding.
- Grouchy's re-review verifies each fix is really in the diff, checks the cause was addressed, and
  **hunts for regressions the fixes introduced**.

### Rules for both loops

- **Findings have stable ids** and carry across rounds with a status (open / fixed / rejected /
  escalated / withdrawn). Nothing silently disappears.
- **Disputes are settled by evidence or by the human** — never by whoever argues hardest.
- **Scope discipline.** Rework fixes the findings. New ideas become new work items.
- **If the plan itself was wrong**, Loop B stops and drops back to Loop A.
- **Brainy owns the round counter** and states the round number in every assignment ("round 2 of 3").
- **Grouchy approves when it is genuinely good.** Hard to please, not impossible to please.

### Fidelity rules (added after the Part 1 acquisition refactor)

These come from a real post-mortem: two of five review findings in one round were caused by
Brainy paraphrasing the approved plan into an assignment, not by faulty implementation.

- **The plan outranks the assignment.** Brainy cites the plan file and section instead of
  restating it, and copies any exact literal verbatim. Handy reads the plan section himself; if
  the assignment is thinner than or disagrees with the plan, the plan wins and he flags it.
  Grouchy reviews against the **plan**, and treats a plan/assignment divergence as a finding
  against the assignment.
- **Surgical edits only.** Handy edits the lines that change rather than regenerating whole files
  — whole-file rewrites were a large share of wall-clock time and buried real changes in noise.
- **Tests must be able to fail.** Brainy states what a test or fixture must detect; Handy builds
  fixtures that exercise those exact properties; Grouchy asks of every fixture whether it would
  still pass if the guarded behaviour regressed.
- **No duplicate reviews.** When Grouchy is queued, Brainy's pre-review is a cheap sanity check
  only; his real review is the final gate after Grouchy reports.
- **No model guessing.** Agents cannot introspect their own runtime model. Silence means "as
  pinned"; only an actually observed fallback gets reported.

### Round limit — hard stop at 3

Each loop is capped at **3 rounds** (a round = one review + one rework). At the end of round 3
without approval, **Brainy halts and goes to the human.** No agent may start round 4 on its own
authority.

Brainy presents: where we are, what is still open (findings by id + evidence), what has been tried,
and an honest **diagnosis of why the loop is not converging** — wrong plan, ambiguous requirement,
missing context, unvalidated assumption, oversized scope, or a dispute only the human can settle —
plus options with a recommendation.

The human then decides:

| Decision | Effect |
|----------|--------|
| **Carry on** | Human grants N extra rounds. Cap resets to N; same rules on exhaustion. Agents never grant themselves rounds. |
| **Stop** | Work ends. Brainy reports the final state, including anything left broken or uncommitted. |
| **Change something** | New context, revised requirement, different approach, narrower scope → re-plan from the new facts, round counter resets to 0. |

The halt exists so the human can rework the context, the prompt, or their own assumptions before
more effort is burned. Escalation **before** the cap is encouraged whenever it is already clear the
loop will not converge — round 3 is the last resort, not the intended trigger.

## Two hard rules

**1. No assumptions.** Every decision rests on either a *validated fact* (read the code, ran the
tests, reproduced the behaviour — and said how) or a *human decision*. When a call is hard,
ambiguous, or subjective, the team stops and asks the human via Brainy instead of guessing.

**2. Models are pinned.** Each agent always runs its assigned model. If a fallback happens for any
reason, it must be reported to the human — expected model, actual model, and why. No silent
substitution.

## Style

Brainy reports to the human in **simple language that stays technically precise**, and uses
[caveman mode](../instructions/caveman.instructions.md) when active. Code, commits, PRs, and
written documentation are always in normal language.

## Usage

```bash
copilot --agent brainy-smurf     # from the shell
/agent brainy-smurf              # inside a session
```

Start with Brainy; he pulls in the others. See `AGENTS.md` in the repo root for project conventions
all three agents follow.
