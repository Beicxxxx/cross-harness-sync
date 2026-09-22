# Next Prompt — <one-line description of the takeover>

You are the single active <role, e.g. implementation executor>. The user already
authorized this scope; do not request authorization again. Read, in order:

1. `.ai/state/ROLE_POLICY.md` (review tiers);
2. `<the stage authorization .md>`;
3. `<design/spec docs named by the authorization, one per line>`.

## Task

<What to do, in imperative form. Mention coexistence: preserve unrelated/user
edits, do not revert others' work.>

Owned files only:

- `<path>` (one per line — anything not listed is read-only for you)

## Current draft hashes — diagnostic only, not approved pins

- <file>: `<sha256>` (one per line, if mid-flight work exists)

## Known hazards to inspect first

1. <Specific trap: stale assertion, half-applied refactor, drifted pin.>

## Mandatory outcome

- <Verifiable condition the work must satisfy.>
- <Evidence to produce: test runs, hashes, red-before-green demonstration.>
- Stop for exactly one independent review when done. Cross-family where the harness
  can reach a second family; otherwise same-family with no shared context. Record
  which it was (R3, R5): the wording is the rule, the availability is not.

## Absolute stop boundary

<Actions that must not happen under any reading of this prompt: production runs,
frozen artifacts, publications, anything irreversible.>
