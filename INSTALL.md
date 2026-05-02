# Installation Guide — Obsidian RAG Protocol

Get your AI agent reading your Obsidian vault in 3 steps.

---

## Prerequisites

- **Python 3.8+** — the reference implementation uses only Python standard library (no pip install needed)
- **macOS or Linux** — tested on macOS Sequoia, should work on any Unix-like system
- **Obsidian vault** — a local folder with `.md` files (iCloud-synced vaults work fine)
- **An AI agent with filesystem access** — Hermes Agent, Claude Code, or any agent that can `read_file`

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

## Setting Up Automatic Rebuilds

The index needs periodic rebuilding to pick up new and changed notes.

### Cron (macOS/Linux)

```bash
# Edit crontab
crontab -e

# Add this line to rebuild daily at 9 AM:
0 9 * * * python3 /path/to/obsidian-rag-protocol/rebuild-vault-index.py \
  --vault ~/Documents/MyObsidianVault \
  --output ~/.hermes/vault-index.json \
  --scan wiki/projects:cc wiki/career:cc hermes-knowledge/:hermes
```

### Launchd (macOS)

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
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.orp.rebuild.plist
```

---

## Agent Integration

Once the index is built and auto-rebuilding, configure your agent to use it.

### Hermes Agent

Add these rules to your system prompt (SOUL.md or equivalent):

```
## Obsidian RAG Protocol

When the user asks a non-trivial question (contains "why", "how", "analyze",
"research", "review", "before", "what is"), your first tool call MUST be:

  read_file(~/.hermes/vault-index.json)

Then:
1. Extract keywords from the user's question
2. Match against `aliases` arrays in the index (fuzzy substring, case-insensitive)
3. If HIT → read_file the matched vault file(s)
4. If MISS → check `updated` field. If ≥4 days old, offer to rebuild the index
5. If the index file is corrupted (JSON parse error) → ask user to rebuild

Skip the index for trivial commands ("run script", "check price", "send message").
```

### Claude Code

Add to your `CLAUDE.md`:

```
## Vault Context

Before answering any non-trivial question, read ~/.hermes/vault-index.json and
match the user's keywords against the aliases field. If a match is found, read
the referenced .md file and use it as context.
```

### Any Other Agent

The protocol is agent-agnostic. All you need:
1. **A way to read files** — `read_file`, `cat`, or equivalent
2. **A system prompt rule** — "first tool call = read vault-index.json on non-trivial queries"
3. **A cron job** — rebuild the index daily

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
```

Stdlib only. Drop it next to your agent's tooling and wire the match output into whatever read-file call your agent uses.

---

## Verifying It Works

### 1. Check the index is updating

After your cron runs, the `updated` field in `vault-index.json` should show today's date:

```bash
python3 -c "import json; print(json.load(open('/Users/vincentwen/.hermes/vault-index.json'))['updated'])"
```

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
