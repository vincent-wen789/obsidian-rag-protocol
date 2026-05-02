#!/usr/bin/env python3
"""
orp_reader.py — Reference reader for the Obsidian RAG Protocol.

Loads vault-index.json and answers queries with matched entries.
Implements the reader side of the spec: schema parsing (§1.2),
alias resolution tolerance (§3.2), matching algorithm (§4.2),
error handling (§4.3), staleness detection (Rule 4).

Stdlib only. ~150 lines. Single file. Use as a library or CLI.

LIBRARY:
    from orp_reader import VaultIndex, IndexMissing, IndexCorrupted
    idx = VaultIndex.load("~/.hermes/vault-index.json")
    for entry_id, entry, matched_alias in idx.match("Coinbase Japan"):
        print(entry["path"])

CLI:
    python3 orp_reader.py status
    python3 orp_reader.py match "Coinbase Japan"
    python3 orp_reader.py get coinbase-japan-analysis
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# Spec defaults — override via CLI flags or VaultIndex constructor.
STALE_DAYS = 4
MIN_TOKEN_LEN = 2  # drop single-character tokens to cut noise on substring match


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

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
