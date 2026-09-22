# Latest Handoff

> Updated: 2026-09-23 02:05 (+10:00) by qoder-cli: wave 1d is reviewed and its
> records are still `pending`; wave 1c is accepted on PR #3 + stacked PR #4;
> nothing is merged.
> Budget: ≤ 80 lines. Background and boundaries live in `.ai/state/CURRENT.md`.

## 1. Done

- Wave 1c: accepted on `aecd536`, both faces. Not restated here —
  `docs/evidence/wave1c-facts.md` W1…W24 is the record of it.
- Wave 1d, on `v2.1-wave1d-deferred-queue`:
  - **The deferred queue is a tracked file.** `docs/evidence/wave1d-queue.md`
    replaced four artifacts' references to "14 minors: M-3, M-4, M-5, M-7..M-14" with
    fifteen rows, and Q13 says outright that eight of those ids resolve to nothing a
    reader can reach.
  - **Check 10, `governing copy`** — every `.ai/scripts/*.py` digests to its twin in
    `scripts/`, so the verifier reporting the invariant is the file this tree ships;
    `path coverage` asks only whether an edit was authorised. D-1..D-9.
  - **The runtime window got the release face's guard** — `_base_conflicts` shared,
    records read before the walk; Q14 lists the four ways it still does not fire.
  - **One anchor predicate** (`ai_common.is_full_sha`): `checkpoint`'s
    uppercase-tolerant copy is gone, which is how the review prompt came to diff from
    a window the verifier called unreadable. **Q4/Q5** gave two untested arms their
    cases; **Q7** wrote the `CHANGELOG.md` entries wave 1c owed and re-measured the
    published figures (`21/27`, `22/27`).
- **Two fresh-context review passes**, the second aimed at the first one's closures,
  because wave 1c accepted its own last batch without one (W24). Findings W1-W9 and
  X1-X8, each with its disposition, are in `docs/evidence/wave1d-facts.md`.

## 2. Not done

- Acceptance. Both wave-1d records read `verdict: pending`; the commit that accepts
  them also sets wave 1c to `status: closed` — two live accepted records in one
  window is what `swarm boundary` refuses.
- One of the two dispatched review passes died in the model service and was not
  repeated: recorded, not counted as a second review.
- Left open by decision, in the queue: Q6 (duplicated `_load`), Q8-Q12, Q14, Q15 (a
  `git show` that exits 0 writing nothing still reads as a clean commit).
- Merge, tag, Release, version bump — the user's, in those terms.

## 3. Evidence pointers

- `docs/evidence/wave1d-facts.md` — V1…V12 measured with their commits, and the two
  finding tables: the citable source for the stage.
- `docs/evidence/wave1d-queue.md` — what the deferred list actually is. Records:
  `.ai/state/authorizations/2026-09-22-wave1d.md` (runtime),
  `docs/release-authorizations/2026-09-22-wave1d-product-changes.md` (ships).

## 4. Warnings

- `python .ai/scripts/sync_verify.py` right now reports `path coverage` and
  `release authorization` FAILED — the mechanism, not a regression: a pending record
  certifies nothing. Re-run after acceptance.
- The guard binds a record's declared base. `status: closed`, an absent base, an
  emptied anchor, or a de-accepted `verdict` each stop it binding, and all four are
  self-reports: Q14, and `templates/AUTHORIZATION.md` says it to whoever writes the
  record. Do not describe that as enforcement.
- `governing copy` compares what runs to what is authored: not a stale copy from a
  hand-edited one, not whether every authored file was installed, and where
  `scripts/init_sync.py` is a borrowed name it says `SKIP(undecidable-source-walk)`.
- Adding a check moves every pinned count: `test_authorization_records.py` is the
  tripwire, and it pulled this stage. Re-measure; never carry a total from a handoff.
- `.ai/runtime/WRITER_LOCK.json` holds a released record that `docs/evidence/` cites;
  re-acquiring overwrites it. This stage holds the current epoch.

## 5. Next step

Accept and close in one commit (`verdict: accepted` on both wave-1d records, wave 1c
`status: closed`), re-run the verifier and the suite on that tree, then push
`v2.1-wave1d-deferred-queue` and open its PR on top of #3/#4. After that this branch
has no work left of its own: merging, tagging and releasing wait on the user.

## 6. Must-read list

- `docs/evidence/wave1d-queue.md` rows Q14, Q15 and Q13 — the guard's reach, the
  escape the new test does not close, and the ids that cannot be resolved.
- `docs/evidence/wave1c-facts.md` W24 — why a review of the closures is a different
  thing from a review of the code.
- `.ai/state/ROLE_POLICY.md` §1–3 — tiers and the R3/R5 ruling, before executing.
