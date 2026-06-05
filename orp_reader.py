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
    python3 orp_reader.py digest --agent cc                # session-start sync
"""

import argparse
import fcntl
import hashlib
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
# Precision guard: a query with ≥COVERAGE_MIN_QUERY_TOKENS tokens must hit
# ≥COVERAGE_MIN_MATCHES *distinct* tokens per entry, else one common substring
# token ("in", "hermes") fans out to scores of weakly-related entries. Shorter
# queries keep single-token matching so "parking" / "ORP status" still resolve.
COVERAGE_MIN_QUERY_TOKENS = 3
COVERAGE_MIN_MATCHES = 2

# §5.5 Session-start digest defaults
DEFAULT_VAULT_ROOT = "~/Documents/Vincent Obsidian"
DEFAULT_LOG_REL = "wiki/log.md"
DEFAULT_CURSOR_REL = ".orp"  # vault-relative dot-dir, excluded from index by default
DEFAULT_TELEMETRY_REL = ".orp/telemetry.jsonl"  # local dogfood tracker (Vincent's fork)
DIGEST_TAIL_CAP = 10         # max headers shown on normal digest call
BOOTSTRAP_TAIL = 5           # headers shown on first-ever call (no cursor yet)
AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HEADER_RE = re.compile(r"^(?:## )?🦅\[")
ALLOWED_ACTIONS = ("write", "note", "done", "decision")

# v1.5.1 C2 identity — trigger category enum (spec-locked)
ALLOWED_TRIGGERS = frozenset({"hook", "skill", "cron", "manual", "replay", "migration"})

# v1.6 D (edit-intent soft protocol) rolled back to v1.7 backlog 2026-05-23.
# Reason: same "no failing case" evidence that demoted v1.6-C also applies to D
# (5d 0 write conflicts post v1.5.1, CC↔Hermes write surfaces are directory-split
# read-only on each other). Re-evaluate when write contention shows up in the log.
# See roadmap.md backlog row + archive/v1.5-plan-cargo-culting-archived.md smell-check.


class IndexStateError(Exception):
    """Base class for vault-index state errors."""


class IndexMissing(IndexStateError):
    """The vault-index.json file does not exist at the given path."""


class IndexCorrupted(IndexStateError):
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
    """v1.5.1 C1: new path under Vault/.orp/cursors/<agent>.json"""
    cursor_dir = vault / ".orp" / "cursors"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    return cursor_dir / f"{agent_id}.json"


# Backward-compat: also check old cursor path (Vault/.orp/cursor-<agent>.json)
# for migration bootstrapping — if new path missing but old exists, use old.
def _cursor_path_fallback(vault: Path, agent_id: str) -> Path:
    new = _cursor_path(vault, agent_id)
    if new.exists():
        return new
    old = vault / ".orp" / f"cursor-{agent_id}.json"
    if old.exists():
        return old
    return new  # doesn't exist yet either way


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


def _read_cursor(cursor_path: Path) -> Optional[dict]:
    """Return cursor dict (v1.5.1 schema) or None if missing/corrupt.

    v1.5.1 schema: agent, log_path, byte_offset, last_entry_ts, last_updated,
    version, file_size, tail_hash, tail_mtime.
    Backward-compat: old schema with 'log_md_offset' → lifted to 'byte_offset'.
    Corrupt cursor files are renamed to .broken-<ts>.json.
    """
    if not cursor_path.exists():
        return None
    try:
        doc = json.loads(cursor_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        broken = cursor_path.with_name(cursor_path.stem + f".broken-{ts}.json")
        try:
            cursor_path.rename(broken)
        except OSError:
            pass
        return None

    # Accept both old field name (log_md_offset) and new (byte_offset)
    try:
        offset = int(doc.get("byte_offset", doc.get("log_md_offset")))
    except (ValueError, TypeError, KeyError):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        broken = cursor_path.with_name(cursor_path.stem + f".broken-{ts}.json")
        try:
            cursor_path.rename(broken)
        except OSError:
            pass
        return None

    if offset < 0:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        broken = cursor_path.with_name(cursor_path.stem + f".broken-{ts}.json")
        try:
            cursor_path.rename(broken)
        except OSError:
            pass
        return None

    # Normalize to v1.5.1 schema
    return {
        "agent": doc.get("agent", "unknown"),
        "byte_offset": offset,
        "last_entry_ts": doc.get("last_entry_ts"),
        "last_updated": doc.get("last_updated"),
        "file_size": doc.get("file_size"),
        "tail_hash": doc.get("tail_hash"),
        "tail_mtime": doc.get("tail_mtime"),
    }


def _write_cursor(cursor_path: Path, cursor: dict, log_size: int = None,
                  tail_hash: str = None, tail_mtime: str = None) -> None:
    """v1.5.1 C1: atomic cursor write with tmpfile+rename.

    Updates last_updated and sanity fields (file_size, tail_hash, tail_mtime)
    if provided. Always writes the full v1.5.1 schema.
    """
    import tempfile

    doc = {
        "agent": cursor.get("agent", "hermes"),
        "log_path": "wiki/log.md",
        "byte_offset": cursor["byte_offset"],
        "last_entry_ts": cursor.get("last_entry_ts"),
        "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": 1,
        "file_size": log_size,
        "tail_hash": tail_hash,
        "tail_mtime": tail_mtime,
    }
    # Don't write None for sanity fields — omit instead
    for k in ("file_size", "tail_hash", "tail_mtime"):
        if doc.get(k) is None:
            del doc[k]

    dir_ = cursor_path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dir_), prefix=".cursor-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cursor_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _extract_headers(text: str) -> list:
    """Return lines that look like log.md entry headers (start with optional `## ` then 🦅[)."""
    return [line for line in text.split("\n") if HEADER_RE.match(line)]


def _extract_headers_with_offsets(tail_bytes: bytes, base_offset: int) -> list:
    """Return [(header_str, absolute_byte_offset_of_line_start), ...].

    Used by `cmd_digest` to advance cursor to first-UNSHOWN entry when output
    is capped, so truncated entries appear next call instead of being skipped.
    Iterates over raw bytes so offsets are byte-exact across multi-byte UTF-8.
    """
    results = []
    pos = 0
    for line_bytes in tail_bytes.split(b"\n"):
        line_str = line_bytes.decode("utf-8", errors="replace")
        if HEADER_RE.match(line_str):
            results.append((line_str, base_offset + pos))
        pos += len(line_bytes) + 1
    return results


def _compute_tail_hash(log_path: Path, byte_offset: int) -> str:
    """Compute SHA-1 of the 256 bytes before byte_offset for sanity check.

    v1.5.1 C1: used to populate cursor.tail_hash after digest write.
    Returns empty string if offset is 0 (no tail yet).
    """
    if byte_offset <= 0:
        return ""
    with open(log_path, "rb") as f:
        start = max(0, byte_offset - 256)
        f.seek(start)
        tail = f.read(byte_offset - start)
    return hashlib.sha1(tail).hexdigest()


# ────────────────────────────────────────────────────────
# Dogfood telemetry (LOCAL FORK — not in repo orp_reader.py)
# Tracks digest + log calls to vault/.orp/telemetry.jsonl for v1.4
# dogfood metrics. Best-effort: telemetry write failure NEVER affects
# the actual digest/log behavior.
# ────────────────────────────────────────────────────────

def _telemetry_path(vault: Path) -> Path:
    return vault / DEFAULT_TELEMETRY_REL


def _emit_telemetry(vault: Path, event: dict) -> None:
    """Append one JSONL row to telemetry file. Swallow all errors — this is dogfood instrumentation."""
    try:
        path = _telemetry_path(vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        event["ts"] = datetime.now().astimezone().isoformat(timespec="seconds")
        line = json.dumps(event, ensure_ascii=False) + "\n"
        # Atomic append under flock (telemetry is multi-writer too)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line.encode("utf-8"))
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
    except Exception:
        pass  # telemetry failure must not affect protocol


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

    def match(self, query: str,
              min_query_tokens: int = COVERAGE_MIN_QUERY_TOKENS,
              min_matches: int = COVERAGE_MIN_MATCHES) -> list:
        """Match query against aliases. Returns [(entry_id, entry, alias)].

        Per spec §4.2: substring containment, case-insensitive. A query
        token T matches an alias A if T is in A or A is in T. Results
        are sorted by alias length descending so a longer (more specific)
        alias outranks a shorter one. Each entry appears at most once.

        Precision guard: when the query has ≥min_query_tokens tokens, an
        entry must match ≥min_matches *distinct* query tokens to be kept —
        this collapses single-token substring fan-out (one token like
        "in"/"hermes" matching 168/56 entries) while leaving short queries
        (which keep single-token matching) unchanged. Defaults come from the
        COVERAGE_MIN_* module constants; override per-call to probe sensitivity.
        """
        tokens = _tokenize(query)
        if not tokens:
            return []

        min_cov = min_matches if len(tokens) >= min_query_tokens else 1

        best = {}       # eid -> (alias, entry): longest matching alias (sort is desc)
        coverage = {}   # eid -> set of distinct query tokens that matched any alias
        for alias, eid, entry in sorted(self._aliases, key=lambda r: -len(r[0])):
            hits = [tok for tok in tokens if tok in alias or alias in tok]
            if not hits:
                continue
            if eid not in best:
                best[eid] = (alias, entry)
            coverage.setdefault(eid, set()).update(hits)

        results = [(eid, entry, alias) for eid, (alias, entry) in best.items()
                   if len(coverage[eid]) >= min_cov]
        results.sort(key=lambda r: -len(r[2]))
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
    except IndexStateError as e:
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
    except IndexStateError as e:
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

    v1.5.1 C2 identity: when --trigger is provided, appends
    `‖ meta: session=<sid8> trigger=<cat>:<detail>` suffix.
    sid8 = sha256(run-id)[:8] for PII safety.

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

    # v1.5.1 C2: validate trigger if provided
    trigger = getattr(args, "trigger", None)
    if trigger is not None:
        if ":" not in trigger:
            print(
                f"ERROR: trigger must be 'category:detail' format, got {trigger!r}",
                file=sys.stderr,
            )
            return 2
        cat = trigger.split(":", 1)[0]
        if cat not in ALLOWED_TRIGGERS:
            print(
                f"ERROR: trigger category {cat!r} not in {sorted(ALLOWED_TRIGGERS)}",
                file=sys.stderr,
            )
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
    entry = f"\n🦅[{args.agent}] {ts} · {args.action} · {msg}"

    # v1.5.1 C2 identity: append meta suffix when trigger is provided
    if trigger is not None:
        # Derive session id hash from trigger + timestamp to be deterministic
        # within a cron run (same trigger+ts → same sid8)
        sid8 = hashlib.sha256(
            f"{trigger}-{ts}".encode()
        ).hexdigest()[:8]
        entry += f" ‖ meta: session={sid8} trigger={trigger}"

    entry += "\n"
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

    _emit_telemetry(vault, {
        "subcommand": "log",
        "agent": args.agent,
        "action": args.action,
        "bytes": len(entry_bytes),
    })

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

    cursor_path = _cursor_path_fallback(vault, args.agent)
    lock_path = cursor_path.with_suffix(".lock")
    log_size = log_path.stat().st_size
    log_mtime = datetime.fromtimestamp(
        log_path.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    with _flock(lock_path):
        cursor = None if args.bootstrap else _read_cursor(cursor_path)
        bootstrap = cursor is None

        # v1.5.1 C1: sanity check (only when not bootstrap)
        sanity_failed = False
        sanity_reason = ""
        if not bootstrap:
            read_offset = min(cursor["byte_offset"], log_size)
            # Check 1: log file size shrunk
            if cursor.get("file_size") and log_size < cursor["file_size"]:
                sanity_failed = True
                sanity_reason = (
                    f"log size shrunk {cursor['file_size']}→{log_size}"
                )
            # Check 2: log mtime regressed
            elif cursor.get("tail_mtime") and log_mtime < cursor["tail_mtime"]:
                sanity_failed = True
                sanity_reason = (
                    f"log mtime regressed {cursor['tail_mtime']}→{log_mtime}"
                )
            # Check 3: tail hash mismatch
            elif cursor.get("tail_hash") and read_offset > 0:
                with open(log_path, "rb") as f:
                    start = max(0, read_offset - 256)
                    f.seek(start)
                    tail = f.read(read_offset - start)
                recomputed = hashlib.sha1(tail).hexdigest()
                if recomputed != cursor["tail_hash"]:
                    sanity_failed = True
                    sanity_reason = "tail hash mismatch — log was edited before cursor"

        if sanity_failed:
            # Full rescan — not silent
            bootstrap = True
            read_offset = 0
            # Log the reset to wiki/log.md
            import tempfile as _tmp
            reset_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
            reset_run_id = f"cursor-rescan-{reset_ts}"
            reset_sid8 = hashlib.sha256(reset_run_id.encode()).hexdigest()[:8]
            reset_entry = (
                f"\n🦅[{args.agent}] {datetime.now().astimezone().isoformat(timespec='seconds')} "
                f"· note · ⚠ cursor reset triggered by sanity check (reason: {sanity_reason}) "
                f"‖ meta: session={reset_sid8} trigger=migration:cursor-rescan\n"
            )
            reset_bytes = reset_entry.encode("utf-8")
            fd = os.open(log_path, os.O_WRONLY | os.O_APPEND)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.write(fd, reset_bytes)
                os.fsync(fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            print(f"[sanity check FAILED] {sanity_reason} → full rescan + ⚠ entry written to log", file=sys.stderr)
        else:
            read_offset = 0 if bootstrap else min(cursor["byte_offset"], log_size)

        with open(log_path, "rb") as f:
            f.seek(read_offset)
            tail_bytes = f.read()

        # v1.4.1: track byte offsets so cursor can land at first-UNSHOWN entry
        # when output is capped — pre-fix the cursor always jumped to log_size,
        # permanently dropping truncated entries.
        all_headers = _extract_headers_with_offsets(tail_bytes, read_offset)

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
            for header_str, _ in shown:
                print(header_str)
            if more_count > 0:
                print(
                    f"... {more_count} more entries; "
                    f"run `orp_reader.py digest --agent {args.agent} --full` to see all"
                )
        # else: silent — no new activity since last call

        sys.stdout.flush()

        if not args.peek:
            # Regular mode + cap hit: land at first-unshown offset (v1.4.1 fix).
            # Bootstrap / --full / no-cap-hit: jump to log_size as before.
            if not bootstrap and not args.full and more_count > 0 and shown:
                next_offset = all_headers[len(shown)][1]
            else:
                next_offset = log_size

            # v1.5.1 C1: compute sanity fields for cursor
            new_tail_hash = _compute_tail_hash(log_path, next_offset)
            _write_cursor(
                cursor_path,
                {"byte_offset": next_offset,
                 "last_entry_ts": cursor.get("last_entry_ts") if cursor else None},
                log_size=log_size,
                tail_hash=new_tail_hash,
                tail_mtime=log_mtime,
            )

    _emit_telemetry(vault, {
        "subcommand": "digest",
        "agent": args.agent,
        "mode": "bootstrap" if bootstrap else "since_byte",
        "headers_shown": len(shown),
        "more_count": more_count,
        "silent": len(shown) == 0,
        "peek": bool(args.peek),
        "log_size": log_size,
    })

    return 0


def cmd_dogfood_report(args) -> int:
    """Read telemetry + vault state, compute v1.4 dogfood metrics.

    Two metrics target the failure modes Vincent flagged severe:
    - 坑1 (CC sees digest but doesn't act): non-empty digest count.
      Auto-detection of "did CC act" is impossible; we surface count
      so Vincent can manually rate signal-vs-theater ratio.
    - 坑2 (log writing discipline): vault md changes vs log entries
      written, per agent, per day.

    Plus action vocab distribution (坑5 — slow signal decay) and
    daily digest activity ratio.
    """
    try:
        vault = _resolve_vault(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    telemetry_path = _telemetry_path(vault)
    if not telemetry_path.exists():
        print(f"(no telemetry yet at {telemetry_path} — dogfood hasn't started)")
        return 0

    cutoff = datetime.now().astimezone() - timedelta(days=args.days)

    digest_calls = []
    log_calls = []
    for line in telemetry_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            ts = datetime.fromisoformat(ev["ts"])
            if ts < cutoff:
                continue
            if ev.get("subcommand") == "digest":
                digest_calls.append(ev)
            elif ev.get("subcommand") == "log":
                log_calls.append(ev)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    # 坑 1 metric — non-empty digest ratio per agent
    print(f"=== ORP v1.4 Dogfood Report · last {args.days} days ===")
    print(f"(generated {datetime.now().astimezone().isoformat(timespec='seconds')})")
    print()

    print("[坑1] Digest activity (CC sees digest but doesn't act?)")
    print("─────────────────────────────────────────────────────────")
    by_agent_digest = {}
    for ev in digest_calls:
        a = ev.get("agent", "?")
        by_agent_digest.setdefault(a, {"total": 0, "non_empty": 0, "bootstrap": 0, "more_count_sum": 0})
        by_agent_digest[a]["total"] += 1
        if not ev.get("silent"):
            by_agent_digest[a]["non_empty"] += 1
        if ev.get("mode") == "bootstrap":
            by_agent_digest[a]["bootstrap"] += 1
        by_agent_digest[a]["more_count_sum"] += ev.get("more_count", 0)
    if by_agent_digest:
        for a, m in sorted(by_agent_digest.items()):
            ratio = (m["non_empty"] / m["total"]) * 100 if m["total"] else 0
            print(f"  {a}: {m['total']} digest calls, {m['non_empty']} non-empty ({ratio:.0f}%), {m['bootstrap']} bootstrap, {m['more_count_sum']} entries hit cap")
        print("  → 坑1 manual: did CC reference any non-empty digest entry during the session?")
        print("    Track per-session in dogfood-v1.4-notes.md. < 30% references = digest is theater.")
    else:
        print("  (no digest calls in window)")
    print()

    # 坑 2 metric — log discipline (vault changes vs log entries)
    print("[坑2] Log writing discipline (agents forget to log?)")
    print("─────────────────────────────────────────────────────────")
    log_count_by_agent = {}
    for ev in log_calls:
        a = ev.get("agent", "?")
        log_count_by_agent[a] = log_count_by_agent.get(a, 0) + 1

    # Vault change count via mtime (best-effort proxy — mtime caveat applies)
    cutoff_ts = cutoff.timestamp()
    vault_md_changes = 0
    for scan_dir in ("wiki",):
        scan_path = vault / scan_dir
        if not scan_path.is_dir():
            continue
        for p in scan_path.rglob("*.md"):
            if p.name == "log.md":
                continue
            try:
                if p.stat().st_mtime > cutoff_ts:
                    vault_md_changes += 1
            except OSError:
                continue

    total_log_entries = sum(log_count_by_agent.values())
    if vault_md_changes or total_log_entries:
        print(f"  vault md files changed (wiki/, excl log.md): {vault_md_changes}")
        print(f"  log entries written via CLI:")
        for a, n in sorted(log_count_by_agent.items()):
            print(f"    {a}: {n}")
        if vault_md_changes > 0:
            ratio = total_log_entries / vault_md_changes
            verdict = "✓" if ratio >= 0.33 else "⚠️"
            print(f"  ratio (log entries / vault changes): {ratio:.2f} {verdict}")
            print("  → 坑2 alarm: ratio < 0.33 (1 log per 3 vault changes) suggests discipline gap")
        else:
            print("  (no vault changes in window — can't compute ratio)")
    else:
        print("  (no activity in window)")
    print()

    # 坑 5 — action vocab distribution
    print("[坑5] Action vocab distribution (semantic drift?)")
    print("─────────────────────────────────────────────────────────")
    action_counts = {}
    for ev in log_calls:
        a = ev.get("action", "?")
        action_counts[a] = action_counts.get(a, 0) + 1
    if action_counts:
        total = sum(action_counts.values())
        for a, n in sorted(action_counts.items(), key=lambda x: -x[1]):
            pct = (n / total) * 100
            print(f"  {a}: {n} ({pct:.0f}%)")
        note_pct = (action_counts.get("note", 0) / total) * 100
        if note_pct > 60:
            print(f"  ⚠️  note > 60% — vocab too thin, consider extending in v1.5")
        else:
            print(f"  ✓ vocab spread looks healthy (note < 60%)")
    else:
        print("  (no log calls in window)")
    print()

    # Notes file pointer
    notes_path = Path("~/Documents/Claude Projects/ORP/dogfood-v1.4-notes.md").expanduser()
    if notes_path.exists():
        size = notes_path.stat().st_size
        print(f"Manual observations: {notes_path} ({size} bytes)")
    else:
        print(f"Manual observations: {notes_path} (not created yet)")

    return 0


# ─── v1.6 E Tier 2 — stale + dedup report (lightweight) ──────────────────

_ENTITY_STATUS_RE = re.compile(r'^status:\s*(\S+)', re.MULTILINE)
_ENTITY_TITLE_RE = re.compile(r'^title:\s*(.+?)$', re.MULTILINE)
_ENTITY_UPDATED_RE = re.compile(r'^updated:\s*(\d{4}-\d{2}-\d{2})', re.MULTILINE)
_ENTITY_H1_RE = re.compile(r'^#\s+(.+?)$', re.MULTILINE)

STATUS_LIVE = frozenset({"captured", "candidate", "verified", "retrievable"})


def _parse_entity_for_report(path: Path):
    """Lightweight entity parser for the stale/dedup report. Reads first 8 KB."""
    try:
        head = path.read_text(encoding='utf-8', errors='replace')[:8192]
    except Exception:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    out = {"path": path, "mtime": mtime, "status": "verified",
           "title": None, "updated_date": None, "h1": None}
    if head.startswith('---'):
        end = head.find('\n---', 3)
        if end > 0:
            fm = head[3:end]
            ms = _ENTITY_STATUS_RE.search(fm)
            if ms:
                out["status"] = ms.group(1).strip().strip('"').strip("'").rstrip(',').lower()
            mt = _ENTITY_TITLE_RE.search(fm)
            if mt:
                out["title"] = mt.group(1).strip().strip('"').strip("'")
            mu = _ENTITY_UPDATED_RE.search(fm)
            if mu:
                out["updated_date"] = mu.group(1)
    mh = _ENTITY_H1_RE.search(head)
    if mh:
        out["h1"] = mh.group(1).strip()
    return out


def cmd_stale_dedup_report(args) -> int:
    """v1.6 E Tier 2 — write a stale + duplicate candidate report.

    Lightweight: not a full consolidation pipeline. Scans vault entities,
    flags entries whose last touch (frontmatter `updated:` or mtime) is older
    than --stale-days AND whose status is still in STATUS_LIVE. Also groups
    by frontmatter `title:` / first `# H1` to surface duplicate candidates.

    Output: a markdown report at vault/.orp/reports/stale-dedup-<date>.md
    (override with --output). Does NOT mutate any entity — Vincent reviews
    and acts manually per v1.5.1 C3 state machine.
    """
    try:
        vault = _resolve_vault(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    scan_roots = args.scan or ["hermes-knowledge", "wiki"]
    skip_names = {"log.md", "README.md", "index.md"}

    entities = []
    for root in scan_roots:
        root_path = vault / root
        if not root_path.is_dir():
            continue
        for md in root_path.rglob("*.md"):
            if md.name in skip_names:
                continue
            # also skip hidden + report output dir to avoid recursion
            if any(part.startswith('.') for part in md.relative_to(vault).parts):
                continue
            ent = _parse_entity_for_report(md)
            if ent:
                entities.append(ent)

    now = datetime.now().astimezone()
    stale_cutoff_ts = (now - timedelta(days=args.stale_days)).timestamp()

    stale = []
    for e in entities:
        if e["status"] not in STATUS_LIVE:
            continue
        last_touch_ts = e["mtime"]
        if e["updated_date"]:
            try:
                ud = datetime.fromisoformat(e["updated_date"] + "T00:00:00").astimezone()
                last_touch_ts = max(last_touch_ts, ud.timestamp())  # take latest signal
            except ValueError:
                pass
        if last_touch_ts < stale_cutoff_ts:
            e["age_days"] = (now.timestamp() - last_touch_ts) / 86400
            stale.append(e)

    by_key = {}
    for e in entities:
        key = (e["title"] or e["h1"] or "").strip().lower()
        if not key:
            continue
        by_key.setdefault(key, []).append(e)
    dups = [(k, v) for k, v in by_key.items() if len(v) >= 2]

    if args.output:
        out_path = Path(args.output).expanduser()
    else:
        date_str = now.strftime("%Y-%m-%d")
        out_path = vault / ".orp" / "reports" / f"stale-dedup-{date_str}.md"

    lines = [
        f"# Stale + Dedup Report — {now.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        f"> Generated by `orp_reader.py stale-dedup-report` · v1.6 E Tier 2",
        f"> Scanned {len(entities)} entities under {', '.join(scan_roots)}/",
        f"> Thresholds: stale_days={args.stale_days}",
        "",
        "_Not a lock — Vincent reviews and acts. Use `status: archived` or merge manually._",
        "",
        f"## Stale candidates ({len(stale)})",
        "",
    ]
    if not stale:
        lines.append("(none)")
    else:
        stale.sort(key=lambda x: x["age_days"], reverse=True)
        for e in stale[:args.limit]:
            rel = e["path"].relative_to(vault)
            lines.append(
                f"- [[{rel}]] · status `{e['status']}` · age {e['age_days']:.0f}d"
            )
        if len(stale) > args.limit:
            lines.append(f"- … and {len(stale) - args.limit} more (raise --limit to see all)")
    lines += ["", f"## Duplicate candidates ({len(dups)} groups)", ""]
    if not dups:
        lines.append("(none)")
    else:
        dups.sort(key=lambda x: -len(x[1]))
        for k, group in dups[:args.limit]:
            lines.append(f"### `{k}` ({len(group)} files)")
            for e in group:
                rel = e["path"].relative_to(vault)
                lines.append(f"- [[{rel}]] · status `{e['status']}`")
            lines.append("")
        if len(dups) > args.limit:
            lines.append(f"… and {len(dups) - args.limit} more duplicate groups")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "report_path": str(out_path),
        "entities_scanned": len(entities),
        "stale_count": len(stale),
        "dup_groups": len(dups),
    }
    if args.format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Report → {out_path}")
        print(f"  entities scanned: {summary['entities_scanned']}")
        print(f"  stale candidates: {summary['stale_count']}")
        print(f"  duplicate groups: {summary['dup_groups']}")
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
    p_log.add_argument(
        "--trigger",
        help=(
            "v1.5.1 C2 identity: trigger category:detail for meta suffix "
            "(e.g. 'cron:entity-promo'). Category must be one of: "
            + ", ".join(sorted(ALLOWED_TRIGGERS))
        ),
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

    # v1.6 E Tier 2 — stale + dedup weekly report ───────────────
    p_sd = sub.add_parser(
        "stale-dedup-report",
        help=(
            "v1.6 E — write a stale + duplicate-candidate report under "
            "vault/.orp/reports/. Hermes weekly cron tool; Vincent reviews manually."
        ),
    )
    p_sd.add_argument(
        "--vault", default=DEFAULT_VAULT_ROOT,
        help=f"vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    p_sd.add_argument(
        "--stale-days", type=int, default=30,
        help="age threshold in days (default: 30)",
    )
    p_sd.add_argument(
        "--scan", action="append",
        help="vault-relative root to scan (repeatable; default: hermes-knowledge wiki)",
    )
    p_sd.add_argument(
        "--limit", type=int, default=50,
        help="max items per section in report (default: 50)",
    )
    p_sd.add_argument(
        "--output",
        help="override report output path (default: vault/.orp/reports/stale-dedup-YYYY-MM-DD.md)",
    )
    p_sd.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="stdout summary format (report markdown is always written)",
    )
    p_sd.set_defaults(func=cmd_stale_dedup_report)

    # Dogfood metrics (LOCAL FORK — Vincent's v1.4 evaluation tool)
    p_dogfood = sub.add_parser(
        "dogfood-report",
        help="v1.4 dogfood metrics: digest activity, log discipline, action vocab distribution",
    )
    p_dogfood.add_argument(
        "--vault", default=DEFAULT_VAULT_ROOT,
        help=f"vault root (default: {DEFAULT_VAULT_ROOT})",
    )
    p_dogfood.add_argument("--days", type=int, default=7, help="report window in days (default: 7)")
    p_dogfood.set_defaults(func=cmd_dogfood_report)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
