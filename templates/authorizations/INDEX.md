# Authorization Index (retrieval entry point — read THIS file to find the live stage record)

> Rule: one row per stage authorization, newest first. The `.md` file is the
> authority (scope, editable files, pins, roles, `## Governance` block); this
> table only says where to look, so a harness never has to read the directory to
> find the one live record. Same idiom as `DECISIONS_INDEX.md`.
> `.ai/scripts/sync_verify.py` scans this directory's `*.md` records and
> deliberately ignores this index — an index is not an authorization.

| Date | Stage | File | Tier | Verdict |
|---|---|---|---|---|
| <YYYY-MM-DD> | <stage name> | <YYYY-MM-DD-stage.md> | <T1/T2/T3> | <accepted/pending/rejected> |

- One file per stage, named `<YYYY-MM-DD>-<stage>.md`, from
  `.ai/templates/AUTHORIZATION.md`.
- `init_sync.py --migrate` creates this file with the rows above still
  unfilled: the records themselves are the user's, and a fabricated one would
  look exactly like a real audit source.
- Keep the table short — it is an L1 read, not an archive.
