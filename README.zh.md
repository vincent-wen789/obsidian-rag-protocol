# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

**ORP 是一个文件系统原生（filesystem-native）的协调协议——给两个或更多 AI agent 共享同一个 Obsidian vault 时用的。** 每个 agent 通过两条机制看到其他 agent 干了啥：确定性的 note 检索 + 从 append-only `wiki/log.md` 读取的 byte-cursor digest——**不用 embeddings、不用向量库、检索路径上不用 LLM**。

> **诚实版本：** 如果你只有一个 AI agent、想让它帮你 curate / 重写 / "优化" vault，**这不是你要的工具**。请用 [Karpathy 的 LLM Wiki 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 或 [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain)。ORP 真正发挥价值的场景：多个 agent 在同一个 vault 干活，它们之间的"静默漂移"是真实成本。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

### 核心差异

- **Coordination，不是 curation。** ORP 不重写你的笔记、不"优化" vault。内容是你的，ORP 只负责协调 agent 之间的状态
- **跨 agent 感知。** session 启动时自动注入 byte-cursor digest，告诉 Agent B 上次以来 Agent A 写了啥。无轮询、无 daemon
- **检索零 LLM 开销。** 确定性 alias 子串匹配，不用 embeddings 也不用 LLM re-ranking。30 篇笔记的索引约 15 KB

---

## 痛点

两个 AI agent 在同一个 Obsidian vault 干活。昨晚 Hermes 在 `hermes-knowledge/` 写了一份市场分析。今早 Claude Code 完全不知道——除非你再讲一遍。每次都这样。

**左手不知道右手在干啥。ORP 是它们之间的共享黑板。**

（如果你只用一个 agent，这不是你的问题——你需要的是 second-brain 工具，不是协调协议。见上方"诚实版本"。）

## 用上 ORP 之后

今早你新开一个 Claude Code session。在你打字之前，这段会自动注入到 agent 的 context：

```
[ORP digest · agent=cc · since byte 184459 · 2026-05-12T09:13:15+09:00]
🦅[hermes] 2026-05-12T07:30 · note · stock-pulse 调研完成并归档
🦅[hermes] 2026-05-12T07:31 · write · wukong 文学向精读报告 — 8/8 endings 全量覆盖
🦅[hermes] 2026-05-12T08:46 · write · Oppenheimer 文学精读 v1.3.0 — 7/7 endings
```

你一句话还没说，Claude Code 已经知道 Hermes 昨晚干了啥。不用重复解释，session 从共享 context 开始。

当你在对话里问"我们之前对 X 是怎么判断的"时，ORP 的 pull side 接管：agent 把你的关键词模糊匹配到你自己维护的 alias，只读对应的笔记。约 15 KB 的 JSON 索引。没 embeddings。东西不离开你电脑。

## ORP 跟 Karpathy 的 LLM Wiki / obsidian-second-brain 是什么关系

如果你已经看过 [Karpathy 的 LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 或 [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) 这个 Claude Code skill，这一节给你看。这三个项目都活在同一个邻里——markdown vault、Obsidian、AI agent——但解决的不是同一个问题。**ORP 不是用来替代它们的**，相反它可以放在它们底下一起跑。

### 一句话各自定位

- **Karpathy 的 LLM Wiki** 是一个*模式*：让 LLM 在 ingest 阶段读 source、构建并**维护**一组互相 link 的 markdown 页面。知识"编译一次然后保持新鲜"。**单 agent + 人协作**的设计。
- **obsidian-second-brain** 是这个模式的*实现 + 扩展*：31 条命令、4 个定时 background agent、新 source 进来 vault **自动重写老页面**、矛盾自动 reconcile。**单 Claude Code session + 人**。
- **ORP** 是一个*协议*——让两个 AI agent 在同一个 vault 下共享上下文：确定性的 alias 子串匹配做检索（不用 embeddings），byte-cursor session-start digest 做跨 agent 感知，append-only log 做协调通道。**Vault 内容是你的，ORP 不重写它**。

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
| **检索方式** | LLM 查询时跑 | LLM 查询 + 缓存页面 | **确定性 alias 子串匹配，不用 LLM、不用 embeddings** |
| **Embeddings / 向量库** | 没明说 | 可选（Perplexity sonar 做调研） | **完全不用——by design** |
| **awareness 原语** | 读整个 wiki / 页面图 | 自动加载 `## For future Claude` 前置段 | 每个 agent 各自的 byte-offset cursor 读 `log.md` |
| **实现规模** | 1500 字的 gist（idea 文档）| 31 条命令、4 个 cron agent、hook 系统 | 6 个 stdlib Python 文件（约 1900 行）|
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

- **不是 embedding 检索**。没向量、没 semantic search。问题没匹配到 alias，ORP 不会装作能找到。
- **不是自动打标签**。Alias 来自 frontmatter 或你手动维护的 map。indexer 永远不自己生成——这样检索结果稳定可预测。
- **不是跨设备同步**。vault 在你电脑上。文件层让 iCloud / Syncthing / Dropbox 自己处理，ORP 只在上面跑索引。
- **不是托管服务**。一个 Python 脚本（只用 stdlib）+ 一个 JSON 文件。没账号、没 API key。

## 你适合用吗

| 你的情况 | 适配 |
|---|---|
| 用 Obsidian 记笔记 | 适合 |
| 别的 markdown 笔记目录 | 适合——ORP 只扫 `.md`，"Obsidian" 部分指的是 frontmatter 习惯 |
| Vault 没怎么写 frontmatter | 适合，会用文件名做 fallback alias。给重要笔记加 `aliases:` 检索更准 |
| 1000+ 篇笔记 | 适合——`--cutoff-days` 控制工作集，已索引的旧笔记不会被掉出 |
| 用 Hermes | 直接适配，`install.sh` 一键搞定 |
| 用 Claude Code、Cursor、ChatGPT、自己写的 agent | 适合——ORP 就是个 JSON 文件。看 [其他 Agent](#其他-agent) |
| 需要真正的语义搜索（"和 X 有关的笔记"） | 不适合——用 LlamaIndex / Mem0 那类 |

## 其他 Agent

ORP 本质就是文件系统 + JSON。任何 agent 只要能：

1. 按需读文件（`read_file`、`cat`、MCP filesystem server 都行）
2. 加一条 system prompt 规则：*"遇到 non-trivial 问题，先读 `~/.hermes/vault-index.json`，把问题用 substring 匹配 `aliases`，命中后读对应 entry 的 `path`。"*

……就能用 ORP。重建用 cron / launchd / systemd timer / 任何调度方式。每个 agent 的具体接法看 [INSTALL.md → Agent Integration](INSTALL.md#agent-integration)。

## 常见疑问

**会把笔记发到外面吗？**
不会。indexer 只用 Python stdlib，没有任何网络调用。索引文件在你指定的路径下（默认 `~/.hermes/vault-index.json`）。

**我有 800 篇笔记，索引会爆吗？**
索引控制在 20KB 以内。`--cutoff-days 90`（默认）只索引最近 90 天动过的笔记。已经在索引里的旧笔记不会因为过了窗口就被踢出。

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

就这些。无需重训、无需 embedding 刷新、无需向量库维护。

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
- 每个 agent 有自己的 cursor 文件 `<vault>/.orp/cursor-<id>.json`，互不干扰。
- Agent 写 log 走 `orp_reader.py log --agent <id> --action <action> "msg"`——**不能手编辑** `wiki/log.md`，否则格式漂移、cursor 解析炸。
- 设计上是 best-effort：vault 不可用 / log 不存在 / cursor 损坏 → 静默 exit 0。digest 失败绝不能 block agent 启动。

没有 mtime 扫描、没有 daemon、没有轮询。append-only 的 log 就是唯一状态源。每个 agent 接入 = 一个 hook，详见 [INSTALL.md → Session-Start Digest](INSTALL.md#session-start-digest-v14)。

加第三个 agent（Codex / Cursor / 自己写的）：取个 id、写 log 走 `orp_reader.py log --agent <id>`、session 启动 hook 调 `digest --agent <id>`。vault 结构不用改。

**v1.5 更新：PostToolUse + Stop hook 自动 log。** v1.4 dogfood 数据显示——chat 型 agent（比如 Claude Code）经常忘记在写完 vault 文件后调 `orp_reader.py log`（一周内 41 个 vault 写入，CC 写 log 次数为 0；Hermes 同期写了 47 条）。Prompt 级别的 MUST 经验证不靠谱。v1.5 加了一个可选的双 hook 机制：PostToolUse stager 把每次 vault 编辑暂存到 per-session pending 文件，Stop hook flusher 在 agent 一回合结束时写 ONE 条汇总 log（action 用 `note`，message 前缀 `auto:`）。**一回合一条**，不是一编辑一条——保持信号紧凑。Hermes 这类长生命周期的后台 agent 已经能可靠记 log，不需要这套机制。详见 [INSTALL.md → Auto-log Hooks](INSTALL.md#auto-log-hooks-v15) 和 spec §5.6。

## 跟其他方案比

| 方案 | 跟 ORP 的取舍 |
|---|---|
| 把 vault 全塞 system prompt | 简单，但每次对话都吃满 context；没增量更新 |
| 向量库 / embedding（LlamaIndex / Mem0 / Letta） | 语义匹配能用，但重：要切块、有 embedding 成本、检索黑盒、随时间漂移 |
| Obsidian MCP server | 实时读 vault，但没有手维护的 alias 层——agent 每次得 grep 整个 vault |
| **ORP** | Alias 你说了算，检索确定性强，几乎零延迟。代价：只做 alias 关键词匹配，没语义匹配 |

ORP 适合"宁愿给重要笔记手写 5 个 alias，也不想调 embedding 切块策略"的场景。

## 状态

协议 v1.5。仓库里 6 个单文件 Python 工具（纯 stdlib，约 1900 行）+ 2 个参考 hook 脚本。

正在跑的：
- 一个 40 来篇笔记的 vault，单笔记本上跑了三个月
- 两个 agent（Hermes + Claude Code）共享同一 vault，分目录写
- 每日定时重建 + stale 自检兜底
- Session 启动 digest 接入两边 agent 的 startup hook（v1.4）
- Claude Code 端 PostToolUse + Stop 自动 log hooks（v1.5）——补上 v1.4 dogfood 发现的"CC 写 vault 但不 log"缺口

诚实交代：这是从一个用户的真实 setup 长出来的手搓规范。**目前还没有第三方采用方**——这套东西放在这里是"你或许也用得上"，不是"社区标准"。如果你接进来用，欢迎开 issue，spec 会跟着真实使用场景演进。

故意没做：
- 没语义 / 向量检索
- 没自动 alias 生成
- 没 GUI / dashboard
- 没 wiki 自动重写（见上方比较段落——append-only log 是相对于"vault 自我重写"的反向设计选择）

## 参考资料

- [`rebuild-vault-index.py`](rebuild-vault-index.py) ——单文件 indexer
- [`orp_reader.py`](orp_reader.py) ——单文件 reader（库 + CLI：`match` / `get` / `status` + v1.4 `log` / `digest`）
- [`orp_health.py`](orp_health.py) ——schema、新鲜度、alias 覆盖度校验
- [`orp_link_check.py`](orp_link_check.py) ——wikilink 完整性扫描（跳过 fenced code block）
- [`expand_aliases.py`](expand_aliases.py) ——批量补 frontmatter alias（alias 覆盖度薄时跑 · spec §3.4）
- [`convert_bare_to_fullpath.py`](convert_bare_to_fullpath.py) ——批量把 bare wikilink 转成全路径（spec §3.5）
- [`examples/orp-vault-stage.py`](examples/orp-vault-stage.py) + [`orp-vault-flush.py`](examples/orp-vault-flush.py) ——v1.5 PostToolUse + Stop hook 参考实现（spec §5.6）
- [`INSTALL.md`](INSTALL.md) ——安装、4 种触发方式、各 agent 接入、session-start digest 接线、auto-log hook 接线
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) ——完整协议 spec（v1.5）
- [`examples/`](examples/) ——3 篇真实笔记 + v1.5 hook 脚本

## License

MIT，见 [LICENSE](LICENSE)。

基于 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 和 [Obsidian](https://obsidian.md) 构建，任何能读文件的 agent 都能用。

维护者：[Vincent Wen](https://github.com/wjameswen888)。
