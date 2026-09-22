# Active Task

> Last updated: <YYYY-MM-DD HH:MM:SS> (<timezone>)
> Updated by: <harness / model> (<reason>).

## Standing state — do not rewrite

> <One-to-three lines of invariants that survive every task change,
> e.g. "Gate X closed as DO NOT ADVANCE; no Y is authorized.">

## The one active task

<Exactly one task. If two things seem active, one of them is wrong — fix this
file before doing either.>

## Role ownership

- **Executor:** <harness/model, or "inactive">.
- **Reviewer:** <harness/model — cross-family where reachable, else same-family
  and no shared context, per R3; "inactive" if done>.
- **User:** <what only the user may decide for this task>.

## Required work

1. <concrete deliverable>
2. <concrete deliverable>

## Explicitly not authorized

<Actions that look adjacent to the task but are out of scope. This list is what
stops scope creep across a handoff.>

## Completion condition

<The observable end state. Written so a different harness on a different machine
can verify it without asking anyone.>
