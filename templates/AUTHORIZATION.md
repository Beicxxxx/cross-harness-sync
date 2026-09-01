# Authorization — <stage name>

> Issued: <YYYY-MM-DD HH:MM:SS> (<timezone>) by the user.
> Recorded by: <harness/model>.
> Git commit at issuance: `<full commit hash>` — the repo state this
> authorization is scoped to.

## Scope

<Exactly what is authorized, in one paragraph. One stage = one file; no
JSON+MD+addendum triplets.>

## Editable files

- `<path>` (one per line — everything not listed is read-only in this stage)

## Pinned baselines

- `<path>`: SHA-256 `<hash>` (one per line)
- Only frozen artifacts, depended-on production code, pre-registration text,
  and approval records may be pinned. NEVER pin `CURRENT.md`, `TASK.md`,
  `BLOCKERS.md`, or `LATEST.md` — frequently-changing state files are not
  pinning targets.

## Roles

- Executor: <harness/model, effort tier>
- Reviewer: <harness/model — different model family from the executor>

## Completion condition

<Observable end state + required evidence (test runs, hashes, review verdict).>

## Stop boundary

<Actions that remain unauthorized even after successful completion.>
