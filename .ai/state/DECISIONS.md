# Decisions — active pages

> Rule: a new decision = ONE line in `DECISIONS_INDEX.md` + ≤ 15 lines here.
> Budget: ≤ 20 active `##` entries; older entries move to
> `archive/DECISIONS_<yyyymm>_full.md` and their index rows flip to `archive`.
> Never restate background; link to it.

## 2026-09-22 08:42:06 (+10:00): the fix wave's own defects are closed by the controller, not by a second lane

Decided by: qoder-cli controller. The scoped re-review of `9937e0a` found that
commit red, and found one fail-open the fix itself had introduced; both were
fixed inline instead of dispatched as another wave.
Rationale: subagent-driven-development permits one fix dispatch and one
re-review for final findings, and both were spent. These are defects in the fix,
not new scope, and a red head cannot be pushed.
Scope: does not cover a finding of a different class — those go to the ledger and
to wave 1c — and does not exempt the controller's own edit from verification: it
was mutation-checked and every published number re-measured.

## 2026-09-22 08:42:06 (+10:00): spec 10.D is satisfied as certification of what landed, not as a retroactive process claim

Decided by: qoder-cli, after the user approved proceeding once the merge landed.
The install sets its governance window to wave 1b's base commit, so the coverage
walk judges the 29 real protected touches of this wave against one accepted
authorization record.
Rationale: wave 1b was executed before `.ai/` existed in this repository.
Pretending the record governed that process would be the unfalsifiable claim the
release wording forbids.
Scope: the record certifies scope and coverage of what shipped. It does not
attest that each earlier step ran under a lock, and `CHANGELOG.md` must keep
saying so.

## 2026-09-22 08:52 (+10:00): two shipped templates instruct behaviour the protocol forbids

Decided by: qoder-cli, found while filling the installed files in by hand during
the spec 10.D dogfood. `templates/AGENTS.md:48` tells every harness to run
`git add -A && git commit && git push`, and
`templates/handoff/NEXT_PROMPT.md:31` demands an "independent cross-family
review".
Rationale: the first contradicts the same file's "never commit secrets" two lines
below and this project's blanket-add prohibition; the second asks for something
rule R5 forbids gating on and §2 forbids claiming, so following the template
verbatim produces an overclaim.
Scope: logged for wave 1c, which owns `templates/`. This stage does not edit
templates (its record's stop boundary says so), and no public defect number is
invented for them — the spec's table ends at D26.

## 2026-09-22 08:52 (+10:00): two governance gaps are documented rather than closed by this stage

Decided by: qoder-cli on the review's findings. `.ai/scripts/*.py` is the copy
that actually governs and sits outside `protected_paths`, so it can drift from
`scripts/*.py` while the verifier reports green; and the coverage walk unions the
editable lists of every accepted record in the window, so a stage keeps
authorising after it closes.
Rationale: both are prospective today — the installed copies are byte-identical
by digest, and `.ai/` matches no protected pattern, so the stale grant is inert
for a verdict. The real closure is a drift check and a record-expiry rule, both
of which change shipped code and need their own red-first tests.
Scope: does NOT cover the general case of a hostile record; it is a documented
limitation, listed in `docs/evidence/wave1b-facts.md` §7 and in the handoff
hazards, and it is wave-1c work.

## 2026-09-22 12:05 (+10:00): Release face and runtime face are separate authorities

Decided by: the user, asked whether a wave-1c record under `.ai/state/` could
authorise edits to `templates/` and `scripts/`. It cannot: those ship to other
people, so they are authorised in `docs/release-authorizations/` and guarded by
`tests/`. `protected_paths` in this checkout dropped `scripts/*` and `templates/*`,
which is why `path coverage` reads 8 rather than 33 on this tree.
Rationale: this repository is both the protocol's user and the protocol's product.
Letting the first certify the second means any stage can approve its own release,
and the dogfood stops being evidence about the product.
Scope: this checkout only. It says nothing about what a downstream project should
register as protected, and the shipped default is still `protected_paths: []`.

## 2026-09-22 12:05 (+10:00): Cross-family review is a preference, downgrades recorded

Decided by: the user, resolving a contradiction inside the policy itself — R3 made
a different model family a requirement at T2/T3 while R5 said family is recorded
and never gates. Cross-family stays the default; a same-family reviewer with no
shared context is admitted, and the record must say `same-family` in those words.
Rationale: a harness that can load one family cannot conjure a second, so an
unconditional requirement is satisfied by writing the word and meaning nothing. The
part that can be enforced is the description, not the availability.
Scope: `ROLE_POLICY.md` (template and installed copy) plus the four documents that
restated the old requirement verbatim. Wave 1c's own review is recorded against it.

## 2026-09-22 13:40 (+10:00): The runtime walk keeps a known hole rather than be widened in passing

Decided by: qoder-cli, while wiring the release gate. The new `_degenerate_empty_window`
predicate refuses a window whose anchor IS the tip, since `<tip>..HEAD` covers nothing.
Applying it to `path coverage` too turned `test_a_protected_set_that_does_match_tracked_files_books_the_pass`
and the indeterminate-void test red: both anchor at HEAD deliberately and expect a PASS
for a quiet window.
Rationale: the release gate needed that arm to avoid reporting green over an empty range,
but changing a settled runtime behaviour is a different change, and a check's reach must
not widen as a side effect of the code sitting next to it. The hole is real and recorded
rather than fixed here.
Scope: `path coverage` only. The release walk is guarded.

## 2026-09-22 13:40 (+10:00): A wildcard bullet in a release record is newly reachable, not newly created

Decided by: qoder-cli on the gate's review. Editable bullets are read as `fnmatch`
patterns and `*` crosses `/`, so one `*` in a release authorisation would cover the whole
published surface for every future stage, because accepted records keep their force after
their stage closes.
Rationale: the parser and the union rule both predate this PR, so the gate did not invent
the mechanism — it pointed that mechanism at files other people install, which is why it
counts as newly reachable. This stage's own record enumerates one path per bullet for that
reason. Closing it needs a refusal or a bound in `sync_verify`, not a comment here.
Scope: both record kinds; `hazard 3` in `handoff/NEXT_PROMPT.md` predates this and stays.

## 2026-09-22 14:35 (+10:00): The release authority is itself under governance

Decided by: qoder-cli on the gate's second review, which found that
`docs/release-authorizations/*` was in neither `protected_paths` nor `release_paths`, so
changing one word — `pending` to `accepted` — flipped the release line from FAIL to PASS
with no other file in the commit. A record that certifies publications but is certified by
nothing is self-approval with extra steps.
Rationale: the file now sits in the runtime walk, so a verdict change must be covered by an
accepted runtime record enumerating it, which is the same `is_accepted()` door everything
else uses. What this actually buys is narrower than it first read: acceptedness is read from the
working tree, so no verdict flip needs prior approval, and the pair only makes the
second hop visible. The remaining real defence is that accepted release bullets are now
refused for using globs — before that, one appended `- \`*\`` line was covered by the
accepted runtime bullet and authorised every later shipped commit, which is what made my
earlier wording here an overclaim.
Scope: this checkout's `protected_paths`. The shipped default remains `[]`, and a project
that does not publish a face of its own registers neither list.

## 2026-09-22 18:22 (+10:00): A record's verdict and its stage's lifecycle are two fields

Decided by: qoder-cli on the acceptance dry-run, which could not close the stage.
`verdict: accepted` was doing double duty — authority over the commits a record names,
and membership in the live-writer count — so the only way to say "this stage is
finished" was to rewrite a verdict. Retiring wave 1b's that way uncovered six of its
own protected touches, and leaving it accepted kept `swarm boundary` red for any
repository that has run two stages, which is a permanent failure with no fix.
Rationale: `status: open|closed` carries liveness alone, read by `swarm boundary` and
by `checkpoint --review-prompt` and deliberately not by the coverage walk. An unknown
value reads as `open`, so a typo costs a red line rather than silencing a check. The
claim is reviewable, not forge-proof — the same envelope as a false `verdict`, which
spec 6.3 already says.
Scope: shipped in `templates/AUTHORIZATION.md`; a record predating the key has none
and means `open`.
