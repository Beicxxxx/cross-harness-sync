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
