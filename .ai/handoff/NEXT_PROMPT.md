# Next Prompt — close wave 1c: one review, then the acceptance commit

You are the single active implementation executor. Read, in order:
`.ai/state/ROLE_POLICY.md` (tiers, R1–R7 — R3 and R5 were reconciled on
2026-09-22, so cross-family is a recorded preference, not a gate);
`.ai/state/CURRENT.md` §5 and `.ai/state/BLOCKERS.md`; both wave-1c records
(`.ai/state/authorizations/2026-09-22-wave1c.md` for the runtime face,
`docs/release-authorizations/2026-09-22-wave1c-product-changes.md` for what ships);
spec §2 (publishing red lines) under `docs/superpowers/specs/`. One rule shapes
every step below: `scripts/` and `templates/` ship to other people, so they are
authorised in `docs/release-authorizations/` and never by a record under
`.ai/state/authorizations/` — the user's ruling of 2026-09-22, and
`release authorization` enforces the separation now.

## Where the branch stands

On `v2.1-wave1c-release-gate` (stacked on `v2.1-wave1c-governance-defects`; PR #3
then PR #4), pushed through `81ff416`:

- Three release-face defects fixed red-first in
  `tests/test_lane_1c_governance.py`: `R3`/`R5` contradicted each other; the shipped
  instructions ordered `git add -A`; the installer's own slots were copied verbatim
  and unchecked. `init_sync.py` now resolves only what its repository can know
  (`git config --local`, never the machine's fallback) and drops ROLE_POLICY
  section 7 with a `WARN` rather than inventing it.
- `sync_verify.py` gained the `release authorization` gate
  (`tests/test_lane_1c_release_gate.py`), and `verdict` was split from `status`:
  closing a finished stage no longer retracts the coverage its own record grants
  (`tests/test_swarm_boundary.py`, W19). `.ai/state/ROLE_POLICY.md` is re-pinned.

Two claims in an earlier version of this file were withdrawn: the identity defect
was never in `templates/AGENTS.md` (it holds a placeholder; the sentence pointing at
repo history was this repository's own), and the "third template defect" logged from
it did not exist. Measurements, including the dry-run numbers below, are in
`docs/evidence/wave1c-facts.md` W1…W21.

## Step 1 — the review, before anything is accepted

One fresh-context pass on the release gate and the `verdict`/`status` split: a
subagent with no shared history, `git diff main...HEAD`, and mutants rather than
comments to attack. Re-run every finding before acting on it, and record what its
model family was — or that it could not be read (W14).

## Step 2 — the acceptance commit, exactly

ONE commit, because each verdict change alone is a self-approval:

- `verdict: pending` → `accepted` in both records;
- `status: closed` on `.ai/state/authorizations/2026-09-22-wave1b-dogfood.md` —
  NOT its `verdict`, which is what covers wave 1b's own protected touches;
- `python .ai/scripts/sync_verify.py` then exits 0 with no FAILED line. W19 holds
  the three dry-run measurements that define the gap (30 / 5 / 11 uncovered of 39).

Merging PR #3 and #4 stays the user's call, in those terms.
## Then: wave 1c's deferred list

- Wave-1b minors: M-3, M-4, M-5, M-7..M-14; `checkpoint._review_is_sha` accepting
  uppercase; `_migration_commit`'s post-commit listing check fixed without a test;
  15 duplicated `_load` helpers across 5 signatures.
- The governing-copy drift check: `.ai/scripts/*` is the copy that actually runs and
  nothing detects it diverging from `scripts/`, so a green `sync_verify` is not
  evidence the installed verifier matches the source — this stage copied by hand.
  Fix = a drift check, not un-protecting the copy.
- The stale-grant rule, and `*`-crosses-`/` for runtime records: `_section_bullets`
  reads a bullet's FIRST path as an `fnmatch` pattern, so enumerate one path per
  line (a packed bullet grants nothing to its second — W20) and never wildcard an
  accepted record. Also open: the coverage walk's share of the degenerate-window
  guard (W18), and a CHANGELOG entry per release document touched.

## Hazards that bit this stage

1. Adding a check moves every pinned count (`20/24`→`21/25` fresh,
   `21/24`→`22/25` migrated). `tests/test_authorization_records.py` is the
   tripwire; when it pulls, re-measure rather than editing the expectation.
2. Filling the installer's own slots makes the output differ from its template, so
   `is_template_shaped()` starts calling every install hand-edited and `--force`
   refreshes nothing. `installer_slot_lines()` is the fix — do not "simplify" it.
3. Two host traps: reading `AGENTS.md` as UTF-8 crashed on a GBK file, and `exists()`
   answers False for files this host merely denies, so it cannot guard that read;
   `.ai/runtime/WRITER_LOCK.json` holds a released record `docs/evidence/` cites as
   D5, and re-acquiring overwrites it (epoch 3, released at close-out).
4. A figure copied from a handoff describes the tree it was written on; W13 and W17
   are this stage's own instances, `13 uncovered of 13` among them.
5. A value folded across lines in a `## Governance` block makes §6 reject the whole
   block — `fields` comes back `{}` and the record can never be accepted (W17).

## Mandatory outcome

Every item fails against the tree it is meant to fix, with that output in the PR;
`sync_verify.py` and `python -m pytest tests/ -n 8 -o addopts= -q` are run after the
change and reported as they print, not as remembered.

## Absolute stop boundary

No tag, no Release, no version bump, no merge of any PR, no push to `main`, no
change to the user's global git config — not credentials, not anything — without
the user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history. No
research-project content in this repository. A figure that exists only under
`.superpowers/` is not evidence: a reader of the clone cannot reach it.
