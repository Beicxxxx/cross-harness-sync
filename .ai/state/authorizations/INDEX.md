# Authorization Index (retrieval entry point — read THIS file to find the live stage record)

> Rule: one row per stage authorization, newest first. The `.md` file is the
> authority (scope, editable files, pins, roles, `## Governance` block); this
> table only says where to look, so a harness never has to read the directory to
> find the one live record. Same idiom as `DECISIONS_INDEX.md`.
> `.ai/scripts/sync_verify.py` scans this directory's `*.md` records and
> deliberately ignores this index — an index is not an authorization.

| Date | Stage | File | Tier | Verdict |
|---|---|---|---|---|
| 2026-09-22 | wave 1b dogfood — install the protocol into its own repo (spec 10.D) | 2026-09-22-wave1b-dogfood.md | T2 | accepted |
| 2026-09-22 | wave 1c — this repo's own runtime face; shipped `scripts/`/`templates/` are authorised outside this index | 2026-09-22-wave1c.md | T2 | accepted |
| 2026-09-22 | wave 1d — the deferred queue made public, plus the governing-copy and window-narrowing checks | 2026-09-22-wave1d.md | T2 | accepted |

- One file per stage, named `<YYYY-MM-DD>-<stage>.md`, from
  `.ai/templates/AUTHORIZATION.md`.
- `init_sync.py --migrate` creates this file with the rows above still
  unfilled: the records themselves are the user's, and a fabricated one would
  look exactly like a real audit source.
- Keep the table short — it is an L1 read, not an archive.
