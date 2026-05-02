#!/usr/bin/env python3
"""
rebuild-vault-index.py — Reference implementation of the Obsidian RAG Protocol.

Scans configured Obsidian vault subdirectories for .md files,
builds a machine-readable JSON index with SHA256-based incremental updates.

USAGE:
    python3 rebuild-vault-index.py \
        --vault ~/Documents/MyVault \
        --output ~/.hermes/vault-index.json \
        --scan wiki/projects wiki/career hermes-knowledge/

KEY DESIGN DECISIONS:
- SHA256 content hashing (not mtime — unreliable on macOS/iCloud)
- Path-based exclusion rules (not frontmatter-based — more deterministic)
- Frontmatter-driven summaries with plain-text fallback
- Aliases preserved from previous run unless frontmatter updates them
- Incremental: same hash → skip extraction → preserve all metadata
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Bumped to 1.1: deterministic cross-scan-dir collision disambiguation,
# atomic writes, and corrupted-index preservation.
PROTOCOL_VERSION = "1.1"


# ═══════════════════════════════════════════════════
# CONFIGURATION — Edit these for your vault
# ═══════════════════════════════════════════════════

# Excluded directories (relative to vault root or any scan root)
EXCLUDE_DIRS = {
    "archived", "archive", "log", "modes",
    "tracking", "task-",
}

# Excluded filename patterns (regex, matched against stem)
EXCLUDE_FILENAME_PATTERNS = [
    r"^plan-",              # plan-*.md
    r"-progress$",          # *-progress.md
    r"-data-\d{4}-\d{2}$",  # *-data-YYYY-MM.md
]

# Files to always skip
SKIP_FILES = {"index.md", "README.md"}

# Default cutoff: skip files older than this many days
DEFAULT_CUTOFF_DAYS = 90


# ═══════════════════════════════════════════════════
# FRONTMATTER EXTRACTION
# ═══════════════════════════════════════════════════

def extract_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown text."""
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    fm = {}
    in_list = False
    list_key = None
    list_vals = []

    for line in match.group(1).split("\n"):
        # Handle inline list: key: [a, b, c]
        inline_list = re.match(r"^(\w[\w_-]*):\s*\[(.*)\]", line)
        if inline_list:
            key = inline_list.group(1)
            vals = [v.strip().strip('"').strip("'")
                    for v in inline_list.group(2).split(",") if v.strip()]
            fm[key] = vals
            continue

        # Handle multi-line list
        if in_list:
            list_match = re.match(r"^\s+-\s+(.+)", line)
            if list_match:
                list_vals.append(list_match.group(1).strip().strip('"').strip("'"))
                continue
            else:
                fm[list_key] = list_vals
                in_list = False
                list_key = None
                list_vals = []

        # Bare key with empty value, list on subsequent indented lines:
        #   aliases:
        #     - foo
        #     - bar
        # This is the standard YAML multi-line list form. Without this branch
        # the empty-value `aliases:` line falls through to the kv regex below,
        # which requires `(.+)` after the colon, fails to match, and the whole
        # multi-line list gets silently dropped.
        bare_key = re.match(r"^(\w[\w_-]*):\s*$", line)
        if bare_key:
            in_list = True
            list_key = bare_key.group(1)
            list_vals = []
            continue

        # Simple key: value (also handles `key: - val` start of list)
        kv = re.match(r"^(\w[\w_-]*):\s*(.+)", line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip().strip('"').strip("'")
            if val.startswith("- "):
                in_list = True
                list_key = key
                list_vals = [val[2:].strip().strip('"').strip("'")]
            else:
                fm[key] = val

    if in_list and list_key:
        fm[list_key] = list_vals

    return fm


# ═══════════════════════════════════════════════════
# CONTENT HASHING
# ═══════════════════════════════════════════════════

def file_hash(filepath: Path) -> str:
    """SHA256 of file content. Reliable on macOS even with iCloud sync."""
    return hashlib.sha256(filepath.read_bytes()).hexdigest()


# ═══════════════════════════════════════════════════
# EXTRACTION
# ═══════════════════════════════════════════════════

def should_index(filepath: Path, scan_root: Path) -> bool:
    """Single entry point for all exclusion logic."""
    if filepath.name in SKIP_FILES:
        return False

    for parent in filepath.relative_to(scan_root).parents:
        if parent.name in EXCLUDE_DIRS:
            return False
    for parent in filepath.parents:
        if parent.name in EXCLUDE_DIRS:
            return False

    stem = filepath.stem
    for pattern in EXCLUDE_FILENAME_PATTERNS:
        if re.match(pattern, stem):
            return False

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return False
    if content.startswith("---"):
        fm = extract_frontmatter(content)
        if fm.get("rag_exclude") in ("true", "True", True, "yes"):
            return False

    return True


def get_first_paragraph(text: str) -> str:
    """Extract first non-empty, non-heading, non-table line after frontmatter."""
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ">", "|", "<!--")):
            continue
        return stripped[:150] + ("..." if len(stripped) > 150 else "")
    return ""


def extract_summary(fm: dict, body: str) -> dict:
    """Build structured summary from frontmatter, with plain-text fallback."""
    summary = {}

    summary["status"] = fm.get("status", "unknown")

    if "version" in fm:
        summary["version"] = fm["version"]

    if "summary_points" in fm and isinstance(fm["summary_points"], list):
        summary["key_points"] = fm["summary_points"][:5]
    else:
        first_para = get_first_paragraph(body)
        if first_para:
            summary["key_points"] = [first_para]

    if "last_action" in fm:
        summary["last_action"] = fm["last_action"]

    return summary


def resolve_aliases(
    entry_id: str,
    fm: dict,
    old_aliases: Optional[list],
    alias_maps: dict
) -> list:
    """Resolve aliases for an entry.

    Priority:
    1. Frontmatter `aliases` field (explicit update)
    2. Hand-curated alias_maps entry
    3. Preserve from previous index run
    4. Fallback: [entry_id, title.lower()]
    """
    # Frontmatter aliases (scalar tolerance: wrap string as list)
    if "aliases" in fm:
        aliases_val = fm["aliases"]
        if isinstance(aliases_val, list) and aliases_val:
            return aliases_val
        elif isinstance(aliases_val, str) and aliases_val.strip():
            return [aliases_val.strip()]

    # Hand-curated
    if entry_id in alias_maps:
        return alias_maps[entry_id]

    # Preserve from previous run
    if old_aliases:
        return old_aliases

    # Fallback
    title = fm.get("title", entry_id.replace("-", " "))
    return [entry_id, title.lower().replace(" ", "-")]


# ═══════════════════════════════════════════════════
# SCAN & REBUILD
# ═══════════════════════════════════════════════════

def load_old_index(output_path: Path) -> dict:
    """Load previous index for incremental comparison.

    On parse failure, rename the broken file to <name>.broken-<ts> so
    hand-curated aliases can be recovered manually instead of being
    silently lost on the next rebuild.
    """
    if not output_path.exists():
        return {"entries": {}, "updated": "1970-01-01"}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as e:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        broken = output_path.with_name(f"{output_path.name}.broken-{ts}")
        try:
            output_path.rename(broken)
            print(
                f"WARNING: {output_path} is corrupted ({e}). "
                f"Moved to {broken} to preserve hand-curated aliases for recovery.",
                file=sys.stderr,
            )
        except Exception as rename_err:
            print(
                f"WARNING: {output_path} is corrupted ({e}) "
                f"and could not be renamed: {rename_err}",
                file=sys.stderr,
            )
        return {"entries": {}, "updated": "1970-01-01"}


def slugify(s: str) -> str:
    """Lowercase, replace spaces and underscores with hyphens."""
    return s.lower().replace(" ", "-").replace("_", "-")


def naive_entry_id(md_file: Path) -> str:
    """Stem-based entry_id (may collide across scan dirs — resolve in main)."""
    return slugify(md_file.stem)


def scan_directory(
    directory: Path,
    author: str,
    old_entries: dict,
    alias_maps: dict,
    cutoff_days: int = DEFAULT_CUTOFF_DAYS,
) -> list:
    """Scan directory for indexable files. Returns list of entry dicts.

    Cross-scan-dir collision resolution is handled by the caller.
    """
    entries = []
    if not directory.exists():
        return entries

    cutoff = datetime.now() - timedelta(days=cutoff_days)
    old_paths = {e.get("path") for e in old_entries.values() if isinstance(e, dict)}

    for md_file in sorted(directory.rglob("*.md")):
        if not should_index(md_file, directory):
            continue

        mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
        if mtime < cutoff:
            # Don't drop a file we've already indexed — preserves hand-curated
            # aliases for older notes that fall outside the rolling window.
            if str(md_file) not in old_paths:
                continue

        content_hash = file_hash(md_file)
        entry_id = naive_entry_id(md_file)
        old_entry = old_entries.get(entry_id)

        # Incremental skip — same hash means content unchanged, reuse old entry.
        if old_entry and old_entry.get("_content_hash") == content_hash:
            entries.append(old_entry)
            continue

        # Full extraction for new/changed files
        content = md_file.read_text(encoding="utf-8")
        fm = extract_frontmatter(content) if content.startswith("---") else {}

        title = fm.get("title", md_file.stem.replace("-", " ").title())
        updated = fm.get("updated", mtime.strftime("%Y-%m-%d"))
        entry_author = fm.get("author", author)

        summary = extract_summary(fm, content)

        old_aliases = old_entry.get("aliases") if old_entry else None
        aliases = resolve_aliases(entry_id, fm, old_aliases, alias_maps)

        entries.append({
            "_content_hash": content_hash,
            "path": str(md_file),
            "title": title,
            "summary": summary,
            "updated": updated,
            "author": entry_author,
            "aliases": aliases,
        })

    return entries


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Rebuild vault-index.json for Obsidian RAG Protocol"
    )
    parser.add_argument(
        "--vault", required=True,
        help="Path to Obsidian vault root"
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to output vault-index.json"
    )
    parser.add_argument(
        "--scan", nargs="+", required=True,
        help="Subdirectories to scan, format: DIR:AUTHOR or DIR"
    )
    parser.add_argument(
        "--cutoff-days", type=int, default=DEFAULT_CUTOFF_DAYS,
        help=f"Skip files older than N days (default: {DEFAULT_CUTOFF_DAYS})"
    )
    parser.add_argument(
        "--alias-maps", type=str, default=None,
        help="Path to a JSON file with hand-curated alias mappings"
    )

    args = parser.parse_args()

    vault_root = Path(args.vault).expanduser().resolve()
    if not vault_root.exists():
        print(f"ERROR: Vault not found: {vault_root}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Parse scan directories
    scan_targets = []
    for spec in args.scan:
        if ":" in spec:
            path_str, author = spec.rsplit(":", 1)
        else:
            path_str, author = spec, "unknown"
        scan_dir = vault_root / path_str
        scan_targets.append((scan_dir, author))

    # Load alias maps
    alias_maps = {}
    if args.alias_maps:
        try:
            with open(args.alias_maps) as f:
                alias_maps = json.load(f)
        except Exception as e:
            print(f"WARNING: Could not load alias maps: {e}", file=sys.stderr)

    old_index = load_old_index(output_path)
    old_entries = old_index.get("entries", {})

    # Two-pass collection so we can detect cross-scan-dir entry_id collisions
    # and disambiguate deterministically with the scan-root basename.
    collected = []  # (naive_eid, scan_root_slug, entry)
    naive_counts = {}

    for directory, author in scan_targets:
        scan_slug = slugify(directory.name)
        for entry in scan_directory(
            directory, author, old_entries, alias_maps,
            cutoff_days=args.cutoff_days,
        ):
            md_path = Path(entry["path"])
            naive_eid = naive_entry_id(md_path)
            collected.append((naive_eid, scan_slug, entry))
            naive_counts[naive_eid] = naive_counts.get(naive_eid, 0) + 1

    new_entries = {}
    warned_naive = set()
    for naive_eid, scan_slug, entry in collected:
        if naive_counts[naive_eid] > 1:
            final_eid = f"{scan_slug}-{naive_eid}" if scan_slug else naive_eid
            if naive_eid not in warned_naive:
                print(
                    f"NOTE: entry_id '{naive_eid}' collides across scan dirs — "
                    f"disambiguating with scan-root prefix.",
                    file=sys.stderr,
                )
                warned_naive.add(naive_eid)
        else:
            final_eid = naive_eid

        if final_eid in new_entries:
            print(
                f"WARNING: unresolvable entry_id collision '{final_eid}' "
                f"({entry.get('path')}) — keeping last write.",
                file=sys.stderr,
            )
        new_entries[final_eid] = entry

    index = {
        "version": PROTOCOL_VERSION,
        "updated": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "entries": new_entries,
    }

    # Atomic write: tmp + os.replace. A cron interruption or full disk leaves
    # the previous index intact instead of producing a half-written JSON file
    # that trips the agent's "index corrupted" fallback path.
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_path, output_path)

    changed = sum(
        1 for kid, v in new_entries.items()
        if old_entries.get(kid, {}).get("_content_hash") != v.get("_content_hash", "__new__")
    )
    print(f"✅ vault-index.json rebuilt: {len(new_entries)} entries ({changed} changed)")


if __name__ == "__main__":
    main()
