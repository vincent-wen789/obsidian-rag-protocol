# Installation Guide — Obsidian RAG Protocol

Get your AI agent reading your Obsidian vault in 3 steps.

---

## Prerequisites

- **Python 3.8+** — core ORP (alias indexer + reader + cursor + log) uses only the Python standard library; no `pip install` needed
- **macOS or Linux** — tested on macOS Sequoia, should work on any Unix-like system
- **Obsidian vault** — a local folder with `.md` files (iCloud-synced vaults work fine)
- **An AI agent with filesystem access** — Hermes Agent, Claude Code, or any agent that can `read_file`

**Optional (v1.6 semantic-fallback layer only)**: if you want the optional `vault_vec.py` semantic retrieval layer + RRF fusion via `vault_lookup.py`:
- `pip install openai tiktoken` — `openai` for `text-embedding-3-small` API calls, `tiktoken` for token counting before truncation
- An `OPENAI_API_KEY` in your environment (or `~/.hermes/.env` — if you use a key file, restrict it to owner-only: `chmod 600 ~/.hermes/.env`)
- ~$0.023 one-time to embed a ~800-entry vault; ~$0.000001 per query thereafter

Alias-only deployments (no vec layer) do not need either of these.

---

## Quick Start (3 Steps)

### 1. Clone and test

```bash
git clone https://github.com/wjameswen888/obsidian-rag-protocol.git
cd obsidian-rag-protocol
```

### 2. Run your first index build

```bash
python3 rebuild-vault-index.py \
  --vault ~/Documents/MyObsidianVault \
  --output ~/.hermes/vault-index.json \
  --scan wiki/projects wiki/career hermes-knowledge/
```

You should see:
```
✅ vault-index.json rebuilt: 12 entries (12 changed)
```

### 3. Verify the output

```bash
cat ~/.hermes/vault-index.json | python3 -m json.tool | head -40
```

You'll see a JSON object with `entries` — each containing `path`, `title`, `aliases`, and a `_content_hash`.

---

## Configuration

### Scan Directories

The `--scan` argument tells the indexer which subdirectories of your vault to scan. Format:

```bash
--scan DIR:AUTHOR DIR:AUTHOR ...
```

- `DIR` — path relative to your vault root
- `AUTHOR` — tag for who maintains this directory (`cc`, `hermes`, `vincent`, or `shared`)

**Example:**
```bash
--scan projects:cc career:cc my-agent-knowledge:hermes
```

**Why specify author?** If you use the bidirectional protocol (two agents sharing one vault), the `author` field helps each agent know which directory it's allowed to write to. If you only use one agent, just pick any label.

### Excluding Files

By default, the indexer skips:
- Directories named `archived`, `archive`, `log`, `modes`, `tracking`, or starting with `task-`
- Files matching `plan-*`, `*-progress`, `*-data-YYYY-MM`
- `index.md` and `README.md`

To exclude an individual note from the index, add this to its YAML frontmatter:
```yaml
---
rag_exclude: true
---
```

### Cutoff Days

By default, files older than 90 days are skipped. Change this with:
```bash
--cutoff-days 180   # index files up to 6 months old
```

### Hand-curated Aliases

For better search matching, you can provide a JSON file mapping entry IDs to custom alias lists:

```json
{
  "my-project": ["project", "my-project", "the thing I built"],
  "meeting-notes": ["meetings", "team-sync"]
}
```

Pass it with:
```bash
--alias-maps ~/my-alias-maps.json
```

---

## Triggering Rebuilds

The index gets stale unless something rebuilds it. The protocol doesn't mandate a single mechanism — pick one or two from below. Most working setups use a scheduled trigger as the primary path and the agent's staleness-prompt as a safety net.

### Path 1: System scheduler (cron / launchd / systemd timer)

The default. Set-and-forget; runs whether you're using the agent or not.

**Cron (macOS / Linux)**

```bash
# Add to your crontab (crontab -e):
0 9 * * * python3 /path/to/obsidian-rag-protocol/rebuild-vault-index.py \
  --vault ~/Documents/MyObsidianVault \
  --output ~/.hermes/vault-index.json \
  --scan wiki/projects:cc wiki/career:cc hermes-knowledge/:hermes \
  >> ~/.hermes/orp-rebuild.log 2>&1
```

The output redirect matters — `cron` swallows stderr by default and a corrupted-index warning would otherwise vanish.

**launchd (macOS)**

Create `~/Library/LaunchAgents/com.orp.rebuild.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.orp.rebuild</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/rebuild-vault-index.py</string>
        <string>--vault</string>
        <string>/Users/you/Documents/MyObsidianVault</string>
        <string>--output</string>
        <string>/Users/you/.hermes/vault-index.json</string>
        <string>--scan</string>
        <string>wiki/projects:cc</string>
        <string>wiki/career:cc</string>
        <string>hermes-knowledge/:hermes</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/you/.hermes/orp-rebuild.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/you/.hermes/orp-rebuild.log</string>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.orp.rebuild.plist
```

### Path 2: Agent-internal scheduler

If your agent has a native scheduled-task system (Hermes Agent does, with cron-style task IDs), register the rebuild there instead of the OS-level scheduler. Survives across machine reboots in lockstep with the agent itself, and shows up in the same dashboard you check for other scheduled work.

```bash
# Hermes example — register a daily task that runs the rebuild script:
hermes schedule add \
  --cron "0 9 * * *" \
  --command "python3 ~/.hermes/scripts/rebuild-vault-index.py"
```

(Translate to your agent's equivalent — the operative point is "use the scheduler that's already running other tasks for this agent.")

### Path 3: Coupled to an upstream job

If you have other scheduled jobs that write content into the vault — a daily job-board scraper, a weekly market-snapshot generator — append the rebuild to their tail rather than running it independently. Keeps the index fresh-relative-to-the-write that just happened, and avoids stale windows where new vault content exists but the index doesn't see it yet.

```bash
#!/usr/bin/env bash
# Example: job-search-with-rebuild.sh
set -euo pipefail

# 1. Run the upstream job that writes new content to the vault
python3 ~/.hermes/scripts/scan_jobs.py --output ~/Documents/Vault/hermes-knowledge/job-search/

# 2. Rebuild the index immediately so the new content is visible to agents
python3 ~/.hermes/scripts/rebuild-vault-index.py
```

### Path 4: Staleness-prompt fallback

The protocol's Rule 4 (§4.3) — agent reads the index, sees it's ≥4 days old, asks the user. This is the safety net for when one of the scheduled triggers fails silently (machine asleep, cron daemon stopped, agent's task system paused). It's also the natural-language path: when the user says "refresh the index" or "rebuild the RAG," the agent runs the script directly.

No setup required beyond making sure the agent's system prompt includes the staleness check (see [Agent Integration](#agent-integration) below).

### Verifying the trigger

After your trigger path runs at least once:

```bash
# Health check the result
python3 orp_health.py --index ~/.hermes/vault-index.json

# Confirm an incremental rebuild reports 0 changed (no double-extraction)
python3 rebuild-vault-index.py ... --scan ...
# ✅ vault-index.json rebuilt: N entries (0 changed)
```

A non-zero `changed` count when nothing in the vault moved means something is mutating files behind your back (iCloud, git, backup software). Investigate before assuming the indexer is broken.

---

## Agent Integration

Once the index is built and auto-rebuilding, configure your agent to use it.

### Hermes Agent

Add these rules to your system prompt (SOUL.md or equivalent):

```
## Obsidian RAG Protocol

For any user question whose answer depends on personal context — what
we decided, what we discussed, what we know about X — your first tool
call MUST be:

  read_file(~/.hermes/vault-index.json)

Then:
1. Extract keywords from the user's question.
2. Match against `aliases` arrays in the index (substring, case-insensitive).
3. HIT → read_file the matched vault file(s) and use as context.
4. MISS → check `updated`. If ≥4 days old, offer to rebuild the index.
5. JSON parse error → ask the user to rebuild.

Skip the index for direct-action commands (run X, query a price, send a
message) and self-contained transformations (format this, edit that)
that don't depend on personal context.
```

The classifier is a behavioral test, not a keyword list — see protocol §4.1. Recall intent reads the index; execute intent doesn't.

### Claude Code

Add to your `CLAUDE.md`:

```
## Vault Context

Before answering any question that depends on personal context, read
~/.hermes/vault-index.json and match the user's keywords against the
aliases field (substring, case-insensitive). If a match is found, read
the referenced .md file and use it as context.

Skip the index for direct-action commands and self-contained tasks.
```

### Any Other Agent

The protocol is agent-agnostic. All you need:
1. **A way to read files** — `read_file`, `cat`, MCP filesystem server, or equivalent.
2. **A system prompt rule** — "for recall-intent queries, read `vault-index.json` first" (see §4.1 for what counts as recall intent).
3. **A rebuild trigger** — pick one or more from [Triggering Rebuilds](#triggering-rebuilds) above.

#### Reader reference

`orp_reader.py` ships in this repo as a reference implementation of the reader side of the protocol — alias matching (§4.2), staleness check, error handling. Use it as a library:

```python
from orp_reader import VaultIndex
idx = VaultIndex.load("~/.hermes/vault-index.json")
for entry_id, entry, matched_alias in idx.match("Coinbase Japan"):
    print(entry["path"])  # then read_file(entry["path"]) to get full note
```

Or as a CLI for ad-hoc shell glue:

```bash
python3 orp_reader.py status                      # exit 0 / 2 / 3
python3 orp_reader.py match "Coinbase Japan"      # tab-separated entry_id, path, matched alias
python3 orp_reader.py get coinbase-japan-analysis # full entry as JSON
python3 orp_reader.py log --agent cc --action note "msg"  # append v1.4 event to wiki/log.md
python3 orp_reader.py digest --agent cc           # session-start sync (§5.5)
```

Stdlib only. Drop it next to your agent's tooling and wire the match output into whatever read-file call your agent uses.

**Single source of truth tip.** Rather than copying matching rules into your agent's system prompt (where they'll drift over time as the protocol evolves), have the prompt instruct the agent to *call* `orp_reader.py match` and parse the output. Keeps the rules in one place — the reader file — instead of duplicated across every agent's prompt.

---

## Session-Start Digest (v1.4+)

The session-start digest closes the awareness gap that pull-only retrieval left open: when Agent A writes to the vault while Agent B is offline, Agent B never learns about it unless the user happens to mention an aliased keyword. The digest reads `wiki/log.md` from a per-agent byte-offset cursor and prints what's new — see protocol §5.5.

### Wiring it up

**1. Switch agents to write log events through `orp_reader.py log` instead of hand-editing `wiki/log.md`.** This is required for digest cursor parsing to work — hand-edits drift the format. Update each agent's system prompt:

```
When you finish a substantive vault write or coordination decision worth surfacing
to the other agent, append a log event:

  python3 ~/.hermes/scripts/orp_reader.py log \
    --agent <your_id> --action <write|note|done|decision> "<one-line summary>"

Do NOT hand-edit wiki/log.md.
```

**2. Wire each agent's session-start hook to call `digest`.**

For **Claude Code**, add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [{
          "type": "command",
          "command": "python3 ~/.hermes/scripts/orp_reader.py digest --agent cc",
          "timeout": 5
        }]
      }
    ]
  }
}
```

The 5-second timeout is the failure ceiling — if anything goes sideways the hook gets killed and the session starts normally without a digest. Best-effort is the design (§5.5).

For **Hermes Agent**, add to your startup flow (the equivalent of an init hook):

```bash
python3 ~/.hermes/scripts/orp_reader.py digest --agent hermes
```

Inject the stdout into the agent's initial context.

**For other agents**, the same pattern: `digest --agent <your_id>` at session start, output into context.

### Verifying

```bash
# Should print 5 most recent log entries on first run, then create cursor file
python3 ~/.hermes/scripts/orp_reader.py digest --agent cc

# Second call — should be silent (no new activity since first call)
python3 ~/.hermes/scripts/orp_reader.py digest --agent cc

# Append a test event
python3 ~/.hermes/scripts/orp_reader.py log --agent cc --action note "digest verification test"

# Now another agent's first call sees it
python3 ~/.hermes/scripts/orp_reader.py digest --agent hermes
```

### Multi-agent forward compatibility

`--agent <id>` accepts any id matching `^[a-z0-9][a-z0-9-]{0,31}$`. Adding a third agent (Codex, Cursor, your own) is three steps:

1. Pick an id (e.g. `codex`).
2. Have it write log events through `orp_reader.py log --agent codex`.
3. Wire its session-start hook to call `digest --agent codex`.

No structural vault changes needed. Cursor files at `<vault>/.orp/cursor-<id>.json` are per-agent and don't collide.

---

## Auto-log Hooks (v1.5+)

Prompt-level `MUST use orp_reader.py log` doesn't hold empirically — chat-oriented agents often forget. v1.5 ships an optional two-hook mechanism that captures vault writes mechanically and flushes one summary log entry per turn. Protocol details in §5.6.

### Wiring it up (Claude Code)

The repo ships reference implementations as `examples/orp-vault-stage.py` and `examples/orp-vault-flush.py`. Copy them to your hooks directory (or reference them in place), then add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/hooks/orp-vault-stage.py",
        "timeout": 5
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "python3 ~/.claude/hooks/orp-vault-flush.py",
        "timeout": 5
      }]
    }]
  }
}
```

If you already have a `SessionStart` hook for the digest (v1.4 setup), keep it — these are additive.

### Behavior

After deployment:
1. CC edits a vault `.md` file (any of `Edit` / `Write` / `MultiEdit`)
2. The stager appends the relative path to `<vault>/.orp/pending/cc-<session_id>.txt`
3. When CC finishes its turn, the flusher reads the pending file, dedupes, and writes:
   ```
   🦅[cc] 2026-05-12T10:30:00+09:00 · note · auto: edited wiki/projects/foo.md, wiki/career/bar.md
   ```
4. The pending file is cleared

Hermes (or whichever agent runs next) picks this up on its next `digest --agent hermes` call.

### Configuration

Both hook scripts read env vars:
- `ORP_VAULT_PATH` — vault root (default `~/Documents/Obsidian Vault`)
- `ORP_READER_PATH` — path to `orp_reader.py` for the log subcommand (default `~/.hermes/scripts/orp_reader.py`)

Set them in `~/.zshrc` or pass via the hook command if defaults don't match your layout.

### Verifying

After wiring:

```bash
# Trigger CC to write any vault md file in a test session
# Then check log.md:
tail -2 ~/Documents/Vincent\ Obsidian/wiki/log.md

# Should see one fresh `auto:` entry tagged 🦅[cc]
```

If you see no entry: check `~/Documents/Obsidian\ Vault/.orp/pending/` for stuck pending files (the flusher should have cleared them); verify the Stop hook's timeout is in **seconds** (not milliseconds — a v1.4 docs bug fixed in v1.4.1); run the stager/flusher manually with a piped JSON to isolate failures.

### Not for every agent

Hermes-style background agents that already log reliably don't need this mechanism — it's specifically for chat-oriented agents whose "complete the task, exit" reflex skips the post-write log call. Read §5.6 for the design rationale.

---

## Verifying It Works

### 1. Health check

The fastest single check — pass means schema is valid, index isn't stale, no orphan paths:

```bash
python3 orp_health.py --index ~/.hermes/vault-index.json
# OK: N entries, K.K KB, 0 failures, 0 warnings
```

If `--strict`, warnings (orphans, oversized index, short aliases) become non-zero exit. Use that mode in CI gates.

### 2. Check incremental rebuilds are healthy

Run the rebuild script again. If no files changed, you should see `0 changed`:

```bash
python3 rebuild-vault-index.py ... --scan ... --output ...
# ✅ vault-index.json rebuilt: 30 entries (0 changed)
```

A non-zero number every run means your files are being modified externally (iCloud sync, git, etc.) — check file watchers.

### 3. Test with your agent

Ask your agent: "What were we working on with [project name]?"

If the agent reads vault-index.json and references content from your vault — it's working.

---

## Troubleshooting

### "Vault not found"
Check your `--vault` path. Use absolute paths (`~/Documents/Vault` not `../Vault`).

### "0 entries built"
- All scanned directories might be empty
- All files might be older than `--cutoff-days` (default 90)
- Files might match exclusion patterns — check the EXCLUDE_DIRS and EXCLUDE_FILENAME_PATTERNS lists in the script
- Files might have `rag_exclude: true` in frontmatter

### "Every run shows all entries changed" (no incremental)
This usually means files are being modified externally. On macOS, iCloud Drive or Time Machine can change file contents. The SHA256 hash catches real changes — if it's reporting changes, something IS modifying your files. Check:
- iCloud sync status
- Git auto-conversion (CRLF↔LF)
- Backup software touching timestamps

### "Agent doesn't read the index"
- Check your system prompt — the rule must explicitly say "first tool call"
- Some agents (Claude Code) may need the rule in their CLAUDE.md file
- The rule must distinguish "non-trivial" vs "trivial" queries

### "Index file corrupted"
```bash
# Just rebuild it
python3 rebuild-vault-index.py --vault ... --output ... --scan ...
```

---

## Next Steps

- Read the [Protocol Specification](OBSIDIAN-RAG-PROTOCOL.md) for full design details
- Set up [bidirectional multi-agent collaboration](OBSIDIAN-RAG-PROTOCOL.md#5-bidirectional-multi-agent-protocol)
- Learn about [Skill ↔ Vault Auto-Expansion](OBSIDIAN-RAG-PROTOCOL.md#6-skill--vault-auto-expansion-v34)
- Contribute: see [CONTRIBUTING.md](CONTRIBUTING.md)
