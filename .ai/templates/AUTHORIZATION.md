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

## Governance

The machine-readable twin of `## Roles`. `.ai/scripts/sync_verify.py` reads the
fenced block below and ignores the prose, so: one `key: value` per line, a
repeated key is fatal (audit data has no last-wins), and an unfilled angle
placeholder is fatal too — which is why this template carries the two sanctioned
sentinels (`n/a`, `NOT_REPORTED`) for you to replace instead of a bracketed hint.
`verdict:` is the line that decides whether this record counts as live; drop the
key and the record is undecided, which the verifier names as
`SKIP(no-verdict: …)` and never books as a pass.

```governance
tier: n/a
executor: NOT_REPORTED
reviewer: NOT_REPORTED
verdict: NOT_REPORTED
red_before_green: n/a
user_authorized: n/a
```

- `tier`: `T1`, `T2` or `T3`, per `.ai/state/ROLE_POLICY.md`.
- `executor` / `reviewer`: the harness and model that filled each role, plus the
  effort tier. Recorded, never gated on model family (rule R5) — the verifier
  checks identity, tier consistency, and omission.
- `red_before_green` / `user_authorized`: `true` or `false`, or `n/a` when the
  tier does not ask (both are expected at T3).
