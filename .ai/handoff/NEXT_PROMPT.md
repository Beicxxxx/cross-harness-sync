# Next Prompt — wave 1d is pushed and open as PR #5; only the owner's merge is left

You are the single active implementation executor. Read, in order:
`.ai/state/CURRENT.md` §2-3, `.ai/state/TASK.md`, `.ai/state/BLOCKERS.md` (binding
disclosures), `.ai/state/ROLE_POLICY.md` §1-3, and the two wave-1d records:
`.ai/state/authorizations/2026-09-22-wave1d.md` (runtime face) and
`docs/release-authorizations/2026-09-22-wave1d-product-changes.md` (release face).
Spec §2 (publishing red lines) is under `docs/superpowers/specs/`.

## There is nothing to do here until the owner decides

`v2.1-wave1d-deferred-queue` is pushed, tip `c9b56cf`-and-after, and open as PR #5
against `v2.1-wave1c-release-gate`, which is PR #4 against PR #3's branch, which is
PR #3 against `main`. Merging in that order, tagging, GitHub Release and any version
bump are the owner's, each asked in its own terms. Do not start a queue row without
him funding it, and do not "tidy" a document: the last 24 hours on this branch went
mostly into prose about finished code.

If you are asked to continue anyway:
1. `python .ai/scripts/checkpoint.py --lock --agent <your-name>` — the previous epoch
   was released at close-out, and re-acquiring overwrites
   `.ai/runtime/WRITER_LOCK.json`, which `docs/evidence/` cites as a live record.
2. Re-run `python .ai/scripts/sync_verify.py` before quoting anything from this file.

## Where it actually stands

On `v2.1-wave1d-deferred-queue`, tip `425b18b`, working tree clean, both wave-1d
records `verdict: accepted`, wave 1c's two `accepted` + `status: closed` (closed by
`status`, never by retracting a verdict — that is what keeps wave 1c's own coverage,
W19). Measured on that committed tree, this session ran:

- `== 28/28 checks passed ==`, no `FAILED:` line;
- `path coverage: 78 protected touches covered`;
- `release authorization: 78 release-face (commit, path) pairs covered by accepted
  record(s) (2 record(s) in docs/release-authorizations)`;
- `swarm boundary: 3 accepted of 3 records … 1 live, 2 closed`;
- suite, via its own `extra_checks` line: `538 passed, 5 skipped`.

`docs/evidence/wave1d-facts.md` V13 prints 75 for coverage, not 78: it was measured on
the pre-commit tree and says so, and the acceptance commit touched protected paths —
the mechanism working. Quote neither figure without re-running.

## Why this stage took so long, so you do not repeat it

The code was done long before it was written down. Hours went into prose about the
code — state files, handoffs, the facts table, the CHANGELOG — and into fixing claims
in that prose that were false (17 of them across two review passes: a `git show` that
exits 0 having written nothing treated as evidence; file counts of 23, 13 and 22 where
one command answers one number; "reviewed by a different model" where no different
model did it). Two habits caused most of it:

- **Measuring, then mutating, then quoting the old green.** Three separate times a
  total in a file was stale on arrival. Fix: after any commit or file copy, re-run
  before quoting anything; if you cannot re-run, do not quote.
- **Treating the description as the deliverable.** A row in a facts table is worth
  exactly one command's output. If a sentence needs a second sentence to stay true,
  the first sentence was the problem.

## What is left in the queue (not authorized to start)

`docs/evidence/wave1d-queue.md`: Q6 (`_load` duplicated across 15 test files under 5
signatures), Q8 (a diverged sidecar keeps running the old verifier), Q9 (a spent grant
never expires inside its window), Q10 (runtime bullets still accept `*`, and `*`
crosses `/`), Q11 (a typo'd `release_paths` is a silent SKIP), Q12 (`authorizations_dir`
resolves differently in two readers), Q14 (four ways the window guard does not fire),
Q15 (a `git show` that exits 0 and writes nothing still reads as a clean commit). Q13
is not work: eight ids (M-3, M-8..M-14) have no definition any reader can reach. Each
needs the user's funding before code.
## Rules that bind every step

- Two authorities. `scripts/`, `templates/`, `tests/`, `README.md`, `SKILL.md` and
  `reference.md` ship to other people: authorised in `docs/release-authorizations/`
  and never by a `.ai/state/authorizations/` record. `protected_paths` does not list
  them, so `path coverage` will not catch the mistake.
- A number may be published only from the tree it describes. `docs/evidence/` is the
  citable source; `.superpowers/` is gitignored, so a figure that lives only there is
  not evidence.
- Adding a check moves every pinned count; `tests/test_authorization_records.py` is the
  tripwire. Re-measure — never edit an expectation back to the old number.
- `check_governing_copy` decides "is this the skill's source checkout" from
  `scripts/init_sync.py` PLUS at least one shared installed name. Do not simplify it
  back to one filename test: that version held an innocent install permanently red, and
  the fix after it called a deleted source walk an install.
- Windows host: printed strings must stay ASCII (cp936 console); `exists()` answers
  False for files this host merely denies, so it cannot guard a read; `AGENTS.md` is
  not necessarily UTF-8; a `## Governance` value folded across lines makes §6 reject
  the whole block and the record can never be accepted.
- Line budgets are hard: `CURRENT.md` ≤ 60, `LATEST.md` ≤ 80, `NEXT_PROMPT.md` ≤ 100,
  `AGENTS.md` ≤ 65.

## Absolute stop boundary

No tag, no Release, no version bump, no merge of any PR, no push to `main`, no change
to the user's global git config — not credentials, not anything — without the user
asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history, never edit an
accepted record to satisfy a check it now refuses (close the stage, or open a new one).
Commits carry this repository's LOCAL `user.name`/`user.email` — the owner's GitHub
identity, not the school address and not the harness. No research-project content here.
