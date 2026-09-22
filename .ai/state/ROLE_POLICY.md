# Role policy — rev 1 (three-tier lightweight regime)

> Adopted: 2026-09-22 11:52:09 (+10:00), by `init_sync.py` (cross-harness-sync 2.1.0).
> This file is L1: read it when executing or reviewing a task, not at startup.

---

## 1. Three tiers

Classify the step first. **When two tiers could apply, take the higher one.**

| Tier | Applies to | Review required |
|---|---|---|
| **T1 — ordinary** | implementation, refactor, bug fix, docs, analysis with no frozen output | Executor runs the relevant tests once. **No LLM review.** |
| **T2 — protected** | anything touching a freeze, a hash pin, an authorization artifact, a fail-closed path, a security or access predicate, or a production path others depend on | **One reviewer, cross-family where the harness can reach one.** Checks diff, hashes, and targeted regressions. Does **not** re-run full suites the executor already ran. |
| **T3 — irreversible gate** | pre-registration, gate verdicts, one-shot opportunities, anything that cannot be undone by a revert | **One independent reviewer + the user's authorization.** Arbiter only if reviewer and executor genuinely conflict. |

### T1/T2 boundary — not a judgement call

A change is **T2, never T1**, if it touches any of:

- an authorization or gate predicate, including its boolean logic;
- a fail-closed default, or any path that decides whether something may run;
- a hash computation, comparison, or pinned-baseline list;
- a freeze manifest, attestation, or approval record;
- a test whose purpose is to protect one of the above.

This list exists because fail-open guard bugs present as "ordinary one-line
fixes" to anyone judging by diff size.

---

## 2. Roles actually instantiated

Day to day there are three: **executor**, **reviewer** (T2/T3 only), and **the
user as gate**. Planner and arbiter are not standing roles.

- **Executor / single active writer.** Exactly one at a time. Always.
- **Reviewer.** Required at T2 and T3. Must not have planned the step under
  review (R2). Take it from a different model **family** when the harness can
  reach one; where it cannot, a same-family reviewer with no shared context holds
  the role and the record says `same-family` out loud. What this regime can
  enforce is the description, not the split: a harness that can load one family
  cannot conjure a second, and a rule that ignored that would be obeyed by
  writing the word and meaning nothing.
  Read scope is hard: the authorization, the diff, and the test/verify output.
  Reading full history "for safety" is out of scope.
- **User.** Sole authority for T3 authorization and any irreversible action.
- **Arbiter.** Only when reviewer and executor genuinely disagree and cannot
  resolve it from the artifacts. Named ad hoc; must not have acted in either
  role on the disputed item.

**No routine reviewer-of-the-reviewer.** The mitigation for an uncalibrated
reviewer is calibration (§5) or the user's own read, not another LLM pass.

---

## 3. Hard rules

- **R1 — Single active writer.** One executor at a time, every tier. Enforced
  by convention plus the advisory lock: `checkpoint.py --lock --agent <name>`.
- **R2 — Reviewer ≠ author.** A model that wrote or planned a step may not
  review it. Its own verification is corroborating evidence, never the review.
- **R3 — Cross-family review preferred at T2/T3.** Different families when the
  harness can reach them; a same-family reviewer with no shared context when it
  cannot, with the downgrade recorded under R5 instead of described as the
  cross-family case. R3 asks for the best reviewer available, not for a second
  family to exist.
- **R4 — Red before green.** A regression test written to close a defect must be
  shown to **fail** against the unfixed code before the fix lands. Executor
  obligation; costs the reviewer nothing.
- **R5 — Record harness + model + effort without creating a gate.** Every `.ai/`
  entry naming an executor or reviewer records all three when known; unknown
  fields are `NOT_REPORTED`, never guessed, and never a reason to rerun a
  substantive review.
- **R6 — Metered spend is a user decision.** Propose, justify, wait.
- **R7 — One model, one function per task.** Planned ≠ reviewed ≠ arbitrated.

## 4. Effort and capability tier

Reviewers and T3 actors take the **top** effort setting; executors the middle.
Match the model class to the failure mode, not the task size:

| Failure mode | Model class | Effort |
|---|---|---|
| **Silent** — a wrong answer looks right (design, review, protocol drafting) | Frontier only | Top |
| **Loud** — tests, hashes or a fail-closed path will catch errors (mechanical edits under a diff-level spec) | Any competent model; cheap tiers fine | Middle |

## 5. Calibration

A model may hold a T2/T3 reviewer role uncalibrated, but record that fact in the
verdict. To calibrate: give it one already-solved task from
`.ai/handoff/archive/` with a known outcome, and compare. Log in `DECISIONS.md`.

## 6. What must never be pinned

**Frequently-changing state files are not pinning targets.** `CURRENT.md`,
`TASK.md`, `BLOCKERS.md` and `LATEST.md` must not appear in any authorization's
baseline or pin list. Pin only: frozen artifacts, production code an
authorization depends on, pre-registration text, approval records, and the
specific task file being executed.

## 7. Project boundaries that are not governance

- Research-project content stays out of this repository: the CJK font repertoire
  and benchmarking work is neither a deliverable here nor a test fixture, and only
  the user lifts this.
- No tag, no GitHub Release, no version bump unless the user asks in those words.
- `.superpowers/` is private reasoning: never force-add it, and never cite a
  figure that appears only there as evidence a reader can reach.
