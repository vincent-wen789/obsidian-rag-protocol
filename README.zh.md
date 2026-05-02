# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

把你的 Obsidian 知识库变成 AI Agent 的长期记忆。无 embedding、无向量库，全本地。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

---

## 痛点

你问 AI Agent："我们之前对 X 是怎么判断的？"——它一脸懵。你又得从头讲一遍。每次都这样。

笔记其实你早写在 Obsidian 里了。Agent 看不到而已。

## 用上 ORP 之后

```
你: 我们之前对 Coinbase Japan 的判断是？

Agent: 根据 wiki/career/coinbase-japan-analysis.md
       (last updated 2026-04-11):
       • status: archived
       • 判断: 規制リスク過大、後発参入劣勢明顯
       • last action: 2026-04-11 写入分析笔记
       Source: alias "Coinbase" 命中。
```

Agent 读一个 ~15KB 的 JSON 索引，把你的问题 fuzzy match 到你自己定义的 alias，然后只读匹配到的那一篇笔记。无 embedding、无外部服务、数据不离开你机器。

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

## 跟其他方案比

| 方案 | 跟 ORP 的取舍 |
|---|---|
| 把 vault 全塞 system prompt | 简单，但每次对话都吃满 context；没增量更新 |
| 向量库 / embedding（LlamaIndex / Mem0 / Letta） | 语义匹配能用，但重：要切块、有 embedding 成本、检索黑盒、随时间漂移 |
| Obsidian MCP server | 实时读 vault，但没有手维护的 alias 层——agent 每次得 grep 整个 vault |
| **ORP** | Alias 你说了算，检索确定性强，几乎零延迟。代价：只做 alias 关键词匹配，没语义匹配 |

ORP 适合"宁愿给重要笔记手写 5 个 alias，也不想调 embedding 切块策略"的场景。

## 状态

协议 v1.1。reference indexer 是一个 Python 文件，~250 行，纯 stdlib。

正在跑的：
- 30 篇笔记的 vault，每日 cron 重建，已经跑三个月
- 两个 agent（Hermes + Claude Code）共享一个 vault，分目录写

故意没做（暂时）：
- 没 reader 参考实现——第三方 agent 目前自己写 alias matcher
- 没语义 / 向量检索
- 没自动 alias 生成
- 没 GUI / dashboard

## 参考资料

- [`rebuild-vault-index.py`](rebuild-vault-index.py) ——单文件 indexer，纯 stdlib
- [`INSTALL.md`](INSTALL.md) ——安装、cron / launchd 配置、各 agent 接入
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) ——完整协议 spec（v1.1）
- [`examples/`](examples/) ——示例 vault + 生成的索引

## License

MIT，见 [LICENSE](LICENSE)。

基于 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 和 [Obsidian](https://obsidian.md) 构建，任何能读文件的 agent 都能用。

维护者：[Vincent Wen](https://github.com/wjameswen888)。
