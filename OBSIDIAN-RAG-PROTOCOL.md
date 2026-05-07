# OBSIDIAN-RAG-PROTOCOL.md

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

A designated file (`wiki/log.md`) acts as the inter-agent communication log AND the event stream consumed by the session-start digest (§5.5). Both agents append entries; the file is NEVER overwritten.

**Entry format (v1.4 MUST):**

Each new entry starts with a header line:

```
🦅[<agent_id>] <ISO8601-with-tz> · <action> · <one-line summary>
- optional bullet detail
- optional bullet detail
```

Where:
- `<agent_id>` matches `^[a-z0-9][a-z0-9-]{0,31}$` (e.g. `cc`, `hermes`, `codex`). Agent ids map to filenames (cursor files); they MUST be sanitized.
- `<ISO8601-with-tz>` is a full timestamp with timezone offset, e.g. `2026-05-07T08:30:00+09:00`. Date-only headers from earlier protocol versions are tolerated as legacy but MUST NOT appear in new entries.
- `<action>` is one of `write`, `note`, `done`, `decision`. The list is closed (extending it is a spec change).
- `<one-line summary>` is a single line — newlines stripped — that summarizes the event by itself, without requiring the bullets to make sense.

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

**Cursor.** Each agent has a cursor file at `<vault>/.orp/cursor-<agent_id>.json` with shape `{"log_md_offset": <bytes>, "last_run": "<iso8601>"}`. The cursor advances strictly forward and is per-agent — different agents see digests of the same shared log from their own positions. Cursor files live under a dot-directory so they are excluded from index scans (§2.2).

**Output.** Header lines (lines matching `^(?:## )?🦅\[`) from the cursor offset to EOF, capped at 10 entries on regular calls and 5 on bootstrap. Bullets and other body content are not emitted — header lines are sized to be self-sufficient (§5.2). Truncation prints `... N more entries; run with --full to see all`.

**Bootstrap.** When no cursor file exists for an agent (first run, or after corruption rotation), the digest prints the LAST `BOOTSTRAP_TAIL` (5) header lines from the full log, then sets the cursor to current EOF. This avoids dumping the full history into a new agent's first context.

**Failure semantics — best-effort.** A digest failure MUST NOT block agent startup:

- Vault unavailable → silent exit 0.
- `wiki/log.md` missing → silent exit 0.
- Corrupt cursor file → rename to `cursor-<id>.broken-<ts>.json`, fall back to bootstrap, exit 0. (Mirrors §4.3 corrupted-index handling.)
- Invalid agent id → exit 2 with stderr message (this is a wiring bug, not a runtime fault — should fail loudly).

**Concurrency.** Cursor reads and writes are serialized via `flock(LOCK_EX)` on a per-agent lock file (`cursor-<id>.lock`). Two simultaneous starts of the same agent will not stomp each other's cursor.

**Cursor advance discipline.** The cursor is written to disk only AFTER the digest output has been printed and stdout flushed. A failure between flush and cursor-write is rare but possible (process killed between syscalls); the residual data-loss window is bounded by the harness's stdout-capture window. Agents accept this trade-off — the alternative (two-phase ack) more than doubles the protocol surface for a vanishingly small failure rate.

**Why mtime is NOT used.** Vault file `mtime` is unreliable (iCloud sync touches, git checkout rewrites, bulk renames) — see §2.4. The digest does not scan vault mtimes; it reads only the append-only log, where byte offset is a deterministic and monotonic cursor.

**Multi-agent forward compatibility.** `--agent <id>` accepts any agent id matching the regex above. Adding a third or Nth agent is three steps: pick an id, wire its session-start hook to call `digest --agent <id>`, and ensure it writes log entries through `orp_reader.py log`. No structural vault changes needed. This does not address symmetric-broadcast spam at high agent counts (everyone sees everything) — that is a known v1.4 limitation. Author-aware filtering and per-agent priority are deferred until concrete N≥3 deployments justify them.

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

---

## Appendix: Design Philosophy

1. **Index is machine-readable, not LLM-reasoned** — JSON lookup, no prompt-time inference cost on the index itself
2. **Frontmatter drives content** — the human controls summaries and aliases
3. **Path-based exclusion** — deterministic, not dependent on frontmatter discipline
4. **Hash-based incremental** — immune to filesystem time quirks
5. **Aliases are curated, not generated** — quality over quantity in search matching
6. **Two agents, one vault** — separate write directories, shared read
7. **Bidirectional, not read-only** — agents both read the vault and write back to it on triggers; the index is the protocol surface, not the entire interaction
