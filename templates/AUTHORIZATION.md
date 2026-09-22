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
`verdict:` decides whether this record is an authority at all; `status:` says
whether its stage is still a live writer. Drop `verdict` and the record is
undecided, which the verifier names as `SKIP(no-verdict: …)` and never books as
a pass.

```governance
tier: n/a
executor: NOT_REPORTED
reviewer: NOT_REPORTED
verdict: NOT_REPORTED
status: open
red_before_green: n/a
user_authorized: n/a
```

- `tier`: `T1`, `T2` or `T3`, per `.ai/state/ROLE_POLICY.md`.
- `executor` / `reviewer`: the harness and model that filled each role, plus the
  effort tier. Recorded, never gated on model family (rule R5) — the verifier
  checks identity, tier consistency, and omission.
- `status`: `open` while the stage is being worked, `closed` once it is
  finished; absent means `open`, and a value that is neither word is read as
  `open` (a typo must cost you a red line, not silence a check). The boundary and
  `checkpoint --review-prompt` consult it; the coverage walk deliberately does
  not, so closing a stage takes it out of the live-writer count WITHOUT
  retracting the `## Editable files` grants that cover its own commits. Rewriting
  `verdict` instead — a `retired` value — is the mistake this key exists to
  prevent. What `status` cannot do is protect you from a lie: a false `verdict`
  costs the writer its coverage, a false `closed` costs nothing, so the reviewer
  is the check here and the field only makes the claim visible.
- `window_start_commit`: the commit this stage began at, and the only thing that
  binds a window to the work it is supposed to govern. Required in a RELEASE record
  (one in the directory `release_authorizations_dir` points at); optional but
  binding in a runtime one. Both walks refuse an anchor
  (`release_window_start_commit`, `governance.window_start_commit`) that has left a
  LIVE accepted record's declared base behind, because a window is one config line
  and moving it forward drops the commits before it out of the range, where they
  read as neither covered nor uncovered — nothing looks at them. Closing a finished
  stage (`status: closed`, above) is how a project re-anchors for its next wave.
  Optional on the runtime side for one reason, and it is a reason about history:
  records written before that field existed carry no such line, an ACCEPTED record
  cannot be edited to add one, and refusing them all would be answered by rewriting
  approved records — worse than the hole. So a runtime stage that states no base is
  unguarded at its own back edge, and the honest response is to write the line in
  the next record, not to trust the walk to notice.
- `red_before_green` / `user_authorized`: `true` or `false`, or `n/a` when the
  tier does not ask (both are expected at T3).
