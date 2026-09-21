# cross-harness-sync

A zero-infrastructure protocol that lets multiple AI coding harnesses
(Claude Code, Codex, Kimi, GLM, Cursor, …) and multiple machines pick up one
repo's work mid-task — plain markdown in `.ai/`, git as the transport, one
verify script that mechanically checks what is mechanically checkable. No
server, no database, no daemon.

**What it proves:** omission, not fabrication. The verifier can show that a
required state file, a line budget, a secret-ignore rule or a tracked
placeholder is missing, and — since wave 1b — that a commit touching a declared
protected path is covered by no accepted authorization's editable-file list. It
cannot show that a review happened or that a recorded agent identity is honest:
a governance record naming executor and reviewer is verifiable against omission
only, and the review it describes is one **by a different model**, not a
mechanically checked one. Budgets, required files and the floor are enforced
(checked every run); the role policy, review tiers and writer discipline are
recorded, not enforced — the state-writing commands warn by name and continue at
exit 0 while another agent holds the advisory lock.

**Design stance:** dumb files + git + one verify script beat a runtime service
when the goals are auditability (everything is a diffable markdown file in the
repo) and harness-agnosticism (every tool can read files and run git).

## 中文说明

**这是什么**：一套让多个 AI 编程 harness（Claude Code、Codex、Kimi、GLM、
Cursor……）和多台机器能在同一个仓库里无缝接力工作的协议。状态全部存为
`.ai/` 目录下的纯 markdown 文件，git 远程仓库即跨机器的共享内存，
一个 `sync_verify.py` 脚本机械检查能被机械检查的部分（缺失与超预算），
检测的是**遗漏**而非**伪造**——它能证明某个必需文件或行数预算不达标，
无法证明某次评审真的发生过。零基础设施：无服务器、无数据库、无守护进程。

**解决什么问题**：agent A 在机器 1 上干到一半，agent B（可能是另一个 harness）
在机器 2 上接着干——不用口头交接，读三个文件就知道项目现在进行到哪、
为什么、下一步是什么。

**核心机制**：

- **L0/L1/L2 分层读取**——启动时只读 `CURRENT.md` / `TASK.md` / `BLOCKERS.md`
  三个文件（各有行数预算，由脚本强制）；历史归档只按索引检索单条，绝不全读。
- **单一写入者**——`checkpoint.py --lock` 获取带 TTL 的建议锁；锁文件随 git
  跨机器同步，被他人持有时 `--lock` 明确报错（退出码 1）而不是静默夺取。锁是
  协商性的：直接写状态的命令（`--handoff`、裸跑 `checkpoint.py`）在他人持锁时
  按名字 WARN 后继续，并以 0 退出。本项目面向顺序交接，不为并发多写入者仲裁，
  也不声称能阻止它们。
- **固定格式交接**——`LATEST.md` 六段模板（已完成/未完成/证据指针/警告/
  下一步/必读清单），≤ 80 行。
- **评审分层**——T1 普通改动免评审；T2 受保护路径（冻结、哈希、授权文件）
  需跨模型族评审；T3 不可逆闸门需独立评审 + 用户授权。这一层是**记录**，不是
  强制：没有任何脚本能证明一次评审发生过。
- **决策日志**——新决策 = 索引一行 + 正文 ≤ 15 行；推翻旧决策前只读归档中
  对应的那一条。

**快速上手**（安装目标必须是 git 仓库；从 v2.0 升级请先读下面 "Install" 段的
升级说明）：

```bash
python scripts/init_sync.py /path/to/your/repo   # 脚手架安装（幂等）
# 填写模板中的 <占位符>，然后：
python .ai/scripts/sync_verify.py                 # 无 FAILED 行即为通过；具名 [SKIP] 是允许的，静默不是
```

新 agent 接入项目时，把 `.ai/SYNC_PROMPT.md` 的内容作为它的第一条 prompt 即可。

详细机制、hooks 配置、配置项说明见 [reference.md](reference.md)。

## Install

The target must be a git repository (`git init` first) — git is the transport,
and outside a repo the secret checks cannot answer and report `[FAIL]`.

```bash
python scripts/init_sync.py /path/to/your/repo
```

Then fill in every `<placeholder>` (remote URL, commit identity, project red
lines), declare project-specific checks in `.ai/sync_config.json`, and:

```bash
python .ai/scripts/sync_verify.py   # no FAILED line; a named [SKIP] is legal, silence is not
git add -A && git commit && git push
```

A default install registers no project checks and declares no protected paths,
so its verifier ends `== 20/24 checks passed, 4 skipped ==` at exit 0 (measured
at `3546c08`); after `python scripts/init_sync.py <repo> --migrate` pins the
role policy and records the coverage window, the same install ends
`== 21/24 checks passed, 3 skipped ==`. Those `[SKIP]` lines are the correct
shape, not a failure to fix, and exit 0 is never sufficient on its own: read
the lines.

`init_sync.py` is idempotent: files it did not write are kept (`KEEP (edited)`),
`--force` refreshes the ones still untouched since their template, `--clobber`
overwrites those too, and a pre-existing `AGENTS.md` gets a marker-delimited
managed block instead of being replaced.

**Upgrading from v2.0.** Wave 1a broke existing installs — `checkpoint.py` and
`sync_verify.py` hard-exit `2` unless `.ai/scripts/ai_common.py` is present, and
v2.0 never installed that file. Wave 1b's `--migrate` is the upgrade:

```bash
python scripts/init_sync.py /path/to/your/repo --migrate
```

It sets the governance config keys, pins the SHA-256 of `ROLE_POLICY.md`,
records the window-start commit, installs the authorization index and template,
writes `.ai/protocol/MIGRATION.json` and a `MIGRATION.md` journal naming what a
revert cannot undo, and commits the result; re-running it verifies and writes
nothing. It refuses at exit 2, writing nothing, when git cannot be consulted or
when another agent holds the writer lock. `--scripts-only` remains the
refresh-only path (no `MIGRATION.json`, no window-start commit, no
reconciliation), and when `.ai/scripts/` is not in HEAD a migration preserves
the old scripts and emits `.new` sidecars plus a `WARN` instead of clobbering
them.

**Boundaries that are refusals, not bugs:** a linked git worktree, a `.ai`
reached through a symlink or Windows junction, an install below the repository
root, or a layout git cannot describe are all refused, on the main checkout and
on the second machine alike. The lock is a tracked file, so it only coordinates
writers who share one checkout's history — two worktrees are not two machines.

## What you get

```
.ai/
├── SYNC_PROMPT.md        # first prompt for every newly joined agent
├── sync_config.json      # budgets, secrets, project-specific extra_checks
├── state/                # CURRENT.md / TASK.md / BLOCKERS.md  (L0 startup reads)
│   │                     # ROLE_POLICY.md · DECISIONS.md + DECISIONS_INDEX.md
│   └── authorizations/   # one .md per stage (editable files + pins + a
│                         # governance block); INDEX.md is its index
├── handoff/              # LATEST.md (6-section template) · NEXT_PROMPT.md
├── protocol/             # VERSION (protocol version, not the skill version) +
│                         # MIGRATION.json/.md written by `--migrate`
├── runtime/              # machine-local; WRITER_LOCK.json is tracked (travels via git)
└── scripts/              # ai_common.py · checkpoint.py · sync_verify.py (three; they hard-exit 2 without the first)
```

## Daily protocol

- **Session start**: `git pull --ff-only`, read `.ai/state/CURRENT.md`,
  `TASK.md`, `BLOCKERS.md` — nothing else. Shortcut:
  `python .ai/scripts/checkpoint.py --prime` (if `.ai/PRIME.md` exists it
  replaces that output wholesale, lock line included).
- **Before writing state**: one active writer at a time —
  `checkpoint.py --lock --agent <harness-name>` (advisory TTL lock; a conflict
  exits 1 and names the holder). The lock is advisory: `--handoff` and the bare
  checkpoint WARN by name and continue at exit 0 while another agent holds it.
- **Writing state**: CURRENT.md ≤ 60 lines, handoff ≤ 80 lines (fixed 6
  sections), one decision = one index line + ≤ 15 lines, one stage = one
  authorization file. Line budgets, required files and secret-ignore rules are
  enforced by `sync_verify.py`, not discipline — an over-budget or missing file
  goes red on every run. That detects omission only: nothing here can prove a
  review happened or that a recorded identity is honest. A line is a weak proxy
  for tokens in CJK state files, which this protocol permits; real token
  accounting is a wave-2 measurement, not a wave-1 claim.
- **Close out**: `sync_verify.py` with no `FAILED:` line → update state →
  `--unlock --agent <name>` → commit + push.

Review tiers (T1 ordinary / T2 protected / T3 irreversible gate), cross-family
review, red-before-green, and the single-writer rule are **recorded** in
`.ai/state/ROLE_POLICY.md`, which the verifier requires and digests against the
SHA-256 pinned in `.ai/sync_config.json`; no shipped script gates on the tiers
themselves, and none gates on model family. What wave 1b adds is that the
*omission* side is verifiable: an uncovered protected-path commit, a forbidden
state-file pin, and more than one accepted authorization live at once each print
a named `[FAIL]`. Details, hook snippets, and configuration:
[reference.md](reference.md).

## Why not Beads / Memory Bank / agent-mail?

- **Cline Memory Bank** reads ALL memory files every session; this uses layered
  L0/L1/L2 budgets with a retrieval-only archive layer.
- **Beads** is a task/issue graph with a versioned DB; this tracks *narrative
  session state* (where the work stands and why) with zero dependencies.
- **mcp_agent_mail** coordinates concurrent agents via a running MCP server;
  this is for sequential handoff where the audit trail must live in git.

Mechanisms gratefully borrowed from all three (and from superpowers and
agent-handoff-skill) are documented in [reference.md](reference.md#provenance-of-borrowed-mechanisms).

## License

MIT — see [LICENSE](LICENSE).
