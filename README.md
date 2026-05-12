# Obsidian RAG Protocol (ORP)

🌐 [English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

**ORP is a filesystem-native coordination protocol for two or more AI agents sharing one Obsidian vault.** It lets each agent see what other agents did through deterministic note retrieval plus a byte-cursor digest from an append-only `wiki/log.md` — no embeddings, no vector DB, no LLM in the retrieval path.

> **Brutally honest:** if you have one AI agent and want it to curate, rewrite, or "optimize" your vault, this is probably not the tool you want. Use [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) or [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) instead. ORP earns its keep when silent drift between agents costs you something real.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hermes Compatible](https://img.shields.io/badge/Hermes_Agent-Compatible-blue)](https://github.com/nousresearch/hermes-agent)
[![Obsidian](https://img.shields.io/badge/Obsidian-Powered-7C3AED)](https://obsidian.md)

### Key differentiators

- **Coordination, not curation.** ORP doesn't rewrite your notes or "optimize" your vault. Your content stays yours; ORP only coordinates what agents do around it.
- **Cross-agent awareness.** A byte-cursor digest at session start tells Agent B exactly what Agent A wrote since last time. No polling, no daemons.
- **Zero LLM at retrieval.** Deterministic alias substring matching, not embeddings or LLM re-ranking. The index is ~15 KB for 30 notes.

---

## The problem

Two AI agents working on the same Obsidian vault. Last night, Hermes wrote a market analysis to `hermes-knowledge/`. This morning, Claude Code has no idea — until you re-explain. Every. Single. Session.

The left hand doesn't know what the right hand did. **ORP is the shared blackboard between them.**

(If you have just one agent, this isn't your problem — you want a second-brain tool, not a coordination protocol. See the "Brutally honest" note above.)

## What it feels like with ORP

You start a new Claude Code session this morning. Before you've typed anything, this gets auto-injected into the agent's context:

```
[ORP digest · agent=cc · since byte 184459 · 2026-05-12T09:13:15+09:00]
🦅[hermes] 2026-05-12T07:30 · note · stock-pulse 调研完成并归档
🦅[hermes] 2026-05-12T07:31 · write · wukong 文学向精读报告 — 8/8 endings 全量覆盖
🦅[hermes] 2026-05-12T08:46 · write · Oppenheimer 文学精读 v1.3.0 — 7/7 endings
```

Claude Code knows what Hermes did overnight before you say a word. You don't re-explain. The session starts with shared context.

When you ask "what did we decide about X last month?" later in the conversation, ORP's pull side kicks in: the agent fuzzy-matches your keywords against aliases you control and reads only the matched note. ~15 KB JSON index. No embeddings. Nothing leaves your machine.

## How ORP relates to Karpathy's LLM Wiki and obsidian-second-brain

If you're already aware of [Karpathy's LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) or the [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) Claude Code skill, this section is for you. They live in the same neighborhood — markdown vaults, Obsidian, AI agents — but they solve different problems. ORP is not a replacement for either; it can sit underneath either of them.

### One-line each

- **Karpathy's LLM Wiki** is a *pattern*: an LLM reads sources at ingest time, builds and **maintains** a wiki of interlinked markdown pages. Knowledge is compiled once, then kept current. Single agent + human curates.
- **obsidian-second-brain** is an *implementation* of that pattern, expanded: 31 commands, scheduled background agents, the wiki **rewrites itself** when new sources arrive, contradictions reconcile automatically. Single Claude Code session + human.
- **ORP** is a *protocol* for two AI agents to share context across one vault: deterministic alias matching (no embeddings) for retrieval, byte-cursor session-start digest for cross-agent awareness, an append-only log for coordination. Vault content is yours; ORP doesn't rewrite it.

### Where they sit in the stack

```
┌──────────────────────────────────────────────┐
│ Application — knowledge synthesis            │
│ Karpathy's LLM Wiki · obsidian-second-brain  │
│ (ingest sources, mutate pages, lint, save)   │
├──────────────────────────────────────────────┤
│ Coordination — multi-agent state sync        │
│ ORP                                          │
│ (digest, log, cursor, alias matching)        │
├──────────────────────────────────────────────┤
│ Storage — markdown + git                     │
│ (Obsidian vault, frontmatter, wikilinks)     │
└──────────────────────────────────────────────┘
```

ORP sits below the application layer. obsidian-second-brain could, in principle, run on top of ORP (with each scheduled agent identifying itself via `--agent <id>` and writing log entries through `orp_reader.py log`). Karpathy's pattern is single-agent so coordination doesn't apply — but if you ever ran two agents against a Karpathy-style wiki, ORP's coordination layer would do useful work.

### Side-by-side

| Axis | Karpathy's LLM Wiki | obsidian-second-brain | **ORP** |
|------|---------------------|----------------------|---------|
| **What it solves** | Knowledge compounds vs. RAG re-derivation | Vault that maintains itself | Two agents staying in sync over one vault |
| **Layer** | Application (knowledge) | Application (knowledge) | Coordination (state) |
| **Agent count** | 1 + human | 1 + human (CC) | 2 (CC + Hermes); extensible |
| **Mutates vault pages?** | Yes (LLM rewrites at ingest) | Yes, aggressively (rewrites + reconciles) | **No** (append-only log; vault content untouched) |
| **Retrieval** | LLM at query time | LLM at query time + cached pages | **Deterministic substring alias matching, no LLM, no embeddings** |
| **Embeddings / vector DB** | Not specified | Optional (Perplexity sonar for research) | **None — by design** |
| **Awareness primitive** | Read whole wiki / page graph | Auto-loaded `## For future Claude` preambles | Per-agent byte-offset cursor over `log.md` |
| **Implementation** | A 1500-word gist (idea file) | 31 commands, 4 cron agents, hook system | 6 stdlib Python files (~1800 lines total) |
| **Multi-agent native?** | No | No | **Yes** |

### When to use what

- **You want one AI to maintain a wiki of your readings/notes that compounds over time.** Use Karpathy's pattern (or obsidian-second-brain if you want it pre-built).
- **You want one AI to manage your whole second brain — kanban, daily notes, contradiction reconciliation, scheduled agents.** Use obsidian-second-brain.
- **You have two or more AI agents writing to the same vault and they need to know what each other did.** Use ORP. (Pair it with either of the above if you also want knowledge synthesis.)

### What ORP is not trying to be

- **Not a wiki maintainer.** ORP doesn't summarize sources, doesn't update entity pages, doesn't reconcile contradictions. It's the layer that lets agents coordinate; what they write to the vault is their business.
- **Not a knowledge compounder.** No LLM-driven page mutation. ORP's append-only log is deliberately the opposite design choice from "wiki rewrites itself" — losing audit trail to gain compactness is a trade we won't make.
- **Not a Claude Code skill.** ORP is a filesystem protocol any agent can implement (CC and Hermes are reference implementations); skill packages built on top of it are application-layer work.

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

## Session-start sync (v1.4+)

Up to v1.3, ORP was pull-only: the index gets read when the user mentions an aliased keyword. That left a gap. If Hermes wrote a note at 3am while Claude Code was offline, Claude Code had no way to know — until the user happened to ask about it.

v1.4 closes the gap. Each agent calls `orp_reader.py digest --agent <id>` at session start and gets a short list of what's happened in the shared log since it last looked:

```
[ORP digest · agent=cc · since byte 118402 · 2026-05-07T09:15:00+09:00]
🦅[hermes] 2026-05-07T03:14:22+09:00 · write · cron-knowledge/timeout-investigation.md — 4 个 aux 模型 timeout 排查
🦅[hermes] 2026-05-07T08:05:11+09:00 · note · ORP v1.3 alias 批量补全 60 → 58
🦅[hermes] 2026-05-07T08:30:00+09:00 · done · vault-health-check skill 长期化重写
```

That's the whole protocol surface for the push side. Implementation:

- `wiki/log.md` is the existing collaboration channel (§5.2). v1.4 standardizes its entry format with ISO-8601 timestamps and a closed action vocabulary so a byte-offset cursor parses cleanly.
- Each agent has a per-agent cursor at `<vault>/.orp/cursor-<id>.json`. Different agents see digests of the same shared log from their own positions.
- Agents write to the log with `orp_reader.py log --agent <id> --action <write|note|done|decision> "msg"` — never by hand-editing — so the format stays consistent and the cursor doesn't choke.
- Best-effort by design: vault unavailable, log missing, corrupt cursor → silent exit 0. A digest failure must not block agent startup.

No mtime scans, no daemon, no polling. The append-only log is the only state. Wiring is one hook per agent — see [INSTALL.md → Session-Start Digest](INSTALL.md#session-start-digest-v14).

Adding a third agent (Codex, Cursor, your own): pick an id, write events through `orp_reader.py log --agent <id>`, wire the session-start hook to call `digest --agent <id>`. No structural vault changes.

**v1.5 update — auto-log via PostToolUse + Stop hooks.** Dogfooding v1.4 showed CC agents reliably miss the "call `orp_reader.py log` after vault writes" rule (0 entries logged across ~41 vault writes in one week, while Hermes logged 47 across the same window). v1.5 ships an optional two-hook mechanism: a PostToolUse stager records each vault edit to a per-session pending file, and a Stop hook flusher writes ONE summary log entry per turn (action `note`, prefix `auto:`). One entry per turn, not per edit — keeps signal tight. Hermes-style background agents that already log reliably don't need it. See [INSTALL.md → Auto-log Hooks](INSTALL.md#auto-log-hooks-v15) and protocol §5.6.

## Compared to alternatives

| Approach | Tradeoff vs ORP |
|---|---|
| Paste vault into system prompt | Simple but blows context budget every conversation; no incremental update |
| Vector DB / embeddings (LlamaIndex, Mem0, Letta) | Semantic match works, but heavy: chunking, embedding cost, opaque retrieval, drift over time |
| Obsidian MCP server | Read-time access, but no curated alias layer — agent has to grep/search the whole vault per query |
| **ORP** | Aliases are explicit (you control them), retrieval is deterministic, latency near zero. Tradeoff: alias-keyword matching only, no semantic match |

ORP wins when you'd rather curate 5 aliases per important note than tune embedding chunking.

## Status

Spec is at v1.5. The repo ships six single-file Python utilities (stdlib-only, ~1,900 lines) plus two reference hook scripts.

What's running:
- A 40-ish-entry vault on a single laptop, three months and counting
- Two agents (Hermes + Claude Code) sharing one vault with separate write directories
- Daily scheduled rebuild plus staleness-prompt fallback
- Session-start digest wired into both agents' startup hooks (v1.4)
- Auto-log PostToolUse + Stop hooks on the Claude Code side (v1.5) — fixes the empirical "CC writes vault but doesn't log" gap that surfaced in v1.4 dogfood

Honest framing: this is a hand-rolled spec from one user's setup. There are no third-party adopters yet — the spec is offered as something you might find useful, not as a community standard. If you adopt it, file issues; the spec moves with real usage.

Intentionally not done:
- No semantic / fuzzy-vector search
- No automated alias generation
- No GUI / dashboard
- No wiki self-rewriting (see comparison section — append-only log is a deliberate counter-design to "vault rewrites itself")

## Reference

- [`rebuild-vault-index.py`](rebuild-vault-index.py) — single-file indexer
- [`orp_reader.py`](orp_reader.py) — single-file reader (library + CLI: `match` / `get` / `status` + v1.4 `log` / `digest`)
- [`orp_health.py`](orp_health.py) — schema, freshness, and alias-coverage validator
- [`orp_link_check.py`](orp_link_check.py) — wikilink integrity scanner (skips fenced code blocks)
- [`expand_aliases.py`](expand_aliases.py) — bulk frontmatter alias updater (when alias coverage is thin · spec §3.4)
- [`convert_bare_to_fullpath.py`](convert_bare_to_fullpath.py) — bulk migrate bare wikilinks to full paths (spec §3.5)
- [`examples/orp-vault-stage.py`](examples/orp-vault-stage.py) + [`orp-vault-flush.py`](examples/orp-vault-flush.py) — v1.5 PostToolUse + Stop hook reference impl (spec §5.6)
- [`INSTALL.md`](INSTALL.md) — installation, four trigger paths, agent integration, session-start digest wiring, auto-log hook wiring
- [`OBSIDIAN-RAG-PROTOCOL.md`](OBSIDIAN-RAG-PROTOCOL.md) — full protocol spec (v1.5)
- [`examples/`](examples/) — three real notes you can run the full loop against in 30 seconds, plus the v1.5 hook scripts

## License

MIT. See [LICENSE](LICENSE).

Built on top of [Hermes Agent](https://github.com/nousresearch/hermes-agent) and [Obsidian](https://obsidian.md), and works with any agent that can read files.

Maintained by [Vincent Wen](https://github.com/wjameswen888).
