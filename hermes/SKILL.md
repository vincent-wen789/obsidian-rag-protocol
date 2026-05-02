---
name: obsidian-rag
description: Obsidian RAG Protocol (ORP) skill for retrieving long-term memory from an Obsidian vault. Use this skill whenever the user asks a question that involves context from their personal notes, past decisions, project history, research, or any knowledge stored in their Obsidian vault. This includes queries containing keywords like "why", "how", "analyze", "research", "review", "before", "what is", "what are", "help me understand", or any question where the agent would benefit from vault context. Also use this skill when the user mentions specific projects, people, or topics that might have corresponding notes in the vault. Even for seemingly simple questions, if they reference something the user has previously discussed or documented, the vault index should be consulted first.
tags:
  - obsidian
  - rag
  - memory
  - knowledge
  - vault
  - context-injection
  - personal-api
triggers:
  - what did we decide
  - what were we working on
  - remind me about
  - what is the status of
  - analyze
  - research
  - review
  - before we
  - how does
  - why did
---

# Obsidian RAG Protocol (ORP) — Agent Skill

This skill gives you persistent, zero-overhead access to the user's Obsidian vault. Instead of forgetting everything between sessions, you can now retrieve relevant notes automatically based on what the user asks.

## How It Works

The cornerstone of ORP is a single machine-readable file: `vault-index.json`. This file contains a structured index of every relevant note in the vault — titles, summaries, aliases, and file paths. It is rebuilt daily by a cron job, so it stays fresh without any manual effort.

Instead of scanning the entire vault (which would cost thousands of tokens), you make **one** `read_file` call to the index, fuzzy-match the user's question against the aliases, and then read only the matched note(s). The total overhead is ~15KB for the index read, plus only the specific notes you need.

## When to Read the Vault Index

**Always read `vault-index.json` as your first tool call on non-trivial queries.** A non-trivial query is any question where context from the user's notes would improve your answer.

### Non-trivial → MUST read index first

Queries containing these signal words (or their intent):
- "why", "how", "analyze", "research", "review"
- "before", "what is", "what are", "help me understand"
- Any question about past decisions, project history, people, or topics
- Questions referencing specific names, projects, or domains the user may have documented

### Trivial → Skip the index

Direct action commands that need no context:
- "run X", "check price", "send message", "change config"
- Simple factual lookups unrelated to personal knowledge
- Formatting, editing, or transformation tasks with no knowledge-retrieval component

### When uncertain → Read the index

The cost of a false positive is one small file read (~15KB). The cost of a false negative is answering without crucial context. Always bias toward triggering.

## How to Match Aliases

After reading `vault-index.json`, extract keywords from the user's query and match them against the `aliases` arrays in each entry:

1. **Fuzzy substring matching** — case-insensitive, partial matches count. "Coinbase" matches an alias "coinbase-evaluation". "Project alpha" matches "project-alpha".
2. **Multiple matches** — if several entries match, read all of them (up to a reasonable limit of ~5 files).
3. **No matches** — see Fallback Behavior below.
4. **Priority** — if a keyword matches both an entry ID and an alias, prefer the entry ID match.

### Matching Examples

- User asks "What's the status of Project Alpha?" → keyword "project alpha" → matches alias `["project", "project-alpha", "alpha"]` → read the matched file
- User asks "How did we evaluate the Coinbase partnership?" → keyword "coinbase" → matches alias `["coinbase", "coinbase-evaluation", "cb"]` → read the matched file
- User asks "What's 2 + 2?" → trivial query → skip index entirely

## The 6 Auto-Injection Rules

These are the hard rules for how you interact with the vault index. Follow them in order:

### Rule 1: First tool call on non-trivial queries = `read_file(vault-index.json)`

Before you reason about the user's question, before you search the web, before you do anything else — read the index. The index path is `~/.hermes/vault-index.json` by default, or whatever path is configured in `ORP_INDEX_PATH`.

### Rule 2: Non-trivial classification

Use the keyword/intent signals above. When in doubt, classify as non-trivial. The token cost of reading the index is negligible (~15KB); the cost of missing context is not.

### Rule 3: Index file missing or corrupted → ask the user to rebuild

If `vault-index.json` doesn't exist or contains invalid JSON, do NOT silently skip the protocol. Tell the user explicitly:

> The vault index file is missing or corrupted. Please run the rebuild script:
> `python3 rebuild-vault-index.py --vault <VAULT_PATH> --output ~/.hermes/vault-index.json --scan <DIRS>`

### Rule 4: Index stale (≥4 days old) → offer rebuild

Check the `updated` field in the index. If it's 4 or more days old, inform the user:

> The vault index was last updated on {date}, which is more than 4 days ago. Would you like me to rebuild it now?

Do NOT auto-rebuild without asking. The rebuild script may take a moment and the user should consent.

### Rule 5: Fuzzy alias matching — substring, case-insensitive

After reading the index, look for keyword matches in the `aliases` arrays. Use substring matching (not exact). "Crypto" matches an alias containing "crypto". Case does not matter.

### Rule 6: No match found → fall back gracefully

If no alias matches the user's query:
- If the index is fresh (<4 days), ask the user for clarification: "I couldn't find any notes matching '{keywords}' in the vault. Could you rephrase or tell me which note you're referring to?"
- If the index is stale (≥4 days), offer a rebuild first — the note might be new and not yet indexed.

## Fallback Behavior Summary

| Condition | Action |
|-----------|--------|
| Index missing | Ask user to rebuild (Rule 3) |
| Index corrupted (bad JSON) | Ask user to rebuild (Rule 3) |
| Index stale (≥4 days) | Offer rebuild, proceed with stale data (Rule 4) |
| No alias match, index fresh | Ask user for clarification (Rule 6) |
| No alias match, index stale | Offer rebuild first (Rule 6) |
| Alias match found | Read matched vault file(s) and use as context |

## Index Schema Reference

When you read `vault-index.json`, expect this structure:

```json
{
  "updated": "YYYY-MM-DD",
  "entries": {
    "<entry-id>": {
      "_content_hash": "<sha256-hex>",
      "path": "<absolute-path-to-md-file>",
      "title": "<human-readable-title>",
      "summary": {
        "status": "<active|draft|archived|unknown>",
        "key_points": ["<string>", ...],
        "last_action": "<optional-string>"
      },
      "updated": "<YYYY-MM-DD>",
      "author": "<cc|hermes|vincent|shared>",
      "aliases": ["<searchable-string>", ...]
    }
  }
}
```

Key fields to use:
- `aliases` — the primary matching target for keyword lookup
- `path` — the file to `read_file` when a match is found
- `summary` — useful context even before reading the full note
- `updated` — check this for staleness (Rule 4)
- `author` — know which agent wrote this note (useful in bidirectional setups)

## Skill ↔ Vault Auto-Expansion

When this skill file references vault documents via Obsidian wikilinks (e.g., `[[hermes-knowledge/project-alpha]]`), and the current task involves the referenced domain, automatically `read_file` those vault pages in the same turn as skill loading.

Limits:
- Max 3 vault files auto-read per skill load (if more than 3, pick top 3 by relevance)
- Template variables (`{date}`, `{timestamp}`) in wikilinks — do NOT expand
- Broken links — note and continue, do NOT block execution

## Incremental Rebuild

The rebuild script (`rebuild-vault-index.py`) uses SHA256 content hashing for incremental updates. This means:
- Running it again when nothing changed produces `0 changed` entries
- It preserves manually curated aliases across rebuilds
- It's safe to run daily (or even multiple times per day)
- iCloud sync quirks on macOS won't cause false positives (mtime is not used)

## Bidirectional Multi-Agent Note

If two agents share this vault, they each write to their own directory and read from the other's. The `author` field in each index entry identifies who wrote what. Respect directory partitioning:
- Your agent's write directory = your knowledge base
- Other agent's directory = read-only from your perspective
- `shared/` = both read, designated author writes
- `log.md` = collaboration channel (append-only, never overwrite)