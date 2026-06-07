# OBSIDIAN-RAG-PROTOCOL.md

## Version 1.7.1

Changes from 1.7:
- §2.6 / reference impl — **`status` enum reconciliation** (the fast-follow deferred in 1.7). The canonical `status` enum is the six §1.2 values `{captured, candidate, verified, retrievable, stale, archived}`; the default retrieval filter includes the four live values and excludes `{stale, archived}`. `unknown` was never a member, yet the alias indexer (`rebuild-vault-index.py`) emitted it as the missing-field fallback while the semantic layer (`vault_vec.py`) fell back to `verified` — so the two layers stamped un-statused notes differently, and status-aware consumers (the §3.10 stale-dedup report and §3.8 backlinks filter, both of which exclude any non-live value) would treat an `unknown`-stamped entry as non-live. Separately, `vault_lookup.py backlinks` defaulted to `{verified, draft}` — `draft` is not a valid §1.2 status, and the default dropped `captured`/`candidate`/`retrievable`. Now a missing **or unrecognized** `status` normalizes to **`captured`** everywhere — live (retrievable, never silently dropped) and honest (does not claim verification), matching the v1.5.1 deployment backfill (216 captured + 1 verified). Aligns `rebuild-vault-index.py`, `orp_reader.py` (`DEFAULT_STATUS` / `ALL_STATUS`), `vault_vec.py` (`DEFAULT_FALLBACK_STATUS`), `vault_lookup.py`, and §2.6.

**Backwards compatibility**: doc + constant reconciliation only. No schema, log-format, or index-shape migration. The one behavior change: un-statused (and previously unrecognized-status) notes now normalize to `captured` and fall inside the default-included filter, so status-aware consumers (stale-dedup report, backlinks) treat them as live instead of excluding them — this only widens recall, matching the semantic layer's existing default. Re-running the indexer re-stamps `captured` in place of any `unknown`.

## Version 1.7

Changes from 1.6:
- §7.5 (new) **Index Freshness as a Deployment Obligation** — a deployment MUST keep *every* retrieval index it relies on fresh, not just the primary alias index; if the optional semantic layer is enabled, it carries the same obligation. Freshness MUST be observable (per-index entry count / age / drift) and staleness MUST be machine-checkable (a check that can exit non-zero), with concrete staleness defaults (age ≥ 4 days OR drift > 5% of eligible entries). The protocol owns *what must stay healthy + the check*; the deployment owns *when the refresh runs* (the scheduler stays out of the spec). Driven by a production incident: an unmaintained semantic index silently drifted ~1/3 of the vault out-of-index over ~11 days while retrieval kept returning plausible results.
- §5.5 — documented the **first concrete N=3 deployment** (`codex` onboarded as a third symmetric read+log agent). N≥3 needs no quorum/leader at directory-partitioned, low-contention scale; the real footgun is a copied per-agent hook left pointing at the *source* agent's `--agent` id (silent cursor clobbering). The §5.5 cursor body now also documents the **3-field sanity check** (`file_size` + tail SHA-1 + `tail_mtime` → `full_rescan` + `⚠`) that shipped in the reference reader at 1.5.1 but was never reflected in the spec body.
- §5.2 — documented the optional **identity meta trailer** (`‖ meta: session=<sid8> trigger=<cat>:<detail>`) in the entry-format grammar; it shipped in the reference reader at 1.5.1 but the §5.2 body had not described it.
- §1.5.1 / §1.6 changelog corrections — removed the `source` / `last_verified_at` entity-state-machine claims: neither the §1.2 schema body nor the reference impl ever adopted them. The `status` field is real, but its value set is inconsistent across changelog / schema / reader; reconciling that enum is tracked as a fast-follow, not fixed here. *(Resolved in 1.7.1: missing/unrecognized `status` normalizes to `captured` across all layers; `unknown` removed.)*

**Backwards compatibility**: v1.7 is documentation-sync plus one new deployment obligation (index freshness). No schema or log-format migration is required. Alias-only deployments remain compliant; the freshness obligation only adds a second index's worth of monitoring when the optional semantic layer is enabled.

## Version 1.6

Changes from 1.5.1:
- §3.6 (new) **Semantic Layer (optional)** — `vault_vec.py` adds OpenAI-embedding-based vector retrieval as a second ranker. ~$0.023 one-time to embed a ~800-entry vault; ~$0.000001 per query; index is a local `.npy` + `.meta.json` pair. Alias remains the primary ranker; vec is the safety net for queries where keyword substring fails. Vec is rank-only — it cannot generate content, only retrieve. Optional: alias-only deployments stay protocol-compliant.
- §3.7 (new) **Rank Fusion (RRF)** — when both layers run, `vault_lookup.py` fuses them via Reciprocal Rank Fusion (k=60, Cormack 2009). Same-doc hits across rankers add naturally → cross-source agreement boosts top results without thresholds. 5-day production telemetry on N=2 agents (32 lookups): alias hit 94%, vec hit 100%, 0 all-miss.
- §3.8 (new) **Backlinks Query** — `vault_lookup.py backlinks <target>` stateless cross-namespace wikilink reverse-lookup (no third index). Mixed resolver: accepts basename (`foo`) or vault-relative full path (`wiki/.../foo.md`); recognizes `[[X]]` / `[[X|display]]` / `[[X#heading]]` / `[[X^block]]`. Ambiguous basenames warn. Skips `archived` / `stale` referrers by default. ~0.1s on ~800-entry vault.
- §3.9 (new) **Embedding Model Versioning** — `vault-vec.about.json` sidecar records `model` / `dim` / `vec_count` / `created_at`. Load-time mismatch detection: **hard** (dim differs) exits with code 2 (fail-closed — prevents silently mixing incompatible spaces); **soft** (same dim, different model name) warns and continues. Closes the "embedding drift after CLI/model rename" failure mode.
- §3.10 (new) **Stale/Duplicate Report** — `orp_reader.py stale-dedup-report` weekly cron scans entities, flags ones older than `--stale-days` and groups by lowercased title / H1 to surface duplicate candidates. Observational only — outputs markdown to `.orp/reports/stale-dedup-<date>.md`; user decides cleanup. Default Tier-2 hygiene without full memory-consolidation pipeline.
- §1.2 schema — `status` is spec-level for retrieval filtering; the default filter is `status ∈ {captured, candidate, verified, retrievable}`, with `stale` and `archived` requiring explicit opt-in. *(1.7 correction: the `source` / `last_verified_at` fields originally listed here were never adopted into the §1.2 schema body or the reference impl — claim removed.)*
- §11 utilities — adds `vault_vec.py` (semantic layer + embedding versioning) and `vault_lookup.py` (unified orchestrator: alias + vec + RRF + backlinks + gap log). `orp_reader.py` adds `stale-dedup-report` subcommand.

**Backwards compatibility**: Pure alias-only ORP deployments (1.5/1.5.1) remain spec-compliant. Semantic + RRF are opt-in upgrades. Existing vault indexes and log files do not need migration.

## Version 1.5.1

Changes from 1.5:
- §5.2 — collaboration-log entries gain optional **identity meta trailer** of form `‖ meta: session=<sid8> trigger=<cat>:<detail>`. Without it, multi-agent logs were attributable to the agent (header `[<agent_id>]`) but not to the specific session or trigger that caused the write — making "why did X get logged?" answerable only by manual git-blame. Four-enum action taxonomy (`write` / `note` / `done` / `decision`) enforced via lint — matching the closed list in §5.2, ending the prior free-form-string drift. (`intent` / `issue` were considered but never adopted into the lint or reference impl; `intent` was tied to the edit-intent soft protocol, later rolled back. The closed list stays four.)
- §5.5 — per-agent cursor extended with a **3-field sanity check** before incremental read: `file_size` + tail SHA-1 (last 256 bytes) + `mtime`. Any mismatch triggers a `full_rescan` from byte 0 and prepends a `⚠ entry` line to the digest so the agent knows the cursor was lost. Pre-fix, log truncation or restore-from-backup would silently rewind cursor reads without warning.
- §1.2 — schema gains a lifecycle **`status`** field used by the default retrieval filter (which excludes `stale` and `archived`), reducing the 1.5 ambiguity where agent-generated stubs were indistinguishable from human-written canonical notes. *(1.7 correction: an earlier draft of this entry also listed `source` / `last_verified_at` fields; those were never adopted into the §1.2 schema body or the reference impl. 1.7.1: the canonical `status` enum is the six §1.2 values `{captured, candidate, verified, retrievable, stale, archived}`; the default retrieval filter includes the four live values and excludes `{stale, archived}`.)*
- §11 — `orp_reader.py` adds `match` (alias substring lookup) + `log` enforcement of the closed four-enum action vocabulary (§5.2). 217-entity backfill verified during deployment (216 captured + 1 verified).

## Version 1.5

Changes from 1.4.1:
- §5.6 (new) Auto-log via PostToolUse + Stop hooks — addresses the v1.4 dogfood finding that CC writes vault files but rarely calls `orp_reader.py log` afterwards (0 of ~41 wiki/ changes logged across 7 days; Hermes meanwhile logged 47 entries). Prompt-only enforcement (the §5.2 MUST) failed empirically. v1.5 adds a two-hook mechanism that mechanically captures vault edits and flushes one summary log entry per turn. Optional — agents that already log reliably (like Hermes) don't need it.
- README repositioned around multi-agent coordination — three independent reviews (Claude agent + Codex + Gemini) flagged that the v1.4 hero ("give your AI agent long-term memory") pattern-matched to the "second-brain category" and made readers misclassify ORP in 5 seconds. v1.5 hero leads with the coordination protocol framing and includes an explicit disqualifier for solo-agent use cases.

## Version 1.4.1

Changes from 1.4:
- §5.5 cursor advance fixed — when a regular-mode digest call hits the cap (10 entries shown, more pending), the cursor now lands at the byte offset of the first unshown entry, not at EOF. Pre-fix, every entry past the cap was permanently dropped from that agent's digest stream. Surfaced via dogfood telemetry (Hermes hit cap with 40 truncated entries across 7 days = ~6 entries/day silently lost). Bootstrap and `--full` modes are unchanged (still advance to EOF).

## Version 1.4

Changes from 1.3:
- §5.2 entry format upgraded — collaboration-log entries now MUST start with a header line of form `🦅[<agent_id>] <ISO8601> · <action> · <one-line summary>`. Pre-v1.4 entries (date-only headers, mixed `·` / `—` separators) are tolerated as legacy; new entries written through `orp_reader.py log` enforce the v1.4 format. Strict format unlocks reliable byte-offset cursor reads (§5.5).
- §5.5 (new) Session-Start Digest — defines the push side of the protocol. Each agent calls `orp_reader.py digest --agent <id>` at session start; cursor advances by byte offset into `wiki/log.md`. Closes the v1.3 awareness gap where pull-only retrieval missed cross-agent activity that happened between sessions. Best-effort by design — failed digest never blocks agent startup.
- §11 utilities — `orp_reader.py` adds `log` (event-write CLI agents MUST use, replacing hand-edits) and `digest` subcommands.

Changes from 1.2:
- §3.4 (new) Alias Quality Maintenance — substring matching needs alias breadth. Empirical floor: 5+ aliases per entry covering project root / EN-CN / concept terms / abbreviations / version anchors. Without it, RAG hit rate stays low on real queries despite "correct" indexing.
- §3.5 (new) Wikilink Hygiene — cross-scan-dir wikilinks MUST use full paths. Bare `[[name]]` resolution depends on Obsidian's vault-wide name lookup, which non-Obsidian consumers (link checker, alias maintenance, multi-agent collaboration) cannot replicate. Bare links across scan-dir boundaries silently break for those consumers.
- §11 utilities expanded with `expand_aliases.py` (alias maintenance) and `convert_bare_to_fullpath.py` (wikilink migration). Health checker now reports thin alias coverage; link checker now skips fenced code blocks (skill docs and READMEs commonly contain wikilink syntax examples that should not count as references).

Changes from 1.1:
- §1.4 size guidance loosened — the "<20KB" target was a 2024-era cost-of-context anchor and broke once production indexes grew past 30 entries. Replaced with a soft cap that scales with vault size and a recommendation to split cold archives.
- §4.1 trigger classification reframed as a behavioral test (does the user want to recall vs. execute?), removing the English-only keyword list. The previous list assumed monolingual prompts; production use is multilingual.
- §5.2 collaboration-channel rules tightened: writers MUST use append-only operations and MUST NOT replace the file with `write_file`. The previous `flock`-or-PIPE_BUF spec was permissive enough to allow naive read-modify-write to pass review.
- §11 (new) Reference utilities — the repository now ships indexer, reader, health checker, and link checker as the conformance target.

Changes from 1.0 (carried over):
- Top-level `version` field (required).
- `updated` field is ISO-8601 with timezone offset.
- Cross-scan-dir entry_id collisions disambiguated with scan-root basename (§1.3).
- Indexer writes are atomic (tmp + rename).
- Corrupted indexes preserved at `<name>.broken-<ts>` (§4.3).

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
        "status": "<captured|candidate|verified|retrievable|stale|archived>",
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

### 1.4 Size Guidance

The index is read in full on every non-trivial query, so its size directly maps to per-query token cost. A reasonable soft cap is **~50 KB** (about 100 entries with conservative summary lengths). Past that, consider:

- **Tightening `cutoff-days`** so the rolling window stays bounded.
- **Splitting into hot + cold indexes** — keep recent / active notes in `vault-index.json`, archive older ones to `vault-index-archive.json` that the agent reads only on explicit request.
- **Trimming `summary.key_points`** to one line per entry instead of three.

There's no hard ceiling. Modern context windows tolerate larger indexes; the cost question is "tokens per query" not "bytes on disk." Pick a soft cap that fits your retrieval budget and use `orp_health.py --max-size-kb` to enforce it.

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
- Directories: `archived`, `archive`, `log`, `modes`, `tracking`, `task-*`, `.orp` (digest cursor state, §5.5)
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

1. **status**: from `status` frontmatter field, fallback `"captured"` — a note with no (or unrecognized) `status` is `captured` (live and retrievable, never silently dropped) rather than carrying a value outside the §1.2 enum. The fallback MUST be a member of the default-included set so un-statused notes stay retrievable.
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

### 3.4 Alias Quality Maintenance

Substring matching is only as good as the alias coverage. Empirically, an
entry with 2 aliases (typically just `[slug, title-kebab]`) misses most
real queries — the user says "narrative game" and the entry's only English
alias is the file slug. Aim for **5 or more aliases per entry**, covering:

- **Project / topic root tag** — e.g. `if-game`, `cookie-ledger` — so all
  related notes share a hub keyword
- **EN ↔ CN counterpart** — for any non-English vault, every alias should
  exist in both languages
- **Concept names** — domain terms that appear in queries but not the title
  (e.g. `narrative game` for an interactive-fiction project)
- **Common abbreviations** — acronyms the user actually types
- **Date / version anchors** — for time-sensitive entries (e.g.
  `2026-Q2 求职` for a Q2 retrospective)

#### Bulk maintenance: `expand_aliases.py`

When you discover thin coverage across many entries (a single
`orp_reader.py match` returning 0 hits for a query you'd expect),
batch-update via `expand_aliases.py`:

1. Curate a JSON additions file: `{entry_id: [aliases_to_add]}`
2. Dry-run to preview merged diffs
3. Apply — script merges frontmatter + indexer + your additions, dedupes
4. Re-run `rebuild-vault-index.py` to refresh the index

The script preserves existing aliases from both frontmatter AND the
indexer's `ALIAS_MAPS` fallback, since writing frontmatter overrides the
fallback per §3.1 — naive replacement would silently drop hand-curated
data.

#### Frontmatter staleness on file moves

When you move a vault file to a new subdirectory between rebuilds, the
incremental rebuild path detects the new location via `rglob` but, for
content-unchanged files (matching SHA256), the indexer must refresh the
`path` field even when reusing the cached entry. Otherwise downstream
tools that resolve paths from the index (alias maintenance, frontmatter
patchers) get stale paths and fail silently.

### 3.5 Wikilink Hygiene

Bare wikilinks (`[[note-name]]`) resolve via Obsidian's vault-wide
name lookup. This works *inside Obsidian*, but every non-Obsidian
consumer of the vault — the link checker, alias maintenance scripts,
external grep, multi-agent coordination layers, plain-text indexers —
has to either replicate that lookup or treat the bare link as broken.

Cross-scan-dir wikilinks MUST use full paths:

- ❌ `[[note-name]]` (bare; depends on Obsidian's resolver)
- ✅ `[[wiki/projects/note-name]]` (full; resolvable by anything)

Within the same scan-dir, bare wikilinks are tolerated — the resolver
ambiguity is bounded. Across scan-dir boundaries (`wiki/` ↔
`hermes-knowledge/`, or any multi-agent split), full paths are required.

This rule is especially load-bearing for multi-agent setups (§5):
Agent B cannot use Agent A's bare wikilinks reliably without
replicating Obsidian's lookup, and silent breakage degrades trust
in the shared knowledge layer.

#### Migration: `convert_bare_to_fullpath.py`

Existing vaults with bare wikilinks can migrate in bulk:

1. Run the script in `--dry` mode to preview replacements
2. Review ambiguous bare links (multiple stem matches) — these are
   not auto-rewritten and require manual disambiguation
3. Apply, then run `rebuild-vault-index.py` to refresh the index

The script preserves pipe aliases (`[[target|display]]`) and anchors
(`[[target#section]]`), skips fenced code blocks, and skips lines
containing placeholder markers (e.g. `(待写)`, `(TODO)`) so
intentional concept stubs that signal "click to create" affordance
are preserved.

#### Link checker exemption

`orp_link_check.py` skips fenced code blocks during scan: skill docs
and READMEs commonly contain wikilink syntax examples (`[[Note Name]]`,
`![[image.png]]`) that should not count as broken references. Inline
single-backtick references are still scanned — they typically point
to real paths in prose ("see `wiki/projects/foo`").

---

## 4. Auto Context Injection (Agent Behavior)

### 4.1 Trigger Classification

The classifier is a **behavioral test, not a keyword list**. Ask: *does the user want me to recall something, or to execute something?*

**Recall intent → MUST read the index as the first tool call:**
- Questions that lean on past context — what we decided, what we discussed, what we know about X.
- Questions that don't make sense without prior knowledge — "is the migration done?", "what's the latest on...?", "how did we end up handling...?"
- Open-ended retrieval — "tell me about Y", "summarize Z", "what do we have on...?"

**Execute intent → skip the index, act directly:**
- Direct actions on external systems — run X, query Y's price, send a message, restart a service.
- Self-contained transformations — format this JSON, edit this file, generate a regex.
- Novel reasoning that doesn't depend on personal context — "how does TLS handshake work in general."

**When uncertain → bias toward triggering.** The index is small; reading it on a false positive is cheap. The miss case (failing to recall something the user already wrote down) is much more expensive — it forces the user to repeat themselves.

This test is intentionally language-agnostic. An LLM agent can apply it directly without a regex stage; production use is typically multilingual and ad-hoc keyword lists fall behind real prompts.

### 4.2 Matching Algorithm

1. Extract keywords from user query
2. Fuzzy-match against `aliases` arrays in vault-index.json (substring, case-insensitive). A query token T matches an alias A if T is in A or A is in T; longer (more specific) aliases outrank shorter ones.
   - **Precision guard (recall-preserving).** When the query has ≥3 tokens, an entry must match ≥2 *distinct* query tokens to be returned. This collapses single-token substring fan-out (one common token like `in` matching scores of weakly-related entries) while leaving short (<3-token) queries on single-token matching. Rationale: the reference reader (`orp_reader.py match()`) is a recall-oriented candidate generator and the fusion layer (RRF, §6 / `vault_lookup.py`) owns final precision/ranking — but RRF's shallow rank-decay cannot recover from an over-broad alias arm flooding it with 100+ weak candidates, so capping fan-out at the matcher is load-bearing, not a layering shortcut.
3. Hit → `read_file` the matched vault file(s)
4. No hit → check `updated` field age:
   - ≥ 4 days → offer index rebuild
   - < 4 days → ask user for clarification

### 4.3 Error Handling

- Index file missing → ask user to run rebuild script
- JSON parse error → "Index corrupted, rebuild?" — do NOT silently skip. The indexer MUST preserve the broken file at `<index-path>.broken-<ts>` rather than overwriting it on the next rebuild.
- Index stale (≥4 days) → offer rebuild, do NOT auto-rebuild
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

A designated file (`wiki/log.md`) acts as the inter-agent communication log AND the event stream consumed by the session-start digest (§5.5). Both agents append entries; the file is NEVER overwritten.

**Entry format (v1.4 MUST):**

Each new entry starts with a header line:

```
🦅[<agent_id>] <ISO8601-with-tz> · <action> · <one-line summary> [ ‖ meta: session=<sid8> trigger=<cat>:<detail> ]
- optional bullet detail
- optional bullet detail
```

Where:
- `<agent_id>` matches `^[a-z0-9][a-z0-9-]{0,31}$` (e.g. `cc`, `hermes`, `codex`). Agent ids map to filenames (cursor files); they MUST be sanitized.
- `<ISO8601-with-tz>` is a full timestamp with timezone offset, e.g. `2026-05-07T08:30:00+09:00`. Date-only headers from earlier protocol versions are tolerated as legacy but MUST NOT appear in new entries.
- `<action>` is one of `write`, `note`, `done`, `decision`. The list is closed (extending it is a spec change).
- `<one-line summary>` is a single line — newlines stripped — that summarizes the event by itself, without requiring the bullets to make sense.
- `‖ meta: session=<sid8> trigger=<cat>:<detail>` is an **optional identity trailer** appended by `orp_reader.py log` (v1.5.1+). `session=<sid8>` is the first 8 hex chars of `sha256(<run-id>)` — a PII-safe correlation handle answering "which session wrote this"; `trigger=<category>:<detail>` records what caused the write (e.g. `cron:nightly-scrape`). The trailer is absent on legacy and hand-written entries, and the digest parser ignores it (it sits after the summary), so it never affects cursor reads.

**Agents MUST write through `orp_reader.py log`, never by hand-editing `wiki/log.md`.** The CLI enforces format, agent_id sanitization, and the byte-size invariant below. Hand-editing drifts the format and breaks digest cursor parsing — see §11.

**Hard rules for writers:**

- **Append-only.** Never replace the file with `write_file` (or equivalent full-file replacement). New entries are added by appending or prepending, never by re-emitting the entire file.
- **Pre-flight check.** Before any modification, read the current file and record its byte size. After the modification, the byte size MUST be ≥ the pre-flight size plus the entry length. A shrink means something was lost — abort and surface to the user.
- **Concurrency floor.** Either issue a single `write(2)` ≤ `PIPE_BUF` (≈4096 bytes on Linux/macOS) on a file opened with `O_APPEND`, or hold an `flock(LOCK_EX)` for the duration of the write. Naive read-modify-write at file scope is forbidden — it silently loses concurrent writes from the other agent.
- **Failure mode.** If a write would violate the byte-size invariant, the writer MUST stop and ask the user before proceeding. Recovering from a corrupted log is cheap; recovering from a destroyed log is not.

These rules are stricter than naive "atomic append" because the log is the single source of truth for inter-agent state — losing one write can leave the two agents permanently out of sync about what happened.

### 5.3 Cross-Write Protocol

If Agent A needs to write to Agent B's directory:
1. Source page stays in Agent A's directory
2. Agent B's directory gets a wikilink reference (Obsidian `[[path/to/source]]`)
3. Frontmatter must include `author: shared`

### 5.4 Index Coverage

The vault index must cover both agents' content directories. Entries include `author` field for filtering by agent.

### 5.5 Session-Start Digest

The collaboration channel (§5.2) is append-only and ordered, so an agent can know what changed since it last looked by remembering a byte offset and reading from there. Each agent calls `orp_reader.py digest --agent <id>` at session start; the output is injected into the agent's initial context.

**Why this exists.** Pre-v1.4 retrieval was pull-only — an agent only saw vault changes when the user mentioned a keyword that aliased to a file. Cross-agent activity that happened between sessions was invisible by default. The digest closes that gap without polling, embeddings, or a daemon: it reads the existing log file from a per-agent cursor.

**Cursor.** Each agent has a cursor file at `<vault>/.orp/cursors/<agent_id>.json` (the reference reader also accepts the legacy `<vault>/.orp/cursor-<agent_id>.json` path for backward compatibility) with shape `{"log_md_offset": <bytes>, "last_run": "<iso8601>", "file_size": <bytes>, "tail_hash": "<sha1>", "tail_mtime": "<iso8601>"}`. The cursor advances strictly forward and is per-agent — different agents see digests of the same shared log from their own positions. Cursor files live under a dot-directory so they are excluded from index scans (§2.2).

**Cursor sanity check (1.5.1+).** A byte offset is only valid against the exact log it was recorded from. Before an incremental read, the reader compares the cursor's stored `file_size` / `tail_hash` (SHA-1 of the log's trailing 256 bytes) / `tail_mtime` against the log's current values. A mismatch — the log shrank, or its tail no longer hashes to the recorded value — means the offset can no longer be trusted (truncation, restore-from-backup, or an external rewrite). The reader then discards the offset, performs a `full_rescan` from byte 0, and prepends a `⚠` line to the digest so the agent knows its cursor was lost rather than silently rewinding. Pre-1.5.1, a truncated or restored log would silently rewind cursor reads with no warning.

**Output.** Header lines (lines matching `^(?:## )?🦅\[`) from the cursor offset to EOF, capped at 10 entries on regular calls and 5 on bootstrap. Bullets and other body content are not emitted — header lines are sized to be self-sufficient (§5.2). Truncation prints `... N more entries; run with --full to see all`. When truncation happens in regular mode, the **cursor advances only to the byte offset of the first unshown entry**, not to EOF — so the truncated entries appear in the next digest call instead of being permanently dropped (v1.4.1 fix). Bootstrap and `--full` modes still advance cursor to EOF.

**Bootstrap.** When no cursor file exists for an agent (first run, or after corruption rotation), the digest prints the LAST `BOOTSTRAP_TAIL` (5) header lines from the full log, then sets the cursor to current EOF. This avoids dumping the full history into a new agent's first context.

**Failure semantics — best-effort.** A digest failure MUST NOT block agent startup:

- Vault unavailable → silent exit 0.
- `wiki/log.md` missing → silent exit 0.
- Corrupt cursor file → rename to `cursor-<id>.broken-<ts>.json`, fall back to bootstrap, exit 0. (Mirrors §4.3 corrupted-index handling.)
- Invalid agent id → exit 2 with stderr message (this is a wiring bug, not a runtime fault — should fail loudly).

**Concurrency.** Cursor reads and writes are serialized via `flock(LOCK_EX)` on a per-agent lock file (`cursor-<id>.lock`). Two simultaneous starts of the same agent will not stomp each other's cursor.

**Cursor advance discipline.** The cursor is written to disk only AFTER the digest output has been printed and stdout flushed. A failure between flush and cursor-write is rare but possible (process killed between syscalls); the residual data-loss window is bounded by the harness's stdout-capture window. Agents accept this trade-off — the alternative (two-phase ack) more than doubles the protocol surface for a vanishingly small failure rate.

**Why vault mtime is NOT used for change detection.** Vault file `mtime` is unreliable (iCloud sync touches, git checkout rewrites, bulk renames) — see §2.4. The digest does not scan vault mtimes to decide what changed; it reads only the append-only log, where byte offset is a deterministic and monotonic cursor. (This is distinct from the cursor's `tail_mtime` sanity field above, which records the *log file's* mtime purely as one cheap tamper/restore signal — never as a content-change trigger.)

**Multi-agent forward compatibility.** `--agent <id>` accepts any agent id matching the regex above. Adding a third or Nth agent is three steps: pick an id, wire its session-start hook to call `digest --agent <id>`, and ensure it writes log entries through `orp_reader.py log`. No structural vault changes needed. This does not address symmetric-broadcast spam at high agent counts (everyone sees everything) — that is a known v1.4 limitation. Author-aware filtering and per-agent priority are deferred until concrete N≥3 deployments justify them.

**First concrete N=3 deployment (`codex`, 2026-06).** A third agent — `codex`, OpenAI's CLI used standalone by the operator — was onboarded as a symmetric **read + log** participant: it runs `digest --agent codex` at session start (its own cursor), recalls through the retrieval stack, and writes via `orp_reader.py log --agent codex`. The open N≥3 question (does a third agent require quorum/leader coordination?) resolves to **no** at directory-partitioned, low-contention scale: per-agent cursors, directory partitioning (§5.1), and the append-only concurrency floor (§5.2) already let N agents coexist without consensus machinery. Entity authoring stayed with the two namespace-owning agents (CC → `wiki/`, Hermes → `hermes-knowledge/`); `codex` contributes knowledge as log entries rather than owning a namespace, so partitioning is unaffected and no quorum is introduced. **Onboarding hazard (observed, worth flagging for adopters):** the new agent's hooks were copied verbatim from an existing agent and left every `--agent` id pointing at the *source* agent. The failure was silent — the new agent advanced the source agent's digest cursor (cursor clobbering, so the source agent began missing entries) and auto-logged under the wrong id. A per-agent hook copy MUST have its `--agent <id>` rewritten end to end (session-start digest, PostToolUse stager, Stop flusher). Rewriting the id is necessary but not sufficient: the source agent's cursor was already advanced past entries it never showed, so it MUST also be reset (re-bootstrapped) once the id is fixed — otherwise it stays silently ahead of its true read position and keeps skipping entries even after the id is correct. A mismatched id — not the absence of quorum — is the real N≥3 footgun.

### 5.6 Auto-log via Hooks (v1.5+)

§5.2 specifies that agents MUST write log entries through `orp_reader.py log`, never by hand-editing `wiki/log.md`. Dogfood data from v1.4 showed this prompt-level MUST does not hold empirically for chat-oriented agents — Claude Code logged 0 entries across ~41 vault writes in one week, while Hermes (a longer-lived background agent) logged 47 across the same window. Prompt-only enforcement is not enough; the protocol needs an optional mechanical fallback.

§5.6 specifies a two-hook coalescing mechanism that agents MAY implement to capture vault writes deterministically:

**Stager (PostToolUse hook).** Fires after the agent performs an edit on a vault file (e.g. `Edit`, `Write`, `MultiEdit`). If the target path is under the vault root, isn't `wiki/log.md` itself, isn't under `.orp/` or `.obsidian/`, and is a markdown file, the stager appends the vault-relative path to a per-session pending file at `<vault>/.orp/pending/<agent_id>-<session_id>.txt`. The stager itself does NOT call `orp_reader.py log` — it only stages.

**Flusher (Stop hook).** Fires when the agent finishes its turn. Reads the per-session pending file, dedupes paths in-order, and writes ONE summary log entry via `orp_reader.py log --action note` with message format `auto: edited <path>, <path>, ...`. The pending file is cleared atomically after read. If the file list is longer than a small cap (5 by default), the message truncates with a `(+N more)` suffix to keep the entry readable.

**Why one entry per turn, not one per edit:**
- A single Claude Code turn often Edits the same file multiple times (write → edit → edit). Per-edit logging would spam `wiki/log.md` with mechanical "wrote X" entries and drown the actual signal.
- Per-turn dedup gives Hermes (or any other agent) a single semantic event to read in its next digest: "CC touched these N files this turn".
- The `auto:` prefix in the message lets humans and other agents filter visually.

**Why `note` and not `write`:**
- The hook can't know whether the underlying edit was a meaningful state change or a trivial whitespace fix. `note` is the honest action — "I touched these files", not "I wrote them".
- Agents can still call `orp_reader.py log --action write/done/decision` manually for semantically richer entries. Both kinds appear in `wiki/log.md`; both surface in the next digest.

**Failure semantics — best-effort.** Like §5.5, hook failures MUST NOT block the agent:
- Stager exception → silent exit 0 (no pending file written; flusher has nothing to flush).
- Flusher exception → pending file already cleared, log entry not written. Lossy in the rare race, but bounded.
- `orp_reader.py` missing / vault path wrong → silent exit 0. Hook scripts read `ORP_VAULT_PATH` and `ORP_READER_PATH` env vars to keep the deployment paths configurable.

**Reference implementation.** `examples/orp-vault-stage.py` and `examples/orp-vault-flush.py` (stdlib only, ~80 lines each). Wired into Claude Code via `~/.claude/settings.json` under `PostToolUse` (matcher `Edit|Write|MultiEdit`) and `Stop` hook events with `timeout: 5` (seconds, per Claude Code hook spec). Agents other than CC can implement equivalent hooks against their own tool-use events; the protocol surface is the pending-file format and the per-turn flush discipline, not the specific hook framework.

**Out of scope for §5.6.** This mechanism does NOT detect "did the agent semantically engage with digest content" (a v1.4 hypothesis called 坑1 that was dropped after 5 days of dogfood produced no measurable evidence). It does NOT detect cross-instance cursor races (deferred). It is purely a compliance mechanism for the §5.2 write-via-CLI rule.

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

## 7. Incremental Rebuild & Index Freshness

### 7.1 Core Principle

Content hash comparison drives incremental updates. Only re-extract frontmatter and summary when SHA256 changes.

### 7.2 States

| Old exists? | Hash matches? | Action |
|-------------|--------------|--------|
| Yes | Yes | Reuse old entry (aliases, summary, all metadata) |
| Yes | No | Full re-extraction from file |
| No | — | New entry, full extraction |

### 7.3 Change Count

Rebuild output MUST report changed entry count for monitoring. Zero changes = healthy incremental path.

### 7.4 Cutoff Window

The indexer applies a rolling age cutoff (default 90 days, configurable) to bound the working set. The cutoff MUST NOT drop a file that already has an entry in the previous index — once indexed, an entry stays until the file is removed from the vault or matches an exclusion rule. Otherwise hand-curated aliases for older notes silently disappear after the cutoff window.

### 7.5 Index Freshness as a Deployment Obligation

This obligation is cross-cutting: it governs *every* index a deployment relies on, not just the incremental-rebuild path above. Retrieval quality degrades silently when an index falls behind the vault, so a deployment **MUST** keep all of its retrieval indexes fresh — not only the primary alias index. If a deployment enables the optional semantic layer, that index carries the **same** freshness obligation as the alias index. An unmaintained secondary index is the most dangerous kind: queries still return *results*, so the degradation is invisible until measured.

> Reference deployment, 2026-06: the alias index had a daily rebuild while the optional semantic index had none. It drifted ~1/3 of vault content out-of-index across ~11 days before anyone noticed — precisely because retrieval kept returning plausible results. The fix was not a new feature but closing the freshness asymmetry: a sibling refresh on the same schedule, plus a staleness check with enough teeth to surface drift.

**Freshness signal.** "Fresh" MUST be observable, not assumed. An implementation MUST expose, per index: entry count, age since last build, and drift. Drift is *eligible-but-missing* content, and each layer's drift MUST be measured against the same eligibility filter (§2.2 / §2.3) that decides what *should* be indexed — on-disk files that qualify for indexing, minus the entries that layer actually holds — never the layer measured against its own last snapshot. (A layer counting only its own snapshot can pass a drift check while silently dropping content the alias layer would have caught — exactly the incident above.) Staleness has concrete defaults: **age ≥ 4 days OR drift > 5% of eligible entries** means stale (defaults; configurable, and aligned with the §4.2 / §4.3 / §11.3 4-day staleness window). The §7.3 change-count is one input to the alias layer's signal — it surfaces churn between rebuilds, not staleness — so a complete signal pairs it with the index's age and drift; §11.1 (`orp_health.py`) is the reference freshness check for the alias layer, and any additional layer needs its own equivalent.

**Staleness MUST be machine-checkable.** Eyeballing freshness does not satisfy this obligation — the production incident above happened precisely because nobody was looking. A compliant deployment MUST be able to check every layer's freshness signal programmatically and get a non-zero / fail result when any layer is stale, so the check can gate CI or block agent startup. A deployment SHOULD roll all layers into a single command for convenience. The reference implementation ships `orp_health.py` (§11.1) as the alias-layer check (`--strict` already exits non-zero on staleness) and `vault_vec.py status --strict` as the semantic-layer equivalent (same contract: non-zero exit when age ≥ 4 days OR eligible-but-missing drift > 5%); a multi-layer rollup is a deployment convenience and, per §9 / §11, the specific tool is a reference utility, not the protocol contract — the contract is that staleness is *observable and machine-checkable*, however it is implemented.

**Boundary — what ORP owns vs what the deployment owns.** ORP specifies the freshness *requirement* and the *signal + check* a compliant implementation must be able to produce. ORP does **not** specify the *scheduler*. When and how the refresh runs — cron, launchd, CI job, agent-internal timer, or staleness-prompt (§11.3) — is a deployment choice and MUST NOT be baked into the protocol; doing so over-fits the protocol to one host's infrastructure. Rule of thumb: **the protocol owns "what must stay healthy + the check"; the deployment owns "when the refresh runs."**

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

The repository ships a single-file, stdlib-only reference implementation. Two scripts cover the protocol's normative behavior; two more cover operations against an existing index.

**Protocol-defining (you reimplement these in any compliant indexer/reader):**

- **`rebuild-vault-index.py`** — the indexer side. Implements §1 (vault index), §2 (indexing algorithm), §3 (alias resolution), §7 (incremental rebuild).
- **`orp_reader.py`** — the reader side. Implements §4.2 (matching algorithm), §4.3 (error handling), staleness detection (Rule 4), §3.2 (scalar aliases tolerance). Library (`from orp_reader import VaultIndex`) or CLI.

**Operational (not part of the protocol contract — see §11):**

- **`orp_health.py`** — schema and freshness validator.
- **`orp_link_check.py`** — wikilink integrity scanner for §6.

Implementations in other languages are welcome — the four Python scripts are the conformance target for the protocol-defining pair.

---

## 10. Adoption Checklist

To adopt ORP for your agent:

- [ ] Configure vault path and scan directories
- [ ] Define exclusion patterns for your vault structure
- [ ] Set up auto context injection rules in your agent's system prompt
- [ ] Run initial index build
- [ ] Set up rebuild trigger (see §11 — cron, agent-internal scheduler, coupled into another job, or staleness-prompt)
- [ ] Pin ORP-related skills from curator/auto-cleanup
- [ ] Verify: agent reads vault-index.json on recall-intent queries
- [ ] Verify: incremental rebuild shows 0 changes when vault is unchanged
- [ ] Verify: `orp_health.py` exits 0 against the freshly-built index
- [ ] If using the optional semantic layer: set up its refresh trigger too (§7.5), and verify staleness is machine-checkable — artificially stale the semantic index and confirm your freshness check exits non-zero (mirroring the `orp_health.py exits 0` line above for the alias layer). An unmaintained secondary index degrades retrieval invisibly, so "monitored" only counts if a check can actually fail.

---

## 11. Reference Utilities

These ship with the reference implementation. They are **not part of the protocol contract** — a compliant indexer + reader satisfies the spec — but they cover operational concerns every adopter eventually hits.

### 11.1 Health checking — `orp_health.py`

Validates an index against the v1.1+ schema, verifies it isn't stale, surfaces orphan paths and short aliases that the reader's noise filter would drop. Distinguishes hard failures (missing required fields, stale beyond threshold, unparseable JSON) from soft warnings (orphans, oversized index). `--strict` promotes warnings to non-zero exit for use as a CI gate.

Recommended invocation points:

- After every rebuild — verify the new index is well-formed before agents start reading it.
- Before adopting a new agent skill — confirm the existing index is fresh enough to be useful.
- In CI — fail the pipeline if a PR breaks the index shape or makes it stale.

### 11.2 Link integrity — `orp_link_check.py`

Scans a directory of markdown files for `[[wikilink]]` and inline-code path references, resolves each against a vault root, reports dead links / live links / orphans. This is the conformance check for §6 (Skill ↔ Vault auto-expansion): if a skill file references a vault note that no longer exists, agents auto-loading the wikilink will fail silently. Recognizes Obsidian template variables (`{date}`, `{timestamp}`) and directory references — does not flag them as dead.

Resolution is two-pass to match Obsidian's own behavior:

1. **Path-style** — `[[wiki/projects/note]]` resolves to `vault/wiki/projects/note.md`.
2. **Bare-name fallback** — `[[note]]` (no path component) is looked up against an in-vault filename index, mirroring how Obsidian itself resolves bare wikilinks. Without this fallback, every bare wikilink in a vault with a non-flat directory structure would be reported as dead, drowning real issues in noise.

Recommended invocation points:

- After moving or renaming a vault note — catch which skill files now point at thin air.
- After editing an agent skill — confirm any new wikilinks resolve.
- In CI on the skills repo — block PRs that introduce dead references.

### 11.3 Triggering rebuilds

The protocol doesn't mandate a specific trigger mechanism. Four are routinely useful, and a working setup typically uses two or three of them:

- **Scheduled (cron / launchd / systemd timer)** — daily or hourly off-peak rebuild. Set-and-forget; the staleness window is bounded by the schedule interval.
- **Agent-internal scheduler** — if your agent has a native scheduled-task system, register the rebuild script there. Survives across agent restarts; doesn't require separate cron infrastructure.
- **Coupled to an upstream job** — wrap the rebuild into another scheduled task that already produces vault content (e.g., a daily job that scrapes job-board listings and writes them into the vault should rebuild the index before completing).
- **Staleness-prompt** — agent reads `updated`, sees ≥4 days, asks the user to rebuild. Effective fallback when the scheduled trigger fails silently.

A robust setup uses a scheduled trigger as the primary path and the staleness-prompt as the safety net.

### 11.4 Co-located ancillary indexes

Adopters frequently maintain a second index alongside `vault-index.json` for cross-cutting concerns the protocol intentionally doesn't cover:

- **`vault-connectivity.json`** — output of `orp_link_check.py --json`, lists which skills reference which vault files. Lets agents reason about "which skill loads will pull this note as expansion."

These ancillary indexes are out of protocol scope but interoperate cleanly because they sit beside `vault-index.json` and answer adjacent questions.

### 11.5 Session-start digest — `orp_reader.py digest` / `log`

Two subcommands implement the §5.5 push side of the protocol:

- **`orp_reader.py log --agent <id> --action <write|note|done|decision> "<message>"`** — append a v1.4-format event to `wiki/log.md`. Enforces agent-id sanitization, ISO-8601 timestamping, the §5.2 byte-size invariant, and `flock(LOCK_EX)` during write. Agents MUST use this instead of hand-editing the log; hand-edits drift the format and break cursor parsing.
- **`orp_reader.py digest --agent <id>`** — print log header lines appended since this agent's cursor, advance the cursor, and exit. Best-effort: vault unavailable / log missing → silent exit 0 so a SessionStart hook never blocks startup. Flags: `--bootstrap` (ignore cursor, last 5 entries), `--full` (no cap), `--peek` (read without advancing cursor; useful for debugging).

Recommended invocation points:

- **`digest`** — fire from each agent's session-start hook (e.g. Claude Code `SessionStart` hook in `~/.claude/settings.json`, Hermes startup flow). Output is small (≤10 header lines) and structured for system-prompt injection.
- **`log`** — call after any vault write or coordination decision worth surfacing to the other agent. Treat it as the agent-side equivalent of a git commit message.

### 11.6 Auto-log hooks — `examples/orp-vault-stage.py` / `orp-vault-flush.py`

Reference implementation of the §5.6 PostToolUse + Stop hook pair. Stager records vault md writes to a per-session pending file; flusher reads pending at turn end and writes one summary log entry via `orp_reader.py log`. Stdlib only, ~80 lines each.

Wiring (Claude Code) — add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "python3 /path/to/orp-vault-stage.py",
        "timeout": 5
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python3 /path/to/orp-vault-flush.py",
        "timeout": 5
      }]
    }]
  }
}
```

Configurable via env vars `ORP_VAULT_PATH` (default `~/Documents/Obsidian Vault`) and `ORP_READER_PATH` (default `~/.hermes/scripts/orp_reader.py`).

---

## Appendix: Design Philosophy

1. **Index is machine-readable, not LLM-reasoned** — JSON lookup, no prompt-time inference cost on the index itself
2. **Frontmatter drives content** — the human controls summaries and aliases
3. **Path-based exclusion** — deterministic, not dependent on frontmatter discipline
4. **Hash-based incremental** — immune to filesystem time quirks
5. **Aliases are curated, not generated** — quality over quantity in search matching
6. **Two agents, one vault** — separate write directories, shared read
7. **Bidirectional, not read-only** — agents both read the vault and write back to it on triggers; the index is the protocol surface, not the entire interaction
