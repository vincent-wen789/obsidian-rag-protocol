#!/usr/bin/env python3
"""ORP v1.5 Stop hook flusher.

Fires when CC's turn ends. Reads the per-session pending file written by
the `orp-vault-stage.py` PostToolUse stager. If non-empty, dedupes paths,
writes ONE `🦅[cc] ... · note · auto: edited X, Y, Z` entry via
`orp_reader.py log`, then clears the pending file.

Design choices:
- ONE entry per turn (not per Edit) — keeps log.md readable
- `action=note` — semantic "I touched these files this turn"
- `auto:` prefix — humans and other agents can filter visually
- Manual `log` calls aren't suppressed: if CC also calls `orp_reader.py
  log` for the same turn (e.g. for a `decision` entry), both entries
  appear — the auto entry lists the files, the manual entry carries
  the semantic message. Trade-off accepted: dual entries beat silent
  drift.

Best-effort by design: any failure exits 0, never blocks CC.

Usage in ~/.claude/settings.json:
  {
    "hooks": {
      "Stop": [{
        "hooks": [{
          "type": "command",
          "command": "python3 /path/to/orp-vault-flush.py",
          "timeout": 5
        }]
      }]
    }
  }

Set ORP_VAULT_PATH env var to override the default vault location, and
ORP_READER_PATH env var to override the orp_reader.py location (default:
~/.hermes/scripts/orp_reader.py).
"""
import json
import os
import pathlib
import subprocess
import sys

DEFAULT_VAULT = "~/Documents/Obsidian Vault"
DEFAULT_READER = "~/.hermes/scripts/orp_reader.py"
PENDING_DIR_REL = ".orp/pending"
MAX_FILES_IN_SUMMARY = 5  # truncate long file lists; rest folded into "+N more"
SUBPROCESS_TIMEOUT_S = 4

try:
    inp = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)

session_id = inp.get("session_id", "unknown")
safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "unknown"

vault_root = pathlib.Path(os.environ.get("ORP_VAULT_PATH", DEFAULT_VAULT)).expanduser()
pending_file = vault_root / PENDING_DIR_REL / f"cc-{safe_session}.txt"

if not pending_file.exists():
    sys.exit(0)

try:
    raw = pending_file.read_text(encoding="utf-8")
    pending_file.unlink()  # clear immediately after read
except Exception:
    sys.exit(0)

# Dedup, preserve order
unique_paths = []
seen = set()
for line in raw.splitlines():
    p = line.strip()
    if p and p not in seen:
        unique_paths.append(p)
        seen.add(p)

if not unique_paths:
    sys.exit(0)

if len(unique_paths) > MAX_FILES_IN_SUMMARY:
    shown = unique_paths[:MAX_FILES_IN_SUMMARY]
    remainder = len(unique_paths) - MAX_FILES_IN_SUMMARY
    msg = f"auto: edited {', '.join(shown)} (+{remainder} more)"
else:
    msg = f"auto: edited {', '.join(unique_paths)}"

reader = pathlib.Path(os.environ.get("ORP_READER_PATH", DEFAULT_READER)).expanduser()
if not reader.exists():
    sys.exit(0)

try:
    subprocess.run(
        ["python3", str(reader), "log",
         "--agent", "cc", "--action", "note",
         "--vault", str(vault_root),
         msg],
        capture_output=True,
        timeout=SUBPROCESS_TIMEOUT_S,
    )
except Exception:
    pass

sys.exit(0)
