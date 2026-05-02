#!/usr/bin/env python3
"""
orp_health.py — Health check for an ORP vault index.

Verifies four things, fails the run if any of them are wrong:

  1. Index file exists and is valid JSON
  2. Top-level schema is v1.1+ (has `version`, `updated`, `entries` dict)
  3. Each entry has the required fields (_content_hash, path, aliases)
  4. Index isn't stale beyond a configurable threshold

Plus three soft warnings (don't fail, but report):

  - Index size beyond a soft cap (default 50KB)
  - Entries whose `path` no longer exists on disk (orphans)
  - Aliases shorter than 2 characters (will be filtered by reader's noise floor)

Stdlib only. Run from CI, cron, or ad-hoc.

USAGE:
    python3 orp_health.py                              # default index path, defaults
    python3 orp_health.py --index ~/.hermes/vault-index.json
    python3 orp_health.py --max-stale-days 4 --max-size-kb 50
    python3 orp_health.py --strict                     # warnings become failures

EXIT CODES:
    0  healthy
    1  hard failure (corrupted, schema invalid, stale, missing required fields)
    2  --strict: soft warning escalated to failure
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_INDEX_PATH = "~/.hermes/vault-index.json"
DEFAULT_MAX_STALE_DAYS = 4
DEFAULT_MAX_SIZE_KB = 50
DEFAULT_MIN_ALIAS_LEN = 2

REQUIRED_TOP_LEVEL = ("version", "updated", "entries")
REQUIRED_ENTRY_FIELDS = ("_content_hash", "path", "aliases")


def parse_updated(s: str):
    """Parse the index `updated` field. Accepts ISO-8601 with TZ or YYYY-MM-DD."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def check_health(index_path: Path, max_stale_days: int, max_size_kb: int,
                 min_alias_len: int) -> dict:
    """Run all checks. Returns a dict with `failures` and `warnings` lists."""
    failures = []
    warnings = []

    if not index_path.exists():
        return {"failures": [f"index file not found: {index_path}"], "warnings": []}

    raw = index_path.read_bytes()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        return {"failures": [f"index is not valid JSON: {e}"], "warnings": []}

    # Top-level schema
    for field in REQUIRED_TOP_LEVEL:
        if field not in doc:
            failures.append(f"missing top-level field: {field}")

    if "entries" in doc and not isinstance(doc["entries"], dict):
        failures.append("`entries` must be a dict (pre-v1.1 array form not supported)")

    # Staleness
    updated_str = doc.get("updated")
    if updated_str:
        dt = parse_updated(updated_str)
        if dt is None:
            failures.append(f"unparseable `updated` field: {updated_str!r}")
        else:
            age_days = (datetime.now(timezone.utc) - dt).days
            if age_days > max_stale_days:
                failures.append(
                    f"index is {age_days} days old (max {max_stale_days})"
                )

    # Per-entry shape
    entries = doc.get("entries", {}) if isinstance(doc.get("entries"), dict) else {}
    short_aliases = []
    orphans = []
    for eid, entry in entries.items():
        if not isinstance(entry, dict):
            failures.append(f"entry {eid!r} is not a dict")
            continue
        for field in REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                failures.append(f"entry {eid!r} missing required field: {field}")
        # Soft: orphan path
        path = entry.get("path")
        if isinstance(path, str) and path and not Path(path).exists():
            orphans.append(eid)
        # Soft: short aliases
        aliases = entry.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        for a in aliases:
            if isinstance(a, str) and 0 < len(a) < min_alias_len:
                short_aliases.append((eid, a))

    if orphans:
        warnings.append(
            f"{len(orphans)} entries reference paths that no longer exist: "
            f"{', '.join(orphans[:5])}"
            + (f" (+{len(orphans) - 5} more)" if len(orphans) > 5 else "")
        )
    if short_aliases:
        warnings.append(
            f"{len(short_aliases)} aliases shorter than {min_alias_len} chars "
            f"(will be filtered by the reader's noise floor): "
            + ", ".join(f"{eid}:{a!r}" for eid, a in short_aliases[:5])
        )

    # Soft: index size
    size_kb = len(raw) / 1024
    if size_kb > max_size_kb:
        warnings.append(
            f"index is {size_kb:.1f} KB (soft cap {max_size_kb} KB). "
            f"Consider archiving cold notes to a separate index."
        )

    return {"failures": failures, "warnings": warnings, "size_kb": size_kb,
            "entry_count": len(entries)}


def main():
    parser = argparse.ArgumentParser(
        description="Health check for an ORP vault index",
    )
    parser.add_argument("--index", default=DEFAULT_INDEX_PATH,
                        help=f"Path to vault-index.json (default: {DEFAULT_INDEX_PATH})")
    parser.add_argument("--max-stale-days", type=int, default=DEFAULT_MAX_STALE_DAYS,
                        help=f"Fail if index older than N days (default: {DEFAULT_MAX_STALE_DAYS})")
    parser.add_argument("--max-size-kb", type=int, default=DEFAULT_MAX_SIZE_KB,
                        help=f"Warn if index larger than N KB (default: {DEFAULT_MAX_SIZE_KB})")
    parser.add_argument("--min-alias-len", type=int, default=DEFAULT_MIN_ALIAS_LEN,
                        help=f"Warn on aliases shorter than N chars (default: {DEFAULT_MIN_ALIAS_LEN})")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero on warnings, not just failures")
    args = parser.parse_args()

    index_path = Path(args.index).expanduser()
    result = check_health(
        index_path,
        max_stale_days=args.max_stale_days,
        max_size_kb=args.max_size_kb,
        min_alias_len=args.min_alias_len,
    )

    failures = result["failures"]
    warnings = result["warnings"]

    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)

    if "entry_count" in result:
        size = result.get("size_kb", 0)
        print(f"OK: {result['entry_count']} entries, {size:.1f} KB, "
              f"{len(failures)} failures, {len(warnings)} warnings")

    if failures:
        sys.exit(1)
    if warnings and args.strict:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
