# cross-harness-sync

A zero-infrastructure protocol that lets multiple AI coding harnesses
(Claude Code, Codex, Kimi, GLM, Cursor, …) and multiple machines pick up one
repo's work mid-task — plain markdown in `.ai/`, git as the transport, one
verify script as enforcement. No server, no database, no daemon.

**Design stance:** dumb files + git + one verify script beat a runtime service
when the goals are auditability (everything is a diffable markdown file in the
repo) and harness-agnosticism (every tool can read files and run git).

## 中文说明

**这是什么**：一套让多个 AI 编程 harness（Claude Code、Codex、Kimi、GLM、
Cursor……）和多台机器能在同一个仓库里无缝接力工作的协议。状态全部存为
`.ai/` 目录下的纯 markdown 文件，git 远程仓库即跨机器的共享内存，
一个 `sync_verify.py` 脚本负责强制执行规范。零基础设施：无服务器、
无数据库、无守护进程。

**解决什么问题**：agent A 在机器 1 上干到一半，agent B（可能是另一个 harness）
在机器 2 上接着干——不用口头交接，读三个文件就知道项目现在进行到哪、
为什么、下一步是什么。

**核心机制**：

- **L0/L1/L2 分层读取**——启动时只读 `CURRENT.md` / `TASK.md` / `BLOCKERS.md`
  三个文件（各有行数预算，由脚本强制）；历史归档只按索引检索单条，绝不全读。
- **单一写入者**——`checkpoint.py --lock` 获取带 TTL 的建议锁；锁文件随 git
  跨机器同步，冲突时明确报错而不是静默覆盖。
- **固定格式交接**——`LATEST.md` 六段模板（已完成/未完成/证据指针/警告/
  下一步/必读清单），≤ 80 行。
- **评审分层**——T1 普通改动免评审；T2 受保护路径（冻结、哈希、授权文件）
  需跨模型族评审；T3 不可逆闸门需独立评审 + 用户授权。
- **决策日志**——新决策 = 索引一行 + 正文 ≤ 15 行；推翻旧决策前只读归档中
  对应的那一条。

**快速上手**：

```bash
python scripts/init_sync.py /path/to/your/repo   # 脚手架安装（幂等）
# 填写模板中的 <占位符>，然后：
python .ai/scripts/sync_verify.py                 # 必须全绿
```

新 agent 接入项目时，把 `.ai/SYNC_PROMPT.md` 的内容作为它的第一条 prompt 即可。

详细机制、hooks 配置、配置项说明见 [reference.md](reference.md)。

## Install

```bash
python scripts/init_sync.py /path/to/your/repo
```

Then fill in every `<placeholder>` (remote URL, commit identity, project red
lines), declare project-specific checks in `.ai/sync_config.json`, and:

```bash
python .ai/scripts/sync_verify.py   # must be all green
git add -A && git commit && git push
```

`init_sync.py` is idempotent: existing files are skipped (`--force` to
overwrite); a pre-existing `AGENTS.md` gets a marker-delimited managed block
instead of being replaced.

## What you get

```
.ai/
├── SYNC_PROMPT.md        # first prompt for every newly joined agent
├── sync_config.json      # budgets, secrets, project-specific extra_checks
├── state/                # CURRENT.md / TASK.md / BLOCKERS.md  (L0 startup reads)
│                         # ROLE_POLICY.md · DECISIONS.md + DECISIONS_INDEX.md
├── handoff/              # LATEST.md (6-section template) · NEXT_PROMPT.md
├── protocol/VERSION
├── runtime/              # machine-local; WRITER_LOCK.json is tracked (travels via git)
└── scripts/              # checkpoint.py · sync_verify.py
```

## Daily protocol

- **Session start**: `git pull --ff-only`, read `.ai/state/CURRENT.md`,
  `TASK.md`, `BLOCKERS.md` — nothing else. Shortcut:
  `python .ai/scripts/checkpoint.py --prime` (project-overridable via
  `.ai/PRIME.md`).
- **Before writing state**: one active writer at a time —
  `checkpoint.py --lock --agent <harness-name>` (advisory TTL lock; conflicts
  are reported, never silently overridden).
- **Writing state**: CURRENT.md ≤ 60 lines, handoff ≤ 80 lines (fixed 6
  sections), one decision = one index line + ≤ 15 lines, one stage = one
  authorization file. Budgets are enforced by `sync_verify.py`, not discipline.
- **Close out**: `sync_verify.py` green → update state → `--unlock` →
  commit + push.

Review tiers (T1 ordinary / T2 protected / T3 irreversible gate), cross-family
review, red-before-green, and the single-writer rule live in
`.ai/state/ROLE_POLICY.md`. Details, hook snippets, and configuration:
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
