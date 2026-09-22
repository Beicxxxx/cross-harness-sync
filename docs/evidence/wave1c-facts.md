# Wave 1c facts — measured on the tree this file describes

Base: `0bc4d7f` (main, after PR #2). Tree measured: the commits on
`v2.1-wave1c-governance-defects`. Every line below was run on that tree; a figure
carried forward from wave 1b would be a different tree's number, so the wave-1b
rows in `docs/evidence/wave1b-facts.md` are left exactly as they were and are not
restated here.

| # | fact | measured |
|---|---|---|
| W1 | the new lane against the **base** tree, before any fix | `8 failed, 1 passed`. The one pass is the CONTROL case (`test_c1_control_a_filled_in_install_adds_no_slot_failure`), green at base by design; it stops meaning anything if it ever goes red. Raw output: private on this host (`.superpowers/…/lane-1c-red-at-base.log`), so the PR body carries the same 9 lines inline — a reader of the clone cannot reach the file |
| W2 | fresh install into a throwaway git repo | `== 21/25 checks passed, 4 skipped ==`, rc 0. Wave 1b measured `20/24` on its own tree; the difference is exactly one check (`unfilled template slots`), which PASSes and adds **no** new skip, and the test that pins this count is the tripwire that proves it |
| W3 | the same repo after `--migrate` | `== 22/25 checks passed, 3 skipped ==`, rc 0 |
| W4 | this repository, after the stage | `== 26/26 checks passed ==`, rc 0, no `[SKIP]` line: `[PASS] unfilled template slots: 2 installer-owned files carry no slot`, `[PASS] path coverage: 8 protected touches covered`, `[PASS] role policy integrity: … digests to the pinned 1cabec53ef17e07382… (5833 bytes)` |
| W5 | the project's own suite | `489 passed, 5 skipped` (same 5 POSIX-only skips). Was `480 passed, 5 skipped` on wave 1b's tree; the 9 added cases are this lane |
| W6 | why `path coverage` fell from 33 to 8 | Not a regression: `scripts/*` and `templates/*` left `protected_paths`. The user's ruling was that a record in this repository's own runtime must not certify what gets published, and registering the release face there did exactly that. The release face is guarded by `tests/` and the review instead |
| W7 | the installer, given a repo whose local identity is `Ada Lovelace <ada@example.com>` | `AGENTS.md` line 46 became `` - Commit identity: `Ada Lovelace <ada@example.com>` `` and `ROLE_POLICY.md` line 3 became `> Adopted: 2026-09-22 11:45:35 (+10:00), by \`init_sync.py\` (cross-harness-sync 2.1.0).` — read from the repository's own config, not a constant, and not the machine's global one |
| W8 | the installer, given a repo with **no** identity set | exit 0, `[WARN] commit identity: none is set for this repository, so AGENTS.md says so rather than guessing one from the machine or the harness`, and the slot is replaced by that sentence rather than left blank |
| W9 | a GBK-encoded `AGENTS.md` | crashed the installer with `UnicodeDecodeError` in the first cut of this change — caught by the pre-existing `test_a_gbk_agents_md_does_not_crash_the_install`, not by anything I wrote. Now left untouched and named: `AGENTS.md: unreadable (UnicodeDecodeError), so its slots stay as found`. The predicate does not consult `exists()`, which on this host answers `False` for a file it merely cannot read |
| W10 | `--force` after the installer filled its own slots | The first cut broke the upgrade path: `KEEP (edited): …ROLE_POLICY.md - pass --clobber to overwrite`, i.e. every install would look hand-edited forever and `--force` would refresh nothing. Fixed by treating exactly the filled span as free (`installer_slot_lines()`), which is why W10 exists as a test at all |
| W11 | the two things this stage found in its own governance text | `.ai/state/ROLE_POLICY.md` shipped `Adopted: <YYYY-MM-DD HH:MM:SS> … by <who>` and an instruction-shaped section 7 while its digest was pinned — the pin proved nobody had looked, not that the document was real. And R3 required a different model family at T2/T3 while R5 said family is recorded and never gates, so the shipped policy contradicted itself |
| W12 | what the digest pin did when changed | One edit (`03f80ef0…` → `1cabec53…`) and `role policy integrity` stayed green; with the old value left in place it prints `[FAIL] … digests to … but config pins …: the governance document changed without the config edit that makes the change visible`. The mechanism works; it was pointed at a document nobody had finished |
