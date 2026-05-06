#!/usr/bin/env python3
"""
convert_bare_to_fullpath.py — Convert bare wikilinks to full-path form.

Bare wikilinks ([[note-name]]) work in Obsidian via vault-wide name lookup,
but they fail in any consumer that doesn't replicate Obsidian's resolver:
external grep, multi-agent collaboration, plain-text search, etc. The
protocol recommends full-path wikilinks ([[wiki/projects/note-name]]) for
cross-scan-dir references — see OBSIDIAN-RAG-PROTOCOL.md §3.5.

This script reads vault-index.json to learn the path of every entry, then
walks the configured scan directories and rewrites unambiguous bare
wikilinks to full-path form. Ambiguous bare links (multiple candidates)
are reported, not rewritten — manual disambiguation needed.

USAGE:
    # Dry-run preview (no writes)
    python3 convert_bare_to_fullpath.py \
        --index ~/.hermes/vault-index.json \
        --vault ~/Documents/MyVault \
        --scan wiki/concepts wiki/projects \
        --dry

    # Apply
    python3 convert_bare_to_fullpath.py \
        --index ~/.hermes/vault-index.json \
        --vault ~/Documents/MyVault \
        --scan wiki/concepts wiki/projects

KEY DESIGN DECISIONS:
- Reads vault-index.json directly for the stem → path map. No vault rescan.
- Skips bare wikilinks on lines containing placeholder markers ("待写",
  "作成予定", "TODO", "未作成") — those are intentional concept stubs that
  signal "click to create" affordance in Obsidian.
- Skips fenced code blocks (skill docs, READMEs commonly contain wikilink
  syntax examples).
- Preserves pipe aliases ([[target|display]] → [[full/path|display]]) and
  anchor refs ([[target#section]] → [[full/path#section]]).
- Ambiguous targets (multiple candidates with same stem) are flagged for
  manual review, never auto-rewritten — silent disambiguation would be
  worse than a noisy report.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")
PLACEHOLDER_MARKERS = ("待写", "作成予定", "TODO", "todo", "未作成")


def build_stem_map(vault: Path) -> dict:
    """Map filename stem → list of relative paths in the vault.

    Used to resolve bare wikilinks. Multiple paths for the same stem means
    the bare link is ambiguous and we refuse to auto-rewrite.
    """
    stem_map = defaultdict(list)
    for md in vault.rglob("*.md"):
        rel = md.relative_to(vault)
        # Skip raw-sources / archived dumps that shouldn't be link targets
        if "raw-sources" in rel.parts:
            continue
        stem_map[md.stem].append(rel)
    return stem_map


def split_lines_skip_fences(text: str):
    """Yield (line_no, line) for each line, skipping fenced code blocks."""
    in_fence = False
    for ln, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield ln, line


def resolve_link(target: str, stem_map: dict, source_path: Path, vault: Path):
    """Return (chosen_relative_path, ambiguous_candidates_or_none).

    Disambiguation prefers a same-parent-dir candidate when the bare link
    happens to match a sibling — common pattern in clustered notes.
    """
    candidates = stem_map.get(target, [])
    if not candidates:
        # Try Obsidian's case-insensitive / dashes-vs-spaces tolerance
        normalized = target.lower().replace(" ", "-")
        candidates = [
            p
            for stem, paths in stem_map.items()
            if stem.lower() == target.lower() or stem.lower() == normalized
            for p in paths
        ]
    if not candidates:
        return None, None
    if len(candidates) == 1:
        return candidates[0], None
    # Disambiguate: prefer same parent dir
    parent_rel = source_path.parent.relative_to(vault)
    same_parent = [c for c in candidates if c.parent == parent_rel]
    if len(same_parent) == 1:
        return same_parent[0], None
    return None, candidates


def process_file(path: Path, vault: Path, stem_map: dict, dry: bool):
    """Returns (changes, unresolved, ambiguous, applied_text_or_none)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0, [], [], None

    # Build a list of (start, end, new_link) replacements; apply in reverse.
    # We need char offsets, so we work on the raw text but consult line-skip
    # logic via a fence-tracking pass.
    in_fence = False
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def char_offset_in_fence(offset: int) -> bool:
        """Re-derive fence state at a given char offset."""
        in_fence_local = False
        for line_start in line_starts:
            if line_start > offset:
                break
            line_end = text.find("\n", line_start)
            line = text[line_start : line_end if line_end != -1 else len(text)]
            if line.lstrip().startswith("```") and line_start <= offset < (line_end if line_end != -1 else len(text)):
                # Cursor is on the fence-marker line itself
                return True
            if line.lstrip().startswith("```"):
                in_fence_local = not in_fence_local
        return in_fence_local

    replacements = []
    unresolved = []
    ambiguous = []

    for m in WIKILINK_RE.finditer(text):
        link = m.group(1)
        # Parse pipe (display alias) and anchor
        target_part, _, display_part = link.partition("|")
        target_only, _, anchor = target_part.partition("#")
        target = target_only.strip()

        # Skip if already full path
        if "/" in target:
            continue

        # Skip if inside a fenced code block
        if char_offset_in_fence(m.start()):
            continue

        # Skip if line has a placeholder marker (intentional stub)
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start : line_end if line_end != -1 else len(text)]
        if any(marker in line for marker in PLACEHOLDER_MARKERS):
            continue

        chosen, multi = resolve_link(target, stem_map, path, vault)
        if chosen is None and multi is None:
            unresolved.append((m.group(0), target))
            continue
        if chosen is None and multi:
            ambiguous.append((m.group(0), target, [str(c) for c in multi]))
            continue

        # Build new wikilink. Strip .md from path; keep anchor + display.
        full_path = str(chosen.with_suffix(""))
        new_target = full_path + (("#" + anchor) if anchor else "")
        new_link = f"[[{new_target}|{display_part}]]" if display_part else f"[[{new_target}]]"

        replacements.append((m.start(), m.end(), new_link))

    if not replacements:
        return 0, unresolved, ambiguous, None

    # Apply replacements in reverse order to keep offsets stable
    new_text = text
    for start, end, new_link in sorted(replacements, key=lambda r: -r[0]):
        new_text = new_text[:start] + new_link + new_text[end:]

    if dry:
        return len(replacements), unresolved, ambiguous, None
    return len(replacements), unresolved, ambiguous, new_text


def main():
    parser = argparse.ArgumentParser(
        description="Convert bare wikilinks to full-path form, using the ORP index for resolution.",
    )
    parser.add_argument("--index", required=True,
                        help="Path to vault-index.json (used as the stem→path source).")
    parser.add_argument("--vault", required=True,
                        help="Vault root.")
    parser.add_argument("--scan", nargs="+", required=True,
                        help="Subdirectories (relative to vault) to scan and rewrite.")
    parser.add_argument("--dry", action="store_true",
                        help="Preview replacements without writing.")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.exists():
        print(f"ERROR: vault not found: {vault}", file=sys.stderr)
        return 1

    # Build stem map from filesystem (includes paths the index may not list,
    # and tolerates index staleness).
    stem_map = build_stem_map(vault)

    total_changes = 0
    files_touched = 0
    all_unresolved = defaultdict(list)
    all_ambiguous = defaultdict(list)

    for scan in args.scan:
        scan_root = vault / scan
        if not scan_root.exists():
            print(f"[skip] scan dir not found: {scan_root}", file=sys.stderr)
            continue
        for md in scan_root.rglob("*.md"):
            if md.name == "log.md":
                continue
            n_changes, unresolved, ambiguous, new_text = process_file(
                md, vault, stem_map, args.dry
            )
            if n_changes:
                files_touched += 1
                total_changes += n_changes
                rel = md.relative_to(vault)
                if args.dry:
                    print(f"[dry] {rel}: {n_changes} link(s) to rewrite")
                else:
                    md.write_text(new_text, encoding="utf-8")
                    print(f"[wrote] {rel}: {n_changes} link(s)")
            for full, target in unresolved:
                all_unresolved[str(md.relative_to(vault))].append(target)
            for full, target, cands in ambiguous:
                all_ambiguous[str(md.relative_to(vault))].append((target, cands))

    print("\n--- summary ---", file=sys.stderr)
    print(f"  files touched: {files_touched}", file=sys.stderr)
    print(f"  total link replacements: {total_changes}", file=sys.stderr)
    print(f"  unresolved (target not found): {sum(len(v) for v in all_unresolved.values())}", file=sys.stderr)
    print(f"  ambiguous (multiple candidates): {sum(len(v) for v in all_ambiguous.values())}", file=sys.stderr)

    if all_ambiguous:
        print("\n  Ambiguous bare wikilinks (manual review needed):", file=sys.stderr)
        for f, items in list(all_ambiguous.items())[:5]:
            for target, cands in items[:3]:
                print(f"    {f} → [[{target}]]  candidates: {cands}", file=sys.stderr)
    if all_unresolved and not args.dry:
        print("\n  Unresolved (target file missing — likely stale or intentional placeholder):", file=sys.stderr)
        for f, targets in list(all_unresolved.items())[:5]:
            for target in targets[:3]:
                print(f"    {f} → [[{target}]]", file=sys.stderr)

    if not args.dry and total_changes:
        print("\nNext step: run rebuild-vault-index.py to refresh the index.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
