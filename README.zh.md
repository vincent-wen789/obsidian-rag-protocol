# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

**如果你有两个或更多 AI agent 在同一份笔记上干活，它们不知道彼此干了啥。ORP 就是让它们同步的共享笔记本。**

**你能拿到什么：**
- **每个 session 不用再重新解释一遍背景。** Agent 启动时就能看到其他 agent 上次以来写了什么。
- **找过去某篇笔记不用靠"我大概记得叫什么"。** 一个小关键词索引把多数"我之前在哪写过 X"问题搞定——不用调 embedding。可选的语义层兜底剩下的。
- **笔记是你的。** Agent 只在共享 log 追加事件，从来不重写你已有的笔记。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

### 这适合你吗

| 你的情况 | 适配？ |
|---|---|
| **两个或多个 AI agent 在同一个 Obsidian 式 vault 写东西** | ✅ ORP 就是为这个场景做的 |
| 一个 AI agent + 想让它 curate / 重写 / "优化" vault | ❌ 用 [Karpathy 的 LLM Wiki 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 或 [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) |
| 只有笔记，没 AI agent | ❌ 用 Obsidian 本体就够 |

ORP 是*协调协议*，不是 wiki 维护工具也不是第二大脑。如果你的 agent 之间没有"静默漂移"成本，这不是你要的工具。

---

## 痛点

两个 AI agent 在同一个 Obsidian vault 干活。昨晚 Hermes 在 `hermes-knowledge/` 写了一份市场分析。今早 Claude Code 完全不知道——除非你再讲一遍。每次都这样。

**左手不知道右手在干啥。ORP 是它们之间的共享黑板。**

（如果你只用一个 agent，这不是你的问题——你需要的是 second-brain 工具，不是协调协议。见上方"诚实版本"。）

## 用上 ORP 之后

**早晨 — session 启动。** 你打开 Claude Code。打字之前，这段自动注入到 agent 的 context：

```
[ORP digest · agent=cc · since byte 184459 · 2026-05-12T09:13:15+09:00]
🦅[hermes] 2026-05-12T07:30 · note · stock-pulse 调研完成并归档
🦅[hermes] 2026-05-12T07:31 · write · wukong 文学向精读报告 — 8/8 endings 全量覆盖
🦅[hermes] 2026-05-12T08:46 · write · Oppenheimer 文学精读 v1.3.0 — 7/7 endings
```

Claude Code 已经知道 Hermes 昨晚干了啥。不用你重新解释。Session 从共享 context 开始。

**中午 — 拉一个过去的决定。** 之后你问："我们上个月对东京那次出差是怎么定的？" Agent 查那个小关键词索引，一个 tool call 命中对应笔记，带着真实决定回答你。这次 query 不扫 vault，也不碰 embedding。

**整个闭环跑在一个很小的 JSON 索引上**——800 篇笔记的 vault 索引也能控在 20 KB 以内，因为只存 frontmatter + cutoff 过滤。全本地。除非你主动开 v1.6 的可选语义兜底，不然东西不离开你电脑。

📊 **看架构图**：[`assets/orp-architecture.png`](assets/orp-architecture.png) — 一张图三层（vault · ORP 协调 · agents）。
🎬 **看跑起来的样子**：[`assets/orp-demo.mp4`](assets/orp-demo.mp4) — 30 秒屏录。

## ORP 跟 Karpathy 的 LLM Wiki / obsidian-second-brain 是什么关系

如果你已经看过 [Karpathy 的 LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 或 [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) 这个 Claude Code skill，这一节给你看。这三个项目都活在同一个邻里——markdown vault、Obsidian、AI agent——但解决的不是同一个问题。**ORP 不是用来替代它们的**，相反它可以放在它们底下一起跑。

### 一句话各自定位

- **Karpathy 的 LLM Wiki** 是一个*模式*：让 LLM 在 ingest 阶段读 source、构建并**维护**一组互相 link 的 markdown 页面。知识"编译一次然后保持新鲜"。**单 agent + 人协作**的设计。
- **obsidian-second-brain** 是这个模式的*实现 + 扩展*：31 条命令、4 个定时 background agent、新 source 进来 vault **自动重写老页面**、矛盾自动 reconcile。**单 Claude Code session + 人**。
- **ORP** 是一个*协议*——让两个 AI agent 在同一个 vault 下共享上下文：以 alias 关键词索引为主路径做检索（主路径不碰 embedding；v1.6 有可选的语义兜底处理 miss 的情况），byte-cursor session-start digest 做跨 agent 感知，append-only log 做协调通道。**Vault 内容是你的，ORP 不重写它**。

### 在协议栈里各自的位置

```
┌──────────────────────────────────────────────┐
│ Application 层 — 知识合成                    │
│ Karpathy 的 LLM Wiki · obsidian-second-brain│
│ (ingest source、改写页面、lint、save)        │
├──────────────────────────────────────────────┤
│ Coordination 层 — 多 agent 状态同步          │
│ ORP                                          │
│ (digest / log / cursor / alias 匹配)         │
├──────────────────────────────────────────────┤
│ Storage 层 — markdown + git                  │
│ (Obsidian vault / frontmatter / wikilinks)   │
└──────────────────────────────────────────────┘
```

ORP 在 application 层下面。原则上 obsidian-second-brain 可以跑在 ORP 之上（每个定时 agent 用 `--agent <id>` 标识自己、写 log 走 `orp_reader.py log`）。Karpathy 的模式是单 agent，所以 coordination 层用不上——但如果你哪天真在 Karpathy 风格的 wiki 上跑两个 agent，ORP 就有活干了。

### 逐项对比

| 维度 | Karpathy 的 LLM Wiki | obsidian-second-brain | **ORP** |
|------|---------------------|----------------------|---------|
| **解决什么问题** | 知识累积（vs RAG 每次重新推导） | Vault 自我维护 | 两个 agent 共享一个 vault 时的状态同步 |
| **所在层** | Application（知识） | Application（知识） | Coordination（状态） |
| **agent 数量** | 1 + 人 | 1 + 人（CC） | 2（CC + Hermes），可扩展 |
| **会改动 vault 页面吗** | 会（ingest 时 LLM 改写） | 会（激进重写 + 矛盾 reconcile）| **不会**（append-only log，vault 内容不动）|
| **检索方式** | LLM 查询时跑 | LLM 查询 + 缓存页面 | **以 alias 关键词索引为主路径**（主路径不碰 LLM），v1.6 加可选的 embedding 兜底 |
| **Embeddings / 向量库** | 没明说 | 可选（Perplexity sonar 做调研） | **可选兜底**——alias-only 部署完整支持 |
| **awareness 原语** | 读整个 wiki / 页面图 | 自动加载 `## For future Claude` 前置段 | 每个 agent 各自的 byte-offset cursor 读 `log.md` |
| **实现规模** | 1500 字的 gist（idea 文档）| 31 条命令、4 个 cron agent、hook 系统 | 8 个单文件 Python 工具（约 3.6k 行 · stdlib + 可选 `openai`/`tiktoken` 给 v1.6 vec 层）|
| **多 agent 原生支持** | 否 | 否 | **是** |

### 啥时候用啥

- **想要一个 AI 帮你维护一个会持续累积的笔记 wiki**——用 Karpathy 的模式（嫌懒就用 obsidian-second-brain，已经做好了）
- **想让一个 AI 管理你整个第二大脑**——kanban、daily notes、矛盾自动 reconcile、各种定时 agent——用 obsidian-second-brain
- **你有两个或更多 AI agent 同时往一个 vault 写东西，需要它们知道彼此干了啥**——用 ORP（如果同时也想要知识合成，跟前两个搭着用）

### ORP 不是要做的

- **不是 wiki 维护工具**。ORP 不会总结 source、不会更新 entity 页、不会 reconcile 矛盾。它只是让 agent 之间能协调；他们往 vault 写啥是他们自己的事
- **不是知识累积器**。没有 LLM 驱动的页面改写。**ORP 的 append-only log 是"vault 自我重写"的反向设计选择**——为了紧凑而失去 audit trail 这种 trade，我们不做
- **不是 Claude Code skill**。ORP 是一个文件系统协议，任何 agent 都能 implement（CC 和 Hermes 是参考实现）；基于它的 skill 包是 application 层的工作

## 三分钟上手

```bash
git clone https://github.com/wjameswen888/obsidian-rag-protocol.git
cd obsidian-rag-protocol
bash hermes/install.sh
```

安装脚本会问你 vault 路径、配好每日 cron、把 indexer 接入 Hermes。一个终端，三分钟完事。

不用 Hermes？看下面 [其他 Agent](#其他-agent)——只要一条 system prompt 规则 + 一个 cron 就行。

## 它到底干啥（白话版）

- **给你的 vault 建一个小 JSON 索引**。一个文件，30 篇笔记 ~15KB。frontmatter（title、aliases、status、last action）抽出来排好供快速查找。
- **增量重建**。SHA256 内容哈希，没改的笔记不重抽。每天 cron 跑也无所谓。
- **Agent 只读索引，不扫 vault**。任何 non-trivial 提问的第一个 tool call 都是 `read_file(vault-index.json)`。Agent 永远不全量扫你的 vault。
- **Fuzzy alias 匹配**。关键词由你掌控（在 frontmatter 里或单独一个 JSON）。命中 → agent 读那一篇。没命中 → 提示用户。

## 工作原理

```
你的 vault                       indexer (cron 每日)
  ├── wiki/projects/             ┌─────────────────────┐
  ├── wiki/career/         ─────►│ rebuild-vault-      │──┐
  └── hermes-knowledge/          │ index.py            │  │ 写出
                                 │ (SHA256 + frontmatter│  │
                                 └─────────────────────┘  ▼
                                                    vault-index.json
                                                       (~15KB)
                                                          │
                                                          ▼
你的 agent (Hermes / Claude / 等等)
  收到 non-trivial 提问
       │
       ├──► read_file(vault-index.json)        # 1 次 tool call
       ├──► fuzzy 匹配关键词到 aliases
       ├──► 命中 → read_file(对应笔记)         # 1 次 tool call
       └──► 没命中 → 问用户 / 提议重建索引
```

完整协议看 [OBSIDIAN-RAG-PROTOCOL.md](OBSIDIAN-RAG-PROTOCOL.md)：schema、alias 解析、多 agent 协作、错误处理全在里面。

## 它**不**是什么

- **不是自动 curator**。ORP 不重写你的笔记、不生成摘要、不"优化"vault。只做协调。
- **Alias 优先，不是 embedding 优先**。多数查询走确定性关键词索引——主路径不碰 LLM。v1.6 加了*可选*的语义兜底处理没命中 alias 的情况；alias-only setup 完整支持，不需要 OpenAI key。
- **不是自动打标签**。Alias 来自 frontmatter 或你手动维护的 map。indexer 永远不自己生成——这样检索结果稳定可预测。
- **不是跨设备同步**。vault 在你电脑上。文件层让 iCloud / Syncthing / Dropbox 自己处理，ORP 只在上面跑索引。
- **不是托管服务**。所有脚本本地跑。不需要注册账号。可选的 v1.6 vec 层会用你自己的 OpenAI key 调 `text-embedding-3-small`。

## 你适合用吗

| 你的情况 | 适配 |
|---|---|
| **两个或多个 AI agent 在同一个 vault 写东西** | 适合——这是规范用例 |
| 一个 AI agent + 想让它 curate / 重写 vault | 不适合——用 [Karpathy 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 或 [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) |
| 用 Obsidian 记笔记 | 适合 |
| 别的 markdown 笔记目录 | 适合——ORP 只扫 `.md`，"Obsidian" 部分指的是 frontmatter 习惯 |
| Vault 没怎么写 frontmatter | 适合，会用文件名做 fallback alias。给重要笔记加 `aliases:` 检索更准 |
| 1000+ 篇笔记 | 适合——`--cutoff-days` 控制工作集，已索引的旧笔记不会被掉出 |
| 用 Hermes | 直接适配，`install.sh` 一键搞定 |
| 用 Claude Code、Cursor、ChatGPT、自己写的 agent | 适合——ORP 就是个 JSON 文件。看 [其他 Agent](#其他-agent) |
| 想用语义搜索做*主接口* | 用向量库吧。ORP 的 v1.6 vec 层只做兜底——主路径是 alias |

## 其他 Agent

ORP 本质就是文件系统 + JSON。任何 agent 只要能：

1. 按需读文件（`read_file`、`cat`、MCP filesystem server 都行）
2. 加一条 system prompt 规则：*"遇到 non-trivial 问题，先读 `~/.hermes/vault-index.json`，把问题用 substring 匹配 `aliases`，命中后读对应 entry 的 `path`。"*

……就能用 ORP。重建用 cron / launchd / systemd timer / 任何调度方式。每个 agent 的具体接法看 [INSTALL.md → Agent Integration](INSTALL.md#agent-integration)。

## 常见疑问

**会把笔记发到外面吗？**
不会。indexer 只用 Python stdlib，没有任何网络调用。索引文件在你指定的路径下（默认 `~/.hermes/vault-index.json`）。

**我有 800 篇笔记，索引会爆吗？**
不会。即使成熟 vault 索引也能控在 20KB 以内——因为 `--cutoff-days 90`（默认）只重新抽取最近 90 天动过的笔记，每条 entry 只存 frontmatter 字段而不是笔记正文。前面"30 篇笔记 ~15KB"的例子是新建小 vault；800 篇笔记的成熟 vault 大小也差不多，因为静默笔记不会被重抽。已经在索引里的旧笔记不会被踢出（不会静默掉条目）。

**我得给所有笔记都加 frontmatter 吗？**
不用。indexer 会用首段抽取 + 文件名 fallback。给经常被引用的笔记加 `aliases: [...]` 和 `summary_points: [...]` 会让检索更准。

**两篇笔记同名（不同目录）会咋样？**
自动用 scan-root 前缀消歧（`career-coinbase` vs `projects-coinbase`），并在 stderr 给 warning。

**索引文件坏了咋办？**
重命名为 `<name>.broken-<ts>` 保留下来，重建一份新的。原来手维护的 alias 都能从备份文件里捡回来。

**两个 agent 共用一个 vault 行吗？**
行——示例里 `wiki/` 和 `hermes-knowledge/` 就是给两个 agent 用的。各自写各自的目录，互相只读对方的。共享的 `log.md` 并发原子写规则在协议 §5.2。

## 日常维护

整个闭环：

1. **你在 Obsidian 写一篇笔记。** Frontmatter（`title` / `aliases` / `summary_points`）可加可不加——不写也能跑，回退到文件名做 alias。
2. **索引自动重建。** 从 `INSTALL.md` 选一种触发方式：系统 cron / agent 自带调度 / 耦合到别的 cron / 让 agent stale 时提示你。**最常见的组合**：每日定时 + agent 自检兜底。
3. **Recall 类提问 agent 自动读索引。** 你说"我们之前对 X 是怎么判断的？" → agent 读 `vault-index.json` → 模糊匹配 alias → 读那篇笔记 → 带着 context 回答。
4. **索引旧了 agent 主动提示。** 默认 ≥4 天 → "要不要重建？" → 你说"重建" → 它跑脚本。不会有静默漂移。
5. **定期跑健康检查。** `python3 orp_health.py` 检测 schema 漂移、孤儿路径、索引体积。CI 里跑或 vault 重整后跑。

就这些。无需重训、无需向量库维护。（如果开了 v1.6 语义兜底，`vault_vec.py update` 只 re-embed 变动的笔记——跟 alias indexer 同样的每日 cron 模式。）

## ORP 不只是只读

协议层面是索引，但实际部署里 vault 是双向的——agent 不只读笔记，触发条件下会**主动往 vault 里写**。生产中常见的几种模式：

| 触发条件 | 写什么 | 写到哪 |
|---|---|---|
| 每日岗位扫描 cron | 当日 Top N 匹配岗位 | `hermes-knowledge/job-search/daily-push-log.md` |
| 周度市场快照 cron | 一页关键信号回顾 | `hermes-knowledge/market/weekly-snapshot-{YYYY-Www}.md` |
| Cron 检测到异常（价格/链上/宏观） | 异动条目 | `hermes-knowledge/cron-knowledge/{category}/` |
| Agent 完成实质任务 | 决策 + 待办 | `wiki/career/` / `wiki/projects/` 等 |
| Agent 间协调 | 共享日志追加一条 | `wiki/log.md`（遵守 §5.2 原子追加规则） |

**这些不是协议契约的一部分**，是协议的*应用*。把 agent 该触发的场景、对应写入路径配好，第二大脑自己累积，不用你手粘贴。下次重建时索引自动收录新写入。

## Session 启动同步（v1.4+）

v1.3 之前，ORP 是**纯 pull**——只有用户提到 alias 命中的关键词，agent 才会读索引。这留了个洞：Hermes 凌晨 3 点写了一篇笔记、Claude Code 当时没在线，那 Claude Code 下次开 session **完全不知道这件事**——除非用户恰好问到它。

v1.4 把这个洞补上。每个 agent 在 session 启动时调一下 `orp_reader.py digest --agent <id>`，拿到自己上次看过之后、共享 log 里新增的内容：

```
[ORP digest · agent=cc · since byte 118402 · 2026-05-07T09:15:00+09:00]
🦅[hermes] 2026-05-07T03:14:22+09:00 · write · cron-knowledge/timeout-investigation.md — 4 个 aux 模型 timeout 排查
🦅[hermes] 2026-05-07T08:05:11+09:00 · note · ORP v1.3 alias 批量补全 60 → 58
🦅[hermes] 2026-05-07T08:30:00+09:00 · done · vault-health-check skill 长期化重写
```

push 那一面整个协议表面就这么大。实现：

- `wiki/log.md` 还是原来的协作通道（§5.2）。v1.4 给它的 entry 格式定了死：ISO-8601 时间戳 + 闭合的 action 词汇（`write`/`note`/`done`/`decision`），这样 byte offset cursor 能干净解析。
- 每个 agent 有自己的 cursor 文件 `<vault>/.orp/cursors/<id>.json`（旧的扁平路径 `cursor-<id>.json` 仍兼容读取），互不干扰。
- Agent 写 log 走 `orp_reader.py log --agent <id> --action <action> "msg"`——**不能手编辑** `wiki/log.md`，否则格式漂移、cursor 解析炸。
- 设计上是 best-effort：vault 不可用 / log 不存在 / cursor 损坏 → 静默 exit 0。digest 失败绝不能 block agent 启动。

没有 mtime 扫描、没有 daemon、没有轮询。append-only 的 log 就是唯一状态源。每个 agent 接入 = 一个 hook，详见 [INSTALL.md → Session-Start Digest](INSTALL.md#session-start-digest-v14)。

加第三个 agent（Codex / Cursor / 自己写的）：取个 id、写 log 走 `orp_reader.py log --agent <id>`、session 启动 hook 调 `digest --agent <id>`。vault 结构不用改。

**v1.5 更新：PostToolUse + Stop hook 自动 log。** v1.4 dogfood 数据显示——chat 型 agent（比如 Claude Code）经常忘记在写完 vault 文件后调 `orp_reader.py log`（一周内 41 个 vault 写入，CC 写 log 次数为 0；Hermes 同期写了 47 条）。Prompt 级别的 MUST 经验证不靠谱。v1.5 加了一个可选的双 hook 机制：PostToolUse stager 把每次 vault 编辑暂存到 per-session pending 文件，Stop hook flusher 在 agent 一回合结束时写 ONE 条汇总 log（action 用 `note`，message 前缀 `auto:`）。**一回合一条**，不是一编辑一条——保持信号紧凑。Hermes 这类长生命周期的后台 agent 已经能可靠记 log，不需要这套机制。详见 [INSTALL.md → Auto-log Hooks](INSTALL.md#auto-log-hooks-v15) 和 spec §5.6。

## 跟其他方案比

| 方案 | 跟 ORP 的取舍 |
|---|---|
| 把 vault 全塞 system prompt | 简单，但每次对话都吃满 context；没增量更新 |
| 纯向量库（LlamaIndex / mem0 / Letta / cognee / supermemory） | embedding-first 意味着检索黑盒、切块成本、随重新 embed 漂移。ORP 是 alias-first（确定性，作者 dogfood 多数 query 直接命中 alias 层），vec 只兜底——多数 query 根本不碰 embedding |
| **CodeGraph 等（tree-sitter 代码图 MCPs）** | 索引源代码 AST + 调用图，给单 coding agent 探索用。ORP 索引散文——笔记、决定、调研——给多 agent 协调用。可以在一台机器上各干各的（CodeGraph 管代码库，ORP 管 vault） |
| **Vendor memory（Claude memory / ChatGPT memory / Cursor memory）** | 锁定单一厂商；存储不透明；单 agent。ORP 是本地 markdown 文件、跨厂商、多 agent——你换工具笔记也不会消失 |
| Obsidian Smart Connections 插件 | 单用户、只查询、纯向量——跑在 Obsidian 里。ORP 是多 agent 读写 + 协调；vault 不依赖插件运行 |
| Obsidian MCP server | 实时读 vault，但没有手维护的 alias 层——agent 每次得 grep 整个 vault |
| **ORP** | Alias 为主路径的确定性检索（你掌控 alias 广度）+ 可选语义兜底 + 排序融合 + append-only 多 agent log。代价：不做 agent 驱动的 vault 重写——只协调，不 curate |

ORP 适合的场景：(a) 有 ≥2 个 agent 往同一个 vault 写东西，(b) 宁愿给重要笔记手写 5 个 alias 也不想调 embedding 切块策略，(c) 想让多数 query 走确定性、把语义当兜底而不是主入口。

## v1.5.1 → v1.7 新功能

用过老版本想看变化的（术语都用人话解释）：

**v1.5.1 — 跨 agent 协议原语**（2026-05）
- **Log 条目带身份元数据。** 每条 log 现在能挂上 `session=<id> trigger=<触发类型>`——一周后回头读共享 log，你能知道是 *哪个 agent 的哪个 session* 写的、被什么触发，不只是"哪个 agent"。Action 词汇收敛成 4 个固定值（`write` / `note` / `done` / `decision`），取代之前的自由文本。
- **Cursor 自检。** 每个 agent 用一个 byte 偏移量记自己上次读到 log 的哪儿，只增量读新东西。v1.5.1 在读之前先校验这个 cursor 没失效——查文件大小、最后 256 字节的内容哈希、最后修改时间。任何一个不对（log 被截断、从备份还原、等）→ agent 重新全读 + 在 digest 前加一条 ⚠ 警告，**不会静默回退**。
- **Note status 字段。** 每个 entity 现在有 `status` 字段，检索默认跳过 stale + archived。补上 v1.5 时"agent 生成的临时 stub 和人写的正式笔记没法区分"的歧义。

**v1.6 — 检索 + hygiene**（2026-05）
- **可选语义兜底。** 当你的提问跟自己写的 alias 偏太远（你想问"AI 复利"但 alias 是"知识图谱"），OpenAI embedding 层兜底救一下这次查询。新 vault 全量 embed 约 $0.023；每次查询约 $0.000001。**始终是可选**——alias-only setup 完全不受影响。
- **两路检索的排序融合。** 两层都开时用 [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)（2009 年的学术成果，现在是搜索引擎标准做法）把 alias + vec 的结果合一起。同一篇笔记两路都命中自然往前排，不用人为调相似度阈值。
- **反向链接（Backlinks）。** `vault_lookup.py backlinks <某篇笔记>` 列出 vault 里所有 wikilink 到它的笔记——同时扫 `wiki/` 和 `hermes-knowledge/` 两个命名空间。不存 index，每次扫 vault 现算（800 篇 ~0.1 秒）。
- **Embedding 模型版本管理。** 小的 `vault-vec.about.json` sidecar 记录索引是哪个 embedding model 建的。如果维度变了（换了一个完全不同的模型）索引拒绝加载（fail-closed——不同维度的 embedding 空间不能混）。如果只是名字变了（同维度），warn 一下继续跑。
- **过期 + 重复报告。** 周度 observational 扫描，输出到 `.orp/reports/stale-dedup-<date>.md`。按年龄和小写标题重合度标 candidate。**ORP 永远不自动改 vault**，你看完 report 自己决定哪些合并、哪些保留。

**v1.7 — 运维进协议本体**（2026-06）
- **每一个索引都得保持新鲜，不只是主索引。** 踩坑学来的：可选的语义索引悄悄落后 vault ~11 天，而主关键词索引一直是最新的。什么都没报错——搜索照样返回看着像样的答案——所以这个漂移一直没被发现，直到真去量了才暴露。v1.7 把"保持索引新鲜"立成一条明确义务、覆盖你跑的*所有*层，并要求新鲜度检查得有牙：某一层落后时它真的*失败*（非零退出），而不是一个等人去瞄一眼的数字。协议规定*什么*必须保持新鲜、*怎么检查*；*什么时候*刷新（cron / launchd / CI / agent 自带定时器）由你定。
- **第一个真实的第三 agent（N=3）。** 我们真把 [Codex](https://openai.com/index/openai-codex/) 接成了第三个读写同一 vault 的 agent——而且它直接就工作了。没有 leader 选举、没有 quorum：per-agent cursor + 分目录写本来就 cover 了这个规模下的 N 个 agent。唯一的坑，现在写进文档给采用方：复制别的 agent 的 hook 时，把 `--agent <id>` *每一处*都改掉，否则新 agent 会悄悄推进*另一个* agent 的读取位置，两边都开始漏读条目。

**一个用户 5 天 dogfood 的遥测**（32 次查询 · 2 个 agent · ~800 篇笔记）：**alias 命中 94% · vec 命中 100% · 全 miss 0 · 写冲突 0**。这是单 vault dogfood 数据，**不是通用 benchmark**——但能确认 alias 是主路径、vec 是少数情况下的兜底，**不是反过来**。

## 状态

协议目前在 v1.8.x。仓库里 **8 个单文件 Python 工具**（约 3.6k 行 · stdlib + v1.6 vec 层用的可选 `openai` + `tiktoken`）+ 2 个参考 hook 脚本。

正在跑的：
- 一个约 800 篇笔记的 vault，单笔记本上跑了 6 个月
- 两个有命名空间的 agent（Hermes + Claude Code）共享同一 vault、分目录写，外加 Codex 作为只读+log 的第三个 agent（v1.7）
- 每日定时重建 + stale 自检兜底
- Session 启动 digest 接入两边 agent 的 startup hook（v1.4）· 身份元数据 + 3 字段 cursor 自检（v1.5.1）
- Claude Code 端 PostToolUse + Stop 自动 log hooks（v1.5）——补上 v1.4 dogfood 发现的"CC 写 vault 但不 log"缺口
- `status` 字段回填覆盖 217 条 entity（v1.5.1）—— 216 captured + 1 verified
- 两层检索（alias + 可选 vec + 排序融合）在 CC 侧部署（v1.6）—— 5 天 dogfood：alias 命中 94% · vec 命中 100% · 全 miss 0（caveat：32 次查询、N=2 agent、不是通用 benchmark）
- Backlinks 查询 · embedding 模型版本管理 · 过期/重复报告 scaffold（v1.6，observational）
- 跨所有层的索引新鲜度义务 + 多层 staleness 检查门（v1.7）—— 起因是一个可选索引在生产里静默漂移了 ~11 天
- 第三个 agent（Codex）跟 Hermes、CC 一起读 + log（v1.7）—— N=3 不需要 quorum/leader；hook 复制改 `--agent` id 的坑写在 §5.5

诚实交代：这是从一个用户的真实 setup 长出来的手搓规范。**目前还没有第三方采用方**——这套东西放在这里是"你或许也用得上"，不是"社区标准"。如果你接进来用，欢迎开 issue，spec 会跟着真实使用场景演进。

故意没做：
- 没自动 alias 生成—— "alias 覆盖薄"留作人工 curate 的信号
- 没 GUI / dashboard
- 没 agent 驱动的 vault 重写（append-only log 是相对于"vault 自我重写"的反向设计选择）
- 没 N≥3 的 quorum / leader 协议——v1.7 也证实了不需要：第三个 agent（Codex）已经在生产里跑、不靠这些，因为 per-agent cursor + 分目录写本来就 cover 了这个规模下的 N 个 agent。只有当 agent 数量大到 symmetric-broadcast 刷屏变成真成本时才需要重新考虑
- 没自动 dedup 清理——v1.6 报告只标 candidate，是否合并由你定

## 参考资料

- [`rebuild-vault-index.py`](rebuild-vault-index.py) ——单文件 indexer
- [`orp_reader.py`](orp_reader.py) ——单文件 reader（库 + CLI：`match` / `get` / `status` + v1.4 `log` / `digest` + v1.5.1 身份元数据强制 + v1.6 `stale-dedup-report`）
- [`vault_vec.py`](vault_vec.py) —— **v1.6** 可选语义层（OpenAI embedding；`index` / `update` / `search` / `status`；带 embedding 模型版本管理 sidecar）
- [`vault_lookup.py`](vault_lookup.py) —— **v1.6** 统一检索 orchestrator（alias + vec + 排序融合 + gap log + `backlinks` 查询 + 周度 `review`）
- [`orp_health.py`](orp_health.py) ——schema、新鲜度、alias 覆盖度校验
- [`orp_link_check.py`](orp_link_check.py) ——wikilink 完整性扫描（跳过 fenced code block）
- [`expand_aliases.py`](expand_aliases.py) ——批量补 frontmatter alias（alias 覆盖度薄时跑 · spec §3.4）
- [`convert_bare_to_fullpath.py`](convert_bare_to_fullpath.py) ——批量把 bare wikilink 转成全路径（spec §3.5）
- [`examples/orp-vault-stage.py`](examples/orp-vault-stage.py) + [`orp-vault-flush.py`](examples/orp-vault-flush.py) ——v1.5 PostToolUse + Stop hook 参考实现（spec §5.6）
- [`INSTALL.md`](INSTALL.md) ——安装、4 种触发方式、各 agent 接入、session-start digest 接线、auto-log hook 接线
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) ——完整协议 spec（v1.8.x）
- [`examples/`](examples/) ——3 篇真实笔记 + v1.5 hook 脚本

## License

MIT，见 [LICENSE](LICENSE)。

基于 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 和 [Obsidian](https://obsidian.md) 构建，任何能读文件的 agent 都能用。

维护者：[Vincent Wen](https://github.com/wjameswen888)。
