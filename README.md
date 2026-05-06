# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

Give your AI agent long-term memory by pointing it at your Obsidian vault. No embeddings, no vector DB, fully local.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

---

## The problem

You ask your AI agent, "what did we decide about X last month?" — and it has no idea. You re-explain. Every. Single. Session.

You already wrote it down in Obsidian. The agent just can't see it.

## What it feels like with ORP

```
You: 我们之前对 Coinbase Japan 的判断是？

Agent: Based on wiki/career/coinbase-japan-analysis.md
       (last updated 2026-04-11):
       • status: archived
       • 判断: 規制リスク過大、後発参入劣勢明顯
       • last action: 2026-04-11 写入分析笔记
       Source: alias "Coinbase" matched.
```

The agent reads a single ~15KB JSON index, fuzzy-matches your question against aliases you control, and pulls only the matched note. No embeddings. No external service. Nothing leaves your machine.

## Quick start

```bash
git clone https://github.com/wjameswen888/obsidian-rag-protocol.git
cd obsidian-rag-protocol
bash hermes/install.sh
```

The installer asks for your vault path, sets up a daily cron job, and wires the indexer into Hermes. Three minutes, one terminal.

Not using Hermes? See [Other agents](#other-agents) — the integration is one prompt rule plus a cron job.

## What it does, in plain terms

- **Builds a small JSON index of your vault.** One file. ~15KB for 30 notes. Frontmatter (title, aliases, status, last action) extracted and laid out for fast lookup.
- **Rebuilds incrementally.** SHA256 content hashing — unchanged notes don't re-extract. Daily cron is fine.
- **Agent reads the index, not the vault.** First tool call on any non-trivial question is `read_file(vault-index.json)`. The agent never scans your full vault.
- **Fuzzy alias matching.** You curate the keywords (in frontmatter, or a side JSON). Match → agent reads that one note. Miss → falls through to "ask user".

## How it works

```
your vault                       indexer (cron, daily)
  ├── wiki/projects/             ┌─────────────────────┐
  ├── wiki/career/         ─────►│ rebuild-vault-      │──┐
  └── hermes-knowledge/          │ index.py            │  │ writes
                                 │ (SHA256 + frontmatter│  │
                                 └─────────────────────┘  ▼
                                                    vault-index.json
                                                       (~15KB)
                                                          │
                                                          ▼
your agent (Hermes / Claude / etc.)
  user asks non-trivial question
       │
       ├──► read_file(vault-index.json)        # 1 tool call
       ├──► fuzzy-match keywords against aliases
       ├──► hit → read_file(matched note)      # 1 tool call
       └──► miss → ask user / offer rebuild
```

Full protocol: [OBSIDIAN-RAG-PROTOCOL.md](OBSIDIAN-RAG-PROTOCOL.md). Schema, alias resolution, multi-agent collaboration, error handling, all specified.

## What this is NOT

- **Not embedding-based.** No vectors, no semantic search. If a question doesn't match an alias, ORP doesn't pretend to retrieve it.
- **Not auto-tagging.** Aliases come from frontmatter or a curated map. The indexer never invents them — keeps retrieval predictable.
- **Not cross-machine sync.** Your vault, your laptop. iCloud / Syncthing / Dropbox handle the file layer; ORP runs on top.
- **Not a hosted service.** One Python script (stdlib only) plus a JSON file. No account, no API key.

## Will this work for you?

| You have... | Fit |
|---|---|
| An Obsidian vault | Yes |
| Some other folder of `.md` notes | Yes — ORP just scans `.md` files, the "Obsidian" part is the frontmatter convention |
| A vault with no frontmatter | Yes, with fallback aliases (filename stems). Add `aliases:` to important notes for better recall |
| 1000+ notes | Yes — `--cutoff-days` keeps the working set bounded; previously-indexed notes don't drop out |
| Use Hermes | Direct fit, `install.sh` handles it |
| Use Claude Code, Cursor, ChatGPT, custom agent | Yes — ORP is a JSON file. See [Other agents](#other-agents) |
| Need true semantic search ("notes related to X") | No — use LlamaIndex, Mem0, or similar |

## Other agents

ORP is filesystem + JSON. Any agent that can:

1. Read a file on demand (`read_file`, `cat`, an MCP filesystem server, etc.)
2. Have a system prompt rule: *"For non-trivial queries, first read `~/.hermes/vault-index.json`. Match the query against `aliases` substrings. If a match is found, read the entry's `path`."*

…can use ORP. Schedule the rebuild via cron, launchd, systemd timer, or whatever your platform uses. Full per-agent guide in [INSTALL.md → Agent Integration](INSTALL.md#agent-integration).

## FAQ

**Does this send my notes anywhere?**
No. The indexer is Python stdlib only — no network calls. The index file lives at a path you control (default `~/.hermes/vault-index.json`).

**My vault has 800 notes. Will the index blow up?**
The index targets <20KB. With `--cutoff-days 90` (default), only notes touched in the last 90 days are indexed. Older notes that are already in the index stay (they don't get dropped just because they aged out).

**Do I need to add frontmatter to all my notes?**
No. The indexer falls back to first-paragraph extraction and filename-derived aliases. Adding `aliases: [...]` and `summary_points: [...]` to frequently-referenced notes makes retrieval sharper.

**What if two notes have the same filename in different folders?**
Disambiguated automatically with the scan-root prefix (`career-coinbase` vs `projects-coinbase`). The indexer warns on collision.

**What if the index file gets corrupted?**
Renamed to `<name>.broken-<ts>` and a fresh one is rebuilt. Hand-curated aliases in the broken file remain recoverable from the renamed copy.

**Can two agents share one vault?**
Yes — that's what `wiki/` and `hermes-knowledge/` are for in the example. Each agent writes to its own directory, both read everything. Atomic-append rules for the shared `log.md` are specified in §5.2 of the protocol.

## Day-to-day maintenance

The whole loop, end to end:

1. **You write a note in Obsidian.** Frontmatter (`title`, `aliases`, `summary_points`) is optional — no frontmatter still works, you just get filename-based fallback aliases.
2. **The index rebuilds automatically.** Pick a trigger from `INSTALL.md` — system cron, your agent's scheduler, coupled into another job, or just "agent prompts you when stale." Most setups use a daily scheduled rebuild plus the staleness prompt as a safety net.
3. **The agent reads the index on recall-intent questions.** "What did we decide about X?" → agent reads `vault-index.json`, fuzzy-matches "X" against your aliases, reads the matched note, answers with context.
4. **The agent prompts you when the index is stale.** ≥4 days old by default — you say "rebuild," it runs the script, you continue. No silent staleness.
5. **You health-check periodically.** `python3 orp_health.py` flags schema drift, orphan paths, oversized indexes. Run it in CI or after a vault reorg.

That's it. No retraining, no embedding refresh, no vector DB to maintain.

## ORP isn't read-only

The protocol surface is the index, but real ORP setups use the vault bidirectionally — agents both read existing notes and write new ones back, on triggers. A few patterns that work in production:

| Trigger | What gets written | Where |
|---|---|---|
| Daily job-board scrape | Top N matched listings for the day | `hermes-knowledge/job-search/daily-push-log.md` |
| Weekly market snapshot job | One-page recap with key signals | `hermes-knowledge/market/weekly-snapshot-{YYYY-Www}.md` |
| Cron-detected anomaly (price, on-chain, macro) | Notable-event entry | `hermes-knowledge/cron-knowledge/{category}/` |
| Agent finishes a substantive task | Decision log + open questions | `wiki/career/`, `wiki/projects/`, etc. |
| Inter-agent coordination | Append entry to shared log | `wiki/log.md` (under §5.2 atomic-append rules) |

These aren't part of the protocol contract — they're *applications* of it. Document the triggers your agent should fire, point each at a vault subdirectory, and your second brain accumulates without you copy-pasting. The index picks up the new entries on its next rebuild.

## Compared to alternatives

| Approach | Tradeoff vs ORP |
|---|---|
| Paste vault into system prompt | Simple but blows context budget every conversation; no incremental update |
| Vector DB / embeddings (LlamaIndex, Mem0, Letta) | Semantic match works, but heavy: chunking, embedding cost, opaque retrieval, drift over time |
| Obsidian MCP server | Read-time access, but no curated alias layer — agent has to grep/search the whole vault per query |
| **ORP** | Aliases are explicit (you control them), retrieval is deterministic, latency near zero. Tradeoff: alias-keyword matching only, no semantic match |

ORP wins when you'd rather curate 5 aliases per important note than tune embedding chunking.

## Status

Spec is at v1.2. The repo ships four single-file Python utilities, all stdlib-only — together about 1,000 lines.

What's running:
- A 40-ish-entry vault on a single laptop, three months and counting
- Two agents (Hermes + Claude Code) sharing one vault with separate write directories
- Daily scheduled rebuild plus staleness-prompt fallback

Honest framing: this is a hand-rolled spec from one user's setup. There are no third-party adopters yet — the spec is offered as something you might find useful, not as a community standard. If you adopt it, file issues; the spec moves with real usage.

Intentionally not done:
- No semantic / fuzzy-vector search
- No automated alias generation
- No GUI / dashboard

## Reference

- [`rebuild-vault-index.py`](rebuild-vault-index.py) — single-file indexer
- [`orp_reader.py`](orp_reader.py) — single-file reader (library + CLI)
- [`orp_health.py`](orp_health.py) — schema and freshness validator
- [`orp_link_check.py`](orp_link_check.py) — wikilink integrity scanner
- [`expand_aliases.py`](expand_aliases.py) — bulk frontmatter alias updater (when alias coverage is thin · spec §3.4)
- [`INSTALL.md`](INSTALL.md) — installation, four trigger paths, agent integration
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) — full protocol spec (v1.2)
- [`examples/`](examples/) — three real notes you can run the full loop against in 30 seconds

## License

MIT. See [LICENSE](LICENSE).

Built on top of [Hermes Agent](https://github.com/nousresearch/hermes-agent) and [Obsidian](https://obsidian.md), and works with any agent that can read files.

Maintained by [Vincent Wen](https://github.com/wjameswen888).
