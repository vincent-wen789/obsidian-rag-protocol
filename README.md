# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

**An open protocol for giving AI agents long-term memory from your Obsidian vault.**

> "The community was talking about 'personal knowledge base as agent identity.' I was already on v3.4."
> — Vincent Wen, creator

---

## What This Is

ORP defines how an AI agent (Hermes, Claude Code, or any agent framework) can read, index, and stay synchronized with an Obsidian vault — treating your personal notes as the agent's persistent knowledge layer.

It's not a plugin. It's not a one-off script. It's a **protocol spec** with a reference implementation that you can drop into any agent that has filesystem access.

## Why This Exists

My name is Vincent Wen. I'm a Crypto/Web3 marketing professional — not a software engineer. But I use AI agents heavily for research, strategy, and personal knowledge management.

In late 2025, I hit a wall: my AI agent (Hermes) would forget everything between sessions. Every time I asked "what did we decide about X," it had no idea. I needed my Obsidian vault — where I keep years of notes, research, and decisions — to feed into every agent conversation automatically.

Most people were solving this with huge system prompts or manual file pasting. I wanted something better:

- **Lazy context injection** — agent reads a ~15KB index on demand, not the whole vault. Only matched files get loaded.
- **Incremental indexing** that survives macOS iCloud sync (mtime is unreliable)
- **Bidirectional protocol** — two agents (Hermes + Claude Code) reading from the same vault with clearly separated directories
- **Human-readable index** that's also machine-queryable

Three months and four major iterations later, I had a system running in production — handling 30+ vault entries, automatically rebuilding daily, and injecting context into every agent conversation.

The community just started exploring "personal knowledge base as agent identity" with tools like `personal-api-skill`. This protocol is the next level — a spec you can adopt, extend, and build on.

## Protocol Overview

### Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      OBSIDIAN VAULT                         │
│                                                             │
│  wiki/                  hermes-knowledge/                    │
│  ├── projects/          ├── job-search/                     │
│  ├── career/            ├── engineering/                    │
│  └── log.md  ◄────────►└── cron-knowledge/                │
│        ↑ collaboration channel         ↑                    │
└────────┼───────────────────────────────┼────────────────────┘
         │  .md files                    │
         ▼                               │
 ┌───────────────────┐                   │
 │  rebuild-vault-   │   SHA256 hash &   │
 │  index.py         │   frontmatter     │
 │  (cron: daily)    │   extraction      │
 └────────┬──────────┘                   │
          │ outputs                      │
          ▼                               │
 ┌────────────────────────────────────────┼──────────────────┐
 │           vault-index.json  (~15KB)                      │
 │                                                          │
 │  { entries: {                                            │
 │      "project-alpha": {                                  │
 │        path, title, summary,                             │
 │        aliases, _content_hash, ...                       │
 │      }                                                   │
 │  }}                                                      │
 │                                                          │
 │  ★ One tool call = full context awareness                │
 │  ★ Zero prompt tokens for indexing                      │
 └────────┬────────────────┬────────────────┬────────────────┘
          │                │                │
          ▼                ▼                ▼
 ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
 │ Hermes      │  │ Claude Code  │  │ Any Agent    │
 │ Agent       │  │              │  │ (adopt ORP)  │
 │             │  │              │  │              │
 │ writes to:  │  │ writes to:   │  │   ORP spec   │
 │ hermes-     │  │ wiki/        │  │   = open     │
 │ knowledge/  │  │              │  │   protocol   │
 │             │  │              │  │              │
 │ reads from: │  │ reads from:  │  │              │
 │ wiki/       │  │ hermes-      │  │              │
 │             │  │ knowledge/   │  │              │
 └─────────────┘  └──────────────┘  └──────────────┘

  ┌──────────────────────────────────────────────────────┐
  │  AUTO CONTEXT INJECTION FLOW                         │
  │                                                      │
  │  User asks ──► Agent classifies query ──► non-trivial│
  │       │                                    │         │
  │       │                              trivial│         │
  │       │                                    ▼         │
  │       │                           read vault-index   │
  │       │                           .json (1st call)  │
  │       │                                    │         │
  │       │                          fuzzy match aliases │
  │       │                              │      │        │
  │       │                           HIT ─┘   MISS ─┐   │
  │       │                              │           │   │
  │       │                    read matched   check staleness│
  │       │                    vault file(s)  (>4d? rebuild)│
  │       │                              │           │   │
  │       │                              ▼           ▼   │
  │       ◄──────── answered with context ──────────────  │
  └──────────────────────────────────────────────────────┘
```

### Core Design Decisions

| Decision | Rationale |
|----------|-----------|
| **SHA256 hashing, not mtime** | macOS iCloud sync mutates file timestamps; content hashing is deterministic |
| **Aliases resolved by priority** | Frontmatter → Hand-curated map → Previous run → Fallback. Never auto-generated |
| **Path-based exclusion, not frontmatter-based** | Frontmatter can be forgotten; directory patterns are deterministic |
| **Incremental by default** | Same hash = skip extraction. Saves CPU and preserves human edits on aliases |
| **Frontmatter-driven summaries** | `summary_points` + `last_action` from YAML frontmatter, plain-text fallback |
| **JSON index, not LLM reasoning** | `read_file(vault-index.json)` is one tool call, zero prompt tokens |

### Auto Context Injection (v3.4)

When the agent detects a non-trivial question (contains "why", "how", "analyze", "research", etc.), it:
1. Reads `vault-index.json` (first tool call — mandatory by protocol)
2. Fuzzy-matches user keywords against `aliases` fields
3. Hit → reads the matched vault file(s) automatically
4. Miss → checks index freshness, offers rebuild

### Bidirectional Collaboration (Hermes ↔ Claude Code)

Two agents sharing one vault — each writes to their own directory:

```
vault/
├── wiki/              ← Claude Code writes here (Hermes reads)
│   ├── log.md         ← Shared collaboration channel
│   ├── career/        ← Job search materials
│   └── engineering/   ← Vibe coding lessons
├── hermes-knowledge/  ← Hermes writes here (Claude Code reads)
│   ├── job-search/    ← Company intel, job evaluations
│   ├── engineering/   ← Cross-project patterns
│   └── cron-knowledge/← Automated monitoring outputs
```

### Skill ↔ Vault Auto-Expansion (v3.4)

When an agent skill references vault files (via Obsidian wikilinks), the protocol auto-reads those files — creating a chain: skill → vault → context, without the user having to manually copy anything.

## Reference Implementation

`rebuild-vault-index.py` — A ~150-line Python script that implements the indexing protocol.

```bash
# Point it at your vault
python3 rebuild-vault-index.py \
  --vault ~/Documents/MyVault \
  --output ~/.hermes/vault-index.json \
  --scan wiki/projects wiki/career hermes-knowledge/
```

Features:
- Scans specified subdirectories for `.md` files
- Extracts YAML frontmatter (`title`, `aliases`, `summary_points`, `last_action`, `status`, `author`)
- Computes SHA256 content hash for incremental rebuilds
- Excludes files by configurable directory/filename patterns
- Respects `rag_exclude: true` in frontmatter
- Outputs JSON with path, title, summary, author, aliases, and hash

## Vault Index Schema

```json
{
  "version": "1.1",
  "updated": "2026-05-02T09:00:00+09:00",
  "entries": {
    "project-name": {
      "_content_hash": "a1b2c3...",
      "path": "/Users/.../wiki/projects/project-name.md",
      "title": "Project Name",
      "summary": {
        "status": "active",
        "key_points": ["First meaningful paragraph..."],
        "last_action": "2026-04-15: deployed v2.0"
      },
      "updated": "2026-04-15",
      "author": "cc",
      "aliases": ["project", "project-name", "alt name"]
    }
  }
}
```

## Auto-Injection Rules (Agent Protocol)

Agents implementing ORP must follow these rules:

1. **First tool call on non-trivial queries = `read_file(vault-index.json)`**
2. **Non-trivial = contains "why", "how", "analyze", "research", "before", "what is", "review"**
3. **Trivial = "run script", "check price", "send message" → skip**
4. **Index corruption → ask user to rebuild → do NOT silently skip**
5. **Index stale (>4 days) → offer rebuild**
6. **Alias matching: fuzzy substring, case-insensitive**

## Adoption

This protocol is currently running in production in my personal Hermes Agent setup:

- **30+ vault entries** indexed and auto-injected
- **2 agents** (Hermes + Claude Code) sharing 1 vault
- **Daily cron rebuild** with incremental change detection
- **Curator protection** preventing the agent from touching index-related skills

## Real-World Impact

**Before ORP** — every agent session is an amnesiac. **After ORP** — context is automatic, reliable, and zero-maintenance.

### 1. Conversation Continuity

- **Before**: You ask "what did we decide about the Coinbase partnership?" and the agent has no idea. You re-explain the entire history. Every. Single. Session.
- **After**: The agent reads `vault-index.json`, fuzzy-matches "Coinbase" against aliases, and pulls up your `coinbase-evaluation.md` — with status, key decisions, and last action — before you finish typing the question.

### 2. Multi-Agent Collaboration Without Chaos

- **Before**: Hermes writes research notes. Claude Code writes project docs. They're in separate silos — no shared context, no cross-referencing, no single source of truth.
- **After**: Two agents share one vault through directory partitioning. Hermes reads Claude Code's `wiki/` updates; Claude Code reads Hermes's `hermes-knowledge/` intel. The collaboration log (`log.md`) tracks everything. Both agents work from the same indexed context layer.

### 3. Bounded Token Cost on Context Injection

- **Before**: You paste your entire vault into the system prompt (thousands of tokens, every conversation) or manually search and attach files (tedious, error-prone, you forget things).
- **After**: One `read_file(vault-index.json)` call — ~15KB / ~4K tokens — triggered only on non-trivial queries. Only the matched vault file gets loaded, and only when relevant. Token cost is bounded by index size, not vault size.

---

## Status

ORP v1.0 spec is stable — this is what runs my daily workflow. The reference implementation is a single-file Python script that you can drop into any agent environment.

Open source under MIT License.

---

### Built on

<a href="https://github.com/nousresearch/hermes-agent"><img src="https://img.shields.io/badge/Hermes_Agent-Compatible-blue" alt="Hermes Agent Compatible"></a>
<a href="https://obsidian.md"><img src="https://img.shields.io/badge/Obsidian-Powered-7C3AED" alt="Obsidian Powered"></a>

ORP was built for the [Hermes Agent](https://github.com/nousresearch/hermes-agent) ecosystem and [Obsidian](https://obsidian.md) vaults. It works with any agent that can read files.

**For Hermes users**: install with one command [→ Installation Guide](INSTALL.md#agent-integration)

### Follow the Creator

- **Twitter/X**: [@vinentW789](https://x.com/vinentW789)
- **GitHub**: [wjameswen888](https://github.com/wjameswen888)

*I'm a marketing professional who builds AI infrastructure because someone had to.*
