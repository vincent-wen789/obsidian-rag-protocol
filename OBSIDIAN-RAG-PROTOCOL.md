# OBSIDIAN-RAG-PROTOCOL.md

## Version 1.1

Changes from 1.0:
- Index document gains a top-level `version` field (required).
- `updated` field is an ISO-8601 timestamp with timezone offset (was date-only).
- Cross-scan-dir entry_id collisions are deterministically disambiguated with the scan-root basename — see §1.3.
- Indexer writes are atomic (tmp + rename); a crashed rebuild never leaves a half-written index.
- A corrupted index is renamed to `<name>.broken-<ts>` instead of being silently overwritten — preserves hand-curated aliases for recovery.
- §5.2 specifies atomic-append semantics for the collaboration log.

---

## Abstract

The Obsidian RAG Protocol (ORP) defines how AI agents retrieve context from an Obsidian vault using a machine-readable JSON index. It enables low-overhead lazy context injection, incremental index updates, bidirectional multi-agent collaboration, and automatic skill-to-vault context expansion.

---

## 1. Vault Index

### 1.1 Location

The index file is a JSON document stored at a configurable path (default: `~/.hermes/vault-index.json`). Must be accessible to the agent via filesystem read.

### 1.2 Schema

```json
{
  "version": "1.1",
  "updated": "2026-05-02T09:00:00+09:00",
  "entries": {
    "<entry-id>": {
      "_content_hash": "<sha256-hex>",
      "path": "<absolute-path>",
      "title": "<human-readable-title>",
      "summary": {
        "status": "<active|draft|archived|unknown>",
        "key_points": ["<string>", ...],
        "last_action": "<optional-string>"
      },
      "updated": "<YYYY-MM-DD or ISO-8601>",
      "author": "<cc|hermes|vincent|shared>",
      "aliases": ["<searchable-string>", ...]
    }
  }
}
```

`entries` is an object keyed by entry_id (not an array). Readers MUST treat unknown top-level keys as forward-compatible additions and ignore them.

### 1.3 Entry ID

Derived from filename stem: lowercase, with spaces and underscores replaced by hyphens.

When the same naive entry_id would be produced by two files in different scan roots, the indexer MUST disambiguate by prefixing the scan-root basename: `<scan-root-slug>-<naive-id>`. Disambiguation applies to ALL colliding entries, not just the second one — this keeps IDs stable across rebuilds. Non-colliding entries keep their bare stem-based ID.

The indexer MUST emit a `NOTE:` to stderr the first time a collision is observed in a run. If even the disambiguated form collides (two files with the same name in same-named subdirectories of two different scan roots), the indexer MUST emit a `WARNING:` to stderr and keep the last write.

### 1.4 Size Target

Index should remain under 20KB. If growing beyond, consider adding directory-specific cutoff days, archiving stale entries to a separate cold index, or raising the age threshold.

---

## 2. Indexing Algorithm

### 2.1 Scan Directories

The indexer scans configured subdirectories of the Obsidian vault. Each scan target includes:
- Path (relative to vault root)
- Author (`cc` | `hermes` | `vincent` | `shared`)
- Cutoff days (max file age, `null` = unlimited)

### 2.2 Exclusion Rules

Files are excluded **by path and filename patterns**, NOT by frontmatter type field. Rationale: frontmatter can be forgotten; path patterns are deterministic.

Default exclusions:
- Directories: `archived`, `archive`, `log`, `modes`, `tracking`, `task-*`
- Filename patterns: `plan-*`, `*-progress`, `*-data-YYYY-MM`
- Known non-content: `index.md`, `README.md`

Frontmatter opt-out: if `rag_exclude: true` in YAML frontmatter, skip regardless of path.

### 2.3 Filter Pipeline

```
file found → should_index() checks:
  1. Filename in SKIP_FILES? → reject
  2. Any parent dir in EXCLUDE_DIRS? → reject
  3. Filename matches EXCLUDE_PATTERNS? → reject
  4. Frontmatter rag_exclude: true? → reject
  5. Modified > CUTOFF_DAYS ago? → reject
  6. → PASS — proceed to extraction
```

### 2.4 Content Hashing

**SHA256 of file content** — NOT modification time (mtime). Rationale:

- macOS iCloud sync mutates mtime unpredictably
- Git operations change mtime on checkout
- Content hashing is deterministic and cross-platform

On incremental rebuild: if `_content_hash` matches previous run, skip extraction entirely. Preserve all previous metadata (aliases, summary, title).

### 2.5 Frontmatter Extraction

Extract YAML frontmatter (`---\n...\n---` block at file start). Support:
- Simple key: value
- Inline lists: `key: [a, b, c]`
- Multi-line lists: `key:\n  - a\n  - b`

Fields extracted:
- `title` → entry title
- `aliases` → alias array
- `summary_points` → key_points array
- `last_action` → last_action string
- `status` → status
- `author` → author (overrides scan directory default)
- `updated` → updated date
- `rag_exclude` → exclusion flag

### 2.6 Summary Extraction

Frontmatter-driven, with plain-text fallback:

1. **status**: from `status` frontmatter field, fallback `"unknown"`
2. **key_points**: from `summary_points` list, fallback to first meaningful paragraph in body
3. **last_action**: from `last_action` field ONLY — never inferred from body text. If absent, omit the key

First paragraph extraction: skip frontmatter block, skip headings (`#`), blockquotes (`>`), tables (`|`), HTML comments (`<!--`). Take first non-empty line, truncate at 150 chars.

---

## 3. Alias Resolution

Aliases enable keyword-to-entry matching during context injection.

### 3.1 Resolution Priority

1. **Frontmatter `aliases` field** — Obsidian native. If present and non-empty, REPLACES all other aliases
2. **Hand-curated ALIAS_MAPS** — Maintained in the rebuild script. Authoritative when no frontmatter override
3. **Previous run aliases** — Carried forward on incremental rebuild (hash unchanged)
4. **Fallback** — `[entry_id, title.lower().replace(' ', '-')]`

### 3.2 Scalar Aliases Tolerance

If frontmatter `aliases` is a string (not an array), auto-wrap as single-element array.

### 3.3 Aliases Never Auto-Generated

Aliases are only updated when:
- Frontmatter explicitly changes
- Hand-curated ALIAS_MAPS is manually edited

No algorithmic alias generation. This prevents drift.

---

## 4. Auto Context Injection (Agent Behavior)

### 4.1 Trigger Classification

**Non-trivial queries** (→ MUST read index as first tool call):
- Contains: why, how, analyze, research, review, before, "what is", "what are", "help me understand"

**Trivial queries** (→ skip RAG, execute directly):
- "run X", "check price", "change config", "send message", "execute script"

**Uncertain** → bias toward triggering. Cost of a false positive = one 15KB file read.

### 4.2 Matching Algorithm

1. Extract keywords from user query
2. Fuzzy-match against `aliases` arrays in vault-index.json (substring, case-insensitive)
3. Hit → `read_file` the matched vault file(s)
4. No hit → check `updated` field age:
   - ≥ 4 days → offer index rebuild
   - < 4 days → ask user for clarification

### 4.3 Error Handling

- Index file missing → ask user to run rebuild script
- JSON parse error → "Index corrupted, rebuild?" — do NOT silently skip. The indexer MUST preserve the broken file at `<index-path>.broken-<ts>` rather than overwriting it on the next rebuild.
- Index stale (>4 days) → offer rebuild, do NOT auto-rebuild
- Rebuild MUST be atomic — write to a temp file in the same directory and `rename(2)` into place. A reader observing the index path mid-rebuild MUST always see either the previous valid index or the new one, never a partial write.

---

## 5. Bidirectional Multi-Agent Protocol

### 5.1 Directory Partitioning

Two agents sharing one vault with separated write directories:

```
vault/
├── wiki/              ← Agent A writes here (Agent B reads)
├── hermes-knowledge/  ← Agent B writes here (Agent A reads)
└── shared/            ← Both read, designated author writes
```

### 5.2 Collaboration Channel

A designated file (`wiki/log.md`) acts as the inter-agent communication log. Both agents append entries with format `🦅[Agent] <message>`. This file is NEVER overwritten — append-only.

Writers MUST use atomic append semantics, since two agents may write concurrently:
- Open with `O_APPEND` and issue a single `write(2)` ≤ `PIPE_BUF` (4096 bytes on Linux/macOS), OR
- Hold an `flock(LOCK_EX)` for the duration of the write.

Entries longer than `PIPE_BUF` MUST use the lock approach. Naive `read → modify → write` is forbidden — it loses concurrent writes.

### 5.3 Cross-Write Protocol

If Agent A needs to write to Agent B's directory:
1. Source page stays in Agent A's directory
2. Agent B's directory gets a wikilink reference (Obsidian `[[path/to/source]]`)
3. Frontmatter must include `author: shared`

### 5.4 Index Coverage

The vault index must cover both agents' content directories. Entries include `author` field for filtering by agent.

---

## 6. Skill ↔ Vault Auto-Expansion (v3.4)

When an agent skill file references vault documents:

### 6.1 Trigger

Skill content contains Obsidian wikilinks (`[[hermes-knowledge/...]]` or `[[wiki/...]]`) AND the current task involves the referenced domain.

### 6.2 Behavior

Agent automatically `read_file`s referenced vault pages in the same turn as skill loading.

### 6.3 Limits

- Max 3 vault files auto-read per skill (if >3, read top 3 by relevance)
- Template variables (`{date}`, `{timestamp}`) in wikilinks → do NOT expand
- Broken links → note and continue, do NOT block execution

---

## 7. Incremental Rebuild Strategy

### 7.1 Core Principle

Content hash comparison drives incremental updates. Only re-extract frontmatter and summary when SHA256 changes.

### 7.2 States

| Old exists? | Hash matches? | Action |
|-------------|--------------|--------|
| Yes | Yes | Reuse old entry (aliases, summary, all metadata) |
| Yes | No | Full re-extraction from file |
| No | — | New entry, full extraction |

### 7.4 Cutoff Window

The indexer applies a rolling age cutoff (default 90 days, configurable) to bound the working set. The cutoff MUST NOT drop a file that already has an entry in the previous index — once indexed, an entry stays until the file is removed from the vault or matches an exclusion rule. Otherwise hand-curated aliases for older notes silently disappear after the cutoff window.

### 7.3 Change Count

Rebuild output MUST report changed entry count for monitoring. Zero changes = healthy incremental path.

---

## 8. Curator Protection

### 8.1 Pin Protocol

All ORP-related agent skills must be pinned via the agent's curator system to prevent automatic archival or modification.

### 8.2 Protected Artifacts

- The rebuild script
- The RAG documentation skill
- The indexing cron job definition
- The index file path configuration

---

## 9. Reference Implementation

See `rebuild-vault-index.py` in this repository. It implements all sections of this protocol in a single-file Python script with no external dependencies beyond stdlib.

---

## 10. Adoption Checklist

To adopt ORP for your agent:

- [ ] Configure vault path and scan directories
- [ ] Define exclusion patterns for your vault structure
- [ ] Set up auto context injection rules in your agent's system prompt
- [ ] Run initial index build
- [ ] Schedule daily rebuild (cron or equivalent)
- [ ] Pin ORP-related skills from curator/auto-cleanup
- [ ] Verify: agent reads vault-index.json on non-trivial queries
- [ ] Verify: incremental rebuild shows 0 changes when vault is unchanged

---

## Appendix: Design Philosophy

1. **Index is machine-readable, not LLM-reasoned** — JSON lookup, zero prompt token overhead
2. **Frontmatter drives content** — the human controls summaries and aliases
3. **Path-based exclusion** — deterministic, not dependent on frontmatter discipline
4. **Hash-based incremental** — immune to filesystem time quirks
5. **Aliases are curated, not generated** — quality over quantity in search matching
6. **Two agents, one vault** — separate write directories, shared read
