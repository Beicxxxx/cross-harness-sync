# Latest Handoff

> Updated: 2026-09-22 08:52 (+10:00) by qoder-cli after the spec 10.D install
> landed and its review closed.
> Budget: ≤ 80 lines. Background and boundary statements live in
> `.ai/state/CURRENT.md` — link, never copy.

## 1. Done

- Wave 1b merged to `main` as PR #1 (`3a5f2a9`); suite on the merge commit is
  `480 passed, 5 skipped`.
- This protocol installed into its own repository (`python scripts/init_sync.py .`),
  under a writer lock held by `qoder-cli` for the duration.
- Governance registered: `protected_paths` = `scripts/*`, `templates/*`,
  `docs/evidence/*`; role-policy digest pinned; window set to the wave's own base
  `db091bdcea61daf73bb9cbcae446ef893490bd50`.
- Coverage walk over real history: 29 uncovered of 29 before the stage record,
  `[PASS] path coverage: 29 protected touches covered` after it, and 30 once this
  stage's own commit landed — every later commit that touches a protected path
  adds one, and only an accepted record naming it keeps the line green.
- Project's own suite registered as an `extra_checks` check; in-repo verifier now
  `== 25/25 checks passed ==`, rc 0, no `[SKIP]` line.
- Pre-commit review by a fresh separate-context subagent: 4 Important, all
  closed (index row, record filename convention, unfilled required files, the
  `.ai/**` wildcard grant).

## 2. Not done

- No tag, no GitHub Release, no version bump.
- Wave 1c (14 deferred minors, plus the three findings in
  `docs/evidence/wave1b-facts.md` §7) has not started and needs its own record.
- The four host-limits in `.ai/state/BLOCKERS.md` §1.3 remain unverified.

## 3. Evidence pointers

- `docs/evidence/wave1b-facts.md` §7 — measured rows for this stage, including
  the live lock record and the `--review-prompt` block layout on a real window.
- `.superpowers/sdd/2026-09-21-cross-harness-sync-v2.1-wave1b-governance-migration/evidence/dogfood-*.log`
  — raw verifier output, before and after the record. **Gitignored**: private
  reasoning, not evidence a clone can reach.
- `.ai/state/authorizations/2026-09-22-wave1b-dogfood.md` — the stage record.

## 4. Warnings

- `.ai/scripts/*.py` are the copies that actually govern and they are outside
  `protected_paths`. Byte-identical to `scripts/*.py` right now; nothing detects
  them drifting later. Do not read a green `sync_verify` as proof the installed
  verifier matches the source.
- The coverage walk unions editable lists across the whole window, so an
  accepted record keeps authorising after its stage closes.
- A `[PASS]` is omission-detection, not prevention, and the lock is advisory.

## 5. Next step

Publish this stage: `v2.1-dogfood-10d` (`ddcf5f9`, `b32c818`) is committed
locally with **no upstream** — `git push` dies in a non-interactive shell because
Git Credential Manager cannot prompt (`/dev/tty` absent), while the `gh` token is
still valid. `handoff/NEXT_PROMPT.md` carries both routes and the commands. Until
the push lands, the public repo has no `.ai/` and the §10.D figures are local
only. Then ask the user about tagging `v2.1.0`; if wave 1c is approved, open its
record first and fix `templates/AGENTS.md`'s `git add -A` line inside that stage.

## 6. Must-read list

- `.ai/state/CURRENT.md` §5 — the standing rules this stage wrote.
- `.ai/state/DECISIONS.md` — the two decisions this stage recorded, including why
  the dogfood cannot be described as retroactive process evidence.
- `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` §2 — the
  publishing red lines, binding on any text that leaves this repo.
