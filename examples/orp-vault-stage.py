#!/usr/bin/env python3
"""ORP v1.5 PostToolUse stager hook.

Fires after Edit/Write/MultiEdit. If the tool's `file_path` is inside the
vault (and isn't `wiki/log.md` itself or a dotdir), records the relative
path into a per-session pending file. The Stop hook flusher (`orp-vault-
flush.py`) reads this file later and writes ONE summary log entry per
turn.

Why staging instead of direct auto-log:
- Per-turn coalescing avoids spamming log.md with one entry per Edit
- One semantic summary entry beats 5 mechanical "wrote X" entries

Best-effort by design: any failure exits 0, never blocks CC.

Usage in ~/.claude/settings.json:
  {
    "hooks": {
      "PostToolUse": [{
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{
          "type": "command",
          "command": "python3 /path/to/orp-vault-stage.py",
          "timeout": 5
        }]
      }]
    }
  }

Set ORP_VAULT_PATH env var to override the default vault location.
"""
import json
import os
import pathlib
import sys
import time

DEFAULT_VAULT = "~/Documents/Obsidian Vault"
PENDING_DIR_REL = ".orp/pending"
HOOK_TIMEOUT_GUARD_S = 4

start = time.time()

try:
    inp = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)

tool_name = inp.get("tool_name", "")
if tool_name not in ("Edit", "Write", "MultiEdit"):
    sys.exit(0)

tool_input = inp.get("tool_input", {})
file_path = tool_input.get("file_path", "")
if not file_path:
    # MultiEdit nests edits — grab the first one's file_path
    edits = tool_input.get("edits") or []
    if edits:
        file_path = edits[0].get("file_path", "") if isinstance(edits[0], dict) else ""
if not file_path:
    sys.exit(0)

vault_root = pathlib.Path(os.environ.get("ORP_VAULT_PATH", DEFAULT_VAULT)).expanduser()
# Resolve both ends so a symlink-prefixed path (macOS /tmp → /private/tmp) on
# either side doesn't cause a false miss. realpath handles non-existent paths.
try:
    vault_resolved = os.path.realpath(str(vault_root))
    file_path_resolved = os.path.realpath(file_path)
except OSError:
    sys.exit(0)

if not file_path_resolved.startswith(vault_resolved + "/"):
    sys.exit(0)

rel = file_path_resolved[len(vault_resolved) + 1:]

# Skip the log itself (use `endswith('/log.md')` so `catalog.md` etc don't
# accidentally match — codex review finding from v1.5 plan), dotdirs, and
# anything that isn't markdown.
if rel.endswith("/log.md"):
    sys.exit(0)
if rel.startswith(".orp/") or rel.startswith(".obsidian/"):
    sys.exit(0)
if not rel.endswith(".md"):
    sys.exit(0)

session_id = inp.get("session_id", "unknown")
# Sanitize session_id for filename safety
safe_session = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64] or "unknown"

pending_dir = vault_root / PENDING_DIR_REL
try:
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_file = pending_dir / f"cc-{safe_session}.txt"
    # Append one line per write; flusher dedupes
    with open(pending_file, "a", encoding="utf-8") as f:
        f.write(f"{rel}\n")
except Exception:
    pass  # best-effort

if time.time() - start > HOOK_TIMEOUT_GUARD_S:
    sys.exit(0)

sys.exit(0)
