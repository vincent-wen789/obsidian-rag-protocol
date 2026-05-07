#!/usr/bin/env python3
"""
orp_reader.py — Reference reader for the Obsidian RAG Protocol.

Loads vault-index.json and answers queries with matched entries.
Implements the reader side of the spec: schema parsing (§1.2),
alias resolution tolerance (§3.2), matching algorithm (§4.2),
error handling (§4.3), staleness detection (Rule 4),
session-start digest (§5.5).

Stdlib only. Single file. Use as a library or CLI.

LIBRARY:
    from orp_reader import VaultIndex, IndexMissing, IndexCorrupted
    idx = VaultIndex.load("~/.hermes/vault-index.json")
    for entry_id, entry, matched_alias in idx.match("Coinbase Japan"):
        print(entry["path"])

CLI:
    python3 orp_reader.py status
    python3 orp_reader.py match "Coinbase Japan"
    python3 orp_reader.py get coinbase-japan-analysis
    python3 orp_reader.py log --agent cc --action note "v1.4 digest 上线"
    python3 orp_reader.py digest --agent cc          # session-start sync
"""

import argparse
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# Spec defaults — override via CLI flags or VaultIndex constructor.
STALE_DAYS = 4
MIN_TOKEN_LEN = 2  # drop single-character tokens to cut noise on substring match

# §5.5 Session-start digest defaults
DEFAULT_VAULT_ROOT = "~/Documents/Vincent Obsidian"
DEFAULT_LOG_REL = "wiki/log.md"
DEFAULT_CURSOR_REL = ".orp"  # vault-relative dot-dir, excluded from index by default
DIGEST_TAIL_CAP = 10         # max headers shown on normal digest call
BOOTSTRAP_TAIL = 5           # headers shown on first-ever call (no cursor yet)
AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HEADER_RE = re.compile(r"^(?:## )?🦅\[")
ALLOWED_ACTIONS = ("write", "note", "done", "decision")


class IndexError(Exception):
    """Base class for vault-index state errors."""


class IndexMissing(IndexError):
    """The vault-index.json file does not exist at the given path."""


class IndexCorrupted(IndexError):
    """The file exists but is not parseable as an ORP index."""


def _tokenize(query: str) -> list:
    """Split a free-form query into searchable lowercase tokens.

    Splits on whitespace and most ASCII punctuation. Multi-byte
    characters (CJK) stay as a single token since they're often
    semantically dense (e.g. "撤退" should not be split per char).
    Tokens shorter than MIN_TOKEN_LEN are dropped.
    """
    raw = re.split(r"[\s,.;:!?\-_/\\\"\'\(\)\[\]{}]+", query.lower())
    return [t for t in raw if len(t) >= MIN_TOKEN_LEN]


# ────────────────────────────────────────────────────────
# §5.5 Session-start digest helpers
# ────────────────────────────────────────────────────────

def _validate_agent_id(agent_id: str) -> None:
    """Reject invalid agent ids early — they map to filenames."""
    if not AGENT_ID_RE.match(agent_id):
        raise ValueError(
            f"invalid agent id {agent_id!r} "
            f"(must match {AGENT_ID_RE.pattern})"
        )


def _resolve_vault(vault: str) -> Path:
    p = Path(vault).expanduser()
    if not p.is_dir():
        raise FileNotFoundError(f"vault root not found: {p}")
    return p


def _cursor_path(vault: Path, agent_id: str) -> Path:
    cursor_dir = vault / DEFAULT_CURSOR_REL
    cursor_dir.mkdir(parents=True, exist_ok=True)
    return cursor_dir / f"cursor-{agent_id}.json"


@contextmanager
def _flock(lock_path: Path):
    """Hold an exclusive flock on lock_path for the duration of the block."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


def _read_cursor(cursor_path: Path) -> Optional[int]:
    """Return the byte offset, or None if missing/corrupt.

    Corrupt cursor files are renamed to .broken-<ts>.json so the next
    run starts from bootstrap rather than failing.
    """
    if not cursor_path.exists():
        return None
    try:
        doc = json.loads(cursor_path.read_text(encoding="utf-8"))
        offset = int(doc["log_md_offset"])
        if offset < 0:
            raise ValueError("negative offset")
        return offset
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        broken = cursor_path.with_name(cursor_path.stem + f".broken-{ts}.json")
        try:
            cursor_path.rename(broken)
        except OSError:
            pass
        return None


def _write_cursor(cursor_path: Path, offset: int) -> None:
    """Atomic cursor write: tmp + rename."""
    doc = {
        "log_md_offset": offset,
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    tmp = cursor_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, cursor_path)


def _extract_headers(text: str) -> list:
    """Return lines that look like log.md entry headers (start with optional `## ` then 🦅[)."""
    return [line for line in text.split("\n") if HEADER_RE.match(line)]


class VaultIndex:
    def __init__(self, doc: dict, source_path: Optional[Path] = None):
        self.doc = doc
        self.source_path = source_path
        self._aliases = self._build_alias_table()

    @classmethod
    def load(cls, path) -> "VaultIndex":
        """Load and parse an index file. Raises IndexMissing or IndexCorrupted."""
        p = Path(path).expanduser()
        if not p.exists():
            raise IndexMissing(f"vault-index.json not found at {p}")
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise IndexCorrupted(f"{p} is not valid JSON: {e}") from e
        if not isinstance(doc, dict) or "entries" not in doc:
            raise IndexCorrupted(f"{p} missing 'entries' field — not an ORP index")
        if not isinstance(doc["entries"], dict):
            raise IndexCorrupted(f"{p} 'entries' is not a dict (pre-v1.1 array form?)")
        return cls(doc, source_path=p)

    def _build_alias_table(self) -> list:
        """Flatten aliases for substring matching.

        Returns a list of (alias_lowercase, entry_id, entry_dict) tuples.
        Tolerates scalar `aliases` per spec §3.2.
        """
        table = []
        for eid, entry in self.doc.get("entries", {}).items():
            if not isinstance(entry, dict):
                continue
            aliases = entry.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            for alias in aliases:
                if isinstance(alias, str) and alias.strip():
                    table.append((alias.lower(), eid, entry))
        return table

    def is_stale(self, days: int = STALE_DAYS) -> bool:
        """True if the index `updated` field is more than `days` old."""
        updated = self.doc.get("updated")
        if not updated:
            return True
        # v1.1 emits ISO-8601 with TZ; v1.0 was date-only — accept both.
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(updated, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt) > timedelta(days=days)
            except ValueError:
                continue
        return True  # unparseable → treat as stale

    def match(self, query: str) -> list:
        """Match query against aliases. Returns [(entry_id, entry, alias)].

        Per spec §4.2: substring containment, case-insensitive. A query
        token T matches an alias A if T is in A or A is in T. Results
        are sorted by alias length descending so a longer (more specific)
        alias outranks a shorter one. Each entry appears at most once.
        """
        tokens = _tokenize(query)
        if not tokens:
            return []

        seen = set()
        results = []
        for alias, eid, entry in sorted(self._aliases, key=lambda r: -len(r[0])):
            if eid in seen:
                continue
            for tok in tokens:
                if tok in alias or alias in tok:
                    results.append((eid, entry, alias))
                    seen.add(eid)
                    break
        return results

    def get(self, entry_id: str) -> Optional[dict]:
        """Get a specific entry by ID. None if not found."""
        return self.doc.get("entries", {}).get(entry_id)

    def __len__(self) -> int:
        return len(self.doc.get("entries", {}))


# ────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────

DEFAULT_INDEX_PATH = "~/.hermes/vault-index.json"


def cmd_status(args) -> int:
    try:
        idx = VaultIndex.load(args.index)
    except IndexMissing as e:
        print(f"MISSING: {e}", file=sys.stderr)
        return 2
    except IndexCorrupted as e:
        print(f"CORRUPTED: {e}", file=sys.stderr)
        return 3
    n = len(idx)
    updated = idx.doc.get("updated", "?")
    version = idx.doc.get("version", "(pre-v1.1)")
    state = "STALE" if idx.is_stale() else "fresh"
    print(f"{n} entries, updated {updated}, {state}, schema {version}")
    return 0


def cmd_match(args) -> int:
    try:
        idx = VaultIndex.load(args.index)
    except IndexError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    matches = idx.match(args.query)
    if not matches:
        print("(no matches)", file=sys.stderr)
        return 1
    for eid, entry, alias in matches:
        print(f"{eid}\t{entry.get('path', '')}\t[matched: {alias}]")
    return 0


def cmd_get(args) -> int:
    try:
        idx = VaultIndex.load(args.index)
    except IndexError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    entry = idx.get(args.entry_id)
    if entry is None:
        print(f"(entry not found: {args.entry_id})", file=sys.stderr)
        return 1
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


def cmd_log(args) -> int:
    """§5.5 — append an event entry to wiki/log.md.

    Format: `🦅[<agent>] <ISO8601> · <action> · <one-line message>`

    Enforces §5.2 hard rules: append-only, byte-size invariant, flock during write.
    """
    try:
        _validate_agent_id(args.agent)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.action not in ALLOWED_ACTIONS:
        print(f"ERROR: action must be one of {ALLOWED_ACTIONS}", file=sys.stderr)
        return 2

    msg = args.message.strip().replace("\n", " ").replace("\r", " ")
    if not msg:
        print("ERROR: message cannot be empty", file=sys.stderr)
        return 2

    try:
        vault = _resolve_vault(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    log_path = vault / DEFAULT_LOG_REL
    if not log_path.exists():
        print(f"ERROR: log.md not found at {log_path}", file=sys.stderr)
        return 2

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    entry = f"\n🦅[{args.agent}] {ts} · {args.action} · {msg}\n"
    entry_bytes = entry.encode("utf-8")

    pre_size = log_path.stat().st_size
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, entry_bytes)
        os.fsync(fd)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)

    post_size = log_path.stat().st_size
    expected = pre_size + len(entry_bytes)
    if post_size < expected:
        # §5.2 invariant violated — surface loudly per spec
        print(
            f"ERROR: log.md byte-size invariant violated "
            f"(pre={pre_size}, post={post_size}, expected≥{expected})",
            file=sys.stderr,
        )
        return 4

    print(f"appended {len(entry_bytes)} bytes to {log_path}")
    return 0


def cmd_digest(args) -> int:
    """§5.5 — print events appended to wiki/log.md since this agent's cursor.

    Best-effort by design: vault unavailable / log.md missing → silent exit 0
    so a SessionStart hook never blocks agent startup. Cursor advances only
    after stdout is flushed (residual data-loss risk: hook capture failure
    AFTER flush but BEFORE injection — bounded by harness internals).
    """
    try:
        _validate_agent_id(args.agent)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        vault = _resolve_vault(args.vault)
    except FileNotFoundError:
        return 0  # best-effort

    log_path = vault / DEFAULT_LOG_REL
    if not log_path.exists():
        return 0

    cursor_path = _cursor_path(vault, args.agent)
    lock_path = cursor_path.with_suffix(".lock")
    log_size = log_path.stat().st_size

    with _flock(lock_path):
        cursor = None if args.bootstrap else _read_cursor(cursor_path)
        bootstrap = cursor is None
        # Defensive: if cursor is past EOF (log was truncated/replaced — should
        # never happen per §5.2 but better safe), read from start.
        read_offset = 0 if bootstrap else min(cursor, log_size)

        with open(log_path, "rb") as f:
            f.seek(read_offset)
            tail = f.read().decode("utf-8", errors="replace")

        all_headers = _extract_headers(tail)

        if args.full:
            shown = all_headers
        elif bootstrap:
            shown = all_headers[-BOOTSTRAP_TAIL:]
        else:
            shown = all_headers[:DIGEST_TAIL_CAP]
        more_count = len(all_headers) - len(shown)

        if shown:
            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            mode = "bootstrap" if bootstrap else f"since byte {read_offset}"
            print(f"[ORP digest · agent={args.agent} · {mode} · {ts}]")
            for h in shown:
                print(h)
            if more_count > 0:
                print(
                    f"... {more_count} more entries; "
                    f"run `orp_reader.py digest --agent {args.agent} --full` to see all"
                )
        # else: silent — no new activity since last call

        sys.stdout.flush()

        if not args.peek:
            _write_cursor(cursor_path, log_size)

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Reference reader for the Obsidian RAG Protocol",
    )
    parser.add_argument(
        "--index", default=DEFAULT_INDEX_PATH,
        help=f"Path to vault-index.json (default: {DEFAULT_INDEX_PATH})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Show index status")
    p_status.set_defaults(func=cmd_status)

    p_match = sub.add_parser("match", help="Match a query against aliases")
    p_match.add_argument("query", help="Free-form query string")
    p_match.set_defaults(func=cmd_match)

    p_get = sub.add_parser("get", help="Get a specific entry by ID")
    p_get.add_argument("entry_id")
    p_get.set_defaults(func=cmd_get)

    # §5.5 Session-start digest commands ─────────────────
    p_log = sub.add_parser(
        "log",
        help="Append an event to wiki/log.md (agents MUST use this, not hand-edit)",
    )
    p_log.add_argument("--agent", required=True, help="agent id (e.g. cc, hermes)")
    p_log.add_argument(
        "--action", required=True,
        help=f"event action; one of {ALLOWED_ACTIONS}",
    )
    p_log.add_argument(
        "--vault", default=DEFAULT_VAULT_ROOT,
        help=f"vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    p_log.add_argument("message", help="one-line summary of the event")
    p_log.set_defaults(func=cmd_log)

    p_digest = sub.add_parser(
        "digest",
        help="Print events appended to log.md since this agent's last call",
    )
    p_digest.add_argument("--agent", required=True, help="agent id (e.g. cc, hermes)")
    p_digest.add_argument(
        "--vault", default=DEFAULT_VAULT_ROOT,
        help=f"vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    p_digest.add_argument(
        "--bootstrap", action="store_true",
        help="ignore cursor; show last N entries from full log",
    )
    p_digest.add_argument(
        "--full", action="store_true",
        help="ignore cap; show all unread entries",
    )
    p_digest.add_argument(
        "--peek", action="store_true",
        help="read without advancing cursor (debugging)",
    )
    p_digest.set_defaults(func=cmd_digest)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
