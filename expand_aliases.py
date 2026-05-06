#!/usr/bin/env python3
"""
expand_aliases.py — Bulk-update vault frontmatter `aliases` fields.

Reads a user-supplied JSON file of {entry_id: [aliases_to_add]} and
patches the matching vault file's frontmatter. Existing aliases (in the
frontmatter AND in the index) are preserved; new aliases are appended
and de-duplicated.

Designed for ORP users who realize their alias coverage is thin
(typical symptom: orp_reader matches ~2 aliases per entry, RAG misses
queries that should hit). Run once with a curated additions file,
then run rebuild-vault-index.py to refresh the index.

USAGE:
    # 1. Write your additions file, e.g. ~/aliases-batch-2026-05.json:
    #    {
    #      "if-game": ["narrative game", "interactive fiction"],
    #      "cookie-ledger": ["PWA 记账", "voice ledger"]
    #    }
    #
    # 2. Dry-run to preview diffs (no writes):
    python3 expand_aliases.py --index ~/.hermes/vault-index.json \
        --additions ~/aliases-batch-2026-05.json --dry
    #
    # 3. Apply:
    python3 expand_aliases.py --index ~/.hermes/vault-index.json \
        --additions ~/aliases-batch-2026-05.json
    #
    # 4. Rebuild the index so new aliases take effect:
    python3 rebuild-vault-index.py ...

KEY DESIGN DECISIONS:
- Merges three sources: frontmatter aliases + index aliases + your additions.
  Frontmatter override semantics (per the protocol spec) mean writing
  frontmatter replaces the indexer's hand-curated ALIAS_MAPS fallback;
  this script merges them first to avoid silent loss.
- Path resolution falls back to vault rglob when index path is stale
  (file was moved to a subdirectory after the last rebuild).
- Inline list format: aliases written as `aliases: [a, b, c]` to match
  the protocol's reference frontmatter shape.
- Skips files without a frontmatter block (does not synthesize one).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def parse_frontmatter(text: str):
    """Return (frontmatter_lines, body_start_line_idx). (None, 0) if no FM."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, 0
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, 0
    return lines[1:end_idx], end_idx + 1


def get_aliases_from_frontmatter(fm_lines):
    """Extract aliases list from frontmatter lines. Returns (list, line_idx)."""
    for i, line in enumerate(fm_lines):
        stripped = line.strip()
        if stripped.startswith("aliases:"):
            value = stripped[len("aliases:"):].strip()
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                items = [s.strip().strip("\"'") for s in inner.split(",") if s.strip()]
                return items, i
    return [], -1


def update_aliases_in_frontmatter(fm_lines, new_aliases_list, aliases_line_idx):
    """Write inline-list-format aliases line. Append if missing."""
    formatted = "[" + ", ".join(new_aliases_list) + "]"
    new_line = f"aliases: {formatted}"
    if aliases_line_idx >= 0:
        fm_lines[aliases_line_idx] = new_line
    else:
        fm_lines.append(new_line)
    return fm_lines


def resolve_path(indexed_path_str: str, vault_root: Optional[Path]) -> Optional[Path]:
    """Try indexed path; fall back to vault rglob by filename if stale."""
    p = Path(indexed_path_str)
    if p.exists():
        return p
    if vault_root and vault_root.exists():
        matches = list(vault_root.rglob(p.name))
        if matches:
            return matches[0]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-update vault frontmatter aliases from a curated additions file.",
    )
    parser.add_argument(
        "--index", required=True,
        help="Path to vault-index.json (the ORP index file).",
    )
    parser.add_argument(
        "--additions", required=True,
        help="Path to JSON file mapping {entry_id: [aliases_to_add]}.",
    )
    parser.add_argument(
        "--vault-root",
        help="Vault root for path-staleness fallback (rglob lookup). "
             "Optional; without it, stale paths in the index are skipped.",
    )
    parser.add_argument(
        "--dry", action="store_true",
        help="Preview changes without writing.",
    )
    args = parser.parse_args()

    idx_path = Path(args.index).expanduser()
    idx_doc = json.loads(idx_path.read_text(encoding="utf-8"))
    entries = idx_doc.get("entries", {})

    additions_doc = json.loads(Path(args.additions).expanduser().read_text(encoding="utf-8"))
    if not isinstance(additions_doc, dict):
        print("ERROR: --additions must be a JSON object {entry_id: [aliases]}.", file=sys.stderr)
        return 1

    vault_root = Path(args.vault_root).expanduser() if args.vault_root else None

    stats = {"updated": 0, "skipped_no_match": 0, "skipped_no_file": 0, "skipped_no_fm": 0}
    misses = []

    for eid, additions in additions_doc.items():
        if not isinstance(additions, list):
            print(f"[warn] {eid}: additions must be a list, skipping.", file=sys.stderr)
            continue

        entry = entries.get(eid)
        if not entry:
            stats["skipped_no_match"] += 1
            misses.append(eid)
            continue

        path = resolve_path(entry.get("path", ""), vault_root)
        if path is None:
            stats["skipped_no_file"] += 1
            print(f"[skip-nofile] {eid} -> {entry.get('path', '')}", file=sys.stderr)
            continue

        text = path.read_text(encoding="utf-8")
        fm_lines, body_idx = parse_frontmatter(text)
        if fm_lines is None:
            stats["skipped_no_fm"] += 1
            print(f"[skip-nofm] {eid} -> {path}", file=sys.stderr)
            continue

        existing_fm, aliases_idx = get_aliases_from_frontmatter(fm_lines)
        # Merge three sources to avoid losing the indexer's ALIAS_MAPS fallback
        # when we write frontmatter (which overrides per protocol).
        indexer_existing = entry.get("aliases", []) or []
        merged = list(existing_fm)
        for a in indexer_existing:
            if a not in merged:
                merged.append(a)
        for a in additions:
            if a not in merged:
                merged.append(a)
        if merged == existing_fm:
            continue

        new_fm_lines = update_aliases_in_frontmatter(fm_lines, merged, aliases_idx)
        new_text = (
            "---\n"
            + "\n".join(new_fm_lines)
            + "\n---\n"
            + "\n".join(text.split("\n")[body_idx:])
        )
        if args.dry:
            print(f"[dry] {eid}")
            print(f"  fm before: {existing_fm}")
            print(f"  indexer:   {indexer_existing}")
            print(f"  after:     {merged}")
        else:
            path.write_text(new_text, encoding="utf-8")
            print(f"[wrote] {eid} ({len(merged) - len(existing_fm)} new aliases)")
        stats["updated"] += 1

    print("\n--- summary ---", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    if misses:
        print(f"  unmatched entry_ids: {misses}", file=sys.stderr)
    if not args.dry:
        print("\nNext step: run rebuild-vault-index.py to refresh the index.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
