#!/usr/bin/env python3
"""
orp_link_check.py — Wikilink and path-reference scanner for ORP vaults.

Scans a directory of markdown files for Obsidian-style wikilinks
(`[[path/to/note]]`) and inline-code path references (`` `wiki/note.md` ``),
resolves each reference against a vault root, and reports:

  - Dead links: references pointing to files that don't exist
  - Live links: references pointing to existing files
  - Orphans: vault files not referenced anywhere

This is the conformance check for protocol §6 (Skill ↔ Vault auto-expansion).
If your skill files reference vault notes that no longer exist, agents
auto-loading those wikilinks will fail silently — this catches that.

Stdlib only.

USAGE:
    # Scan a vault for internal-link integrity
    python3 orp_link_check.py --vault ~/Documents/MyVault

    # Scan a separate skills directory referencing the vault
    python3 orp_link_check.py --vault ~/Documents/MyVault --scan ~/.hermes/skills

    # JSON output for CI / cron
    python3 orp_link_check.py --vault ~/Documents/MyVault --json

EXIT CODES:
    0  no dead links
    1  one or more dead links found
"""

import argparse
import json
import re
import sys
from pathlib import Path


# [[wikilink]] — Obsidian internal link, possibly with #anchor or |alias
RE_WIKILINK = re.compile(r"\[\[([^\[\]\|#]+?)(?:#[^\[\]\|]*)?(?:\|[^\[\]]*)?\]\]")

# Inline-code path reference: `wiki/foo.md` or `hermes-knowledge/bar`
RE_INLINE_PATH = re.compile(
    r"`((?:wiki|hermes-knowledge)/[A-Za-z0-9_/\-]+(?:\.md)?)`"
)

# Template variables we should not flag as dead — they're meant to be expanded
TEMPLATE_VAR = re.compile(r"\{[a-z_][a-z0-9_-]*\}", re.IGNORECASE)


def is_template(ref: str) -> bool:
    """A ref containing {date} / {timestamp} etc. is intentional, not dead."""
    return bool(TEMPLATE_VAR.search(ref))


def is_directory_ref(vault: Path, ref: str) -> bool:
    """A ref ending with `/` or pointing at an existing directory is intentional."""
    if ref.endswith("/"):
        return True
    candidate = vault / ref
    return candidate.is_dir()


def resolve(vault: Path, ref: str) -> Path:
    """Resolve a ref to a candidate file path, adding .md if missing."""
    rel = ref.strip().lstrip("/")
    candidate = vault / rel
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    return candidate


def scan_file(path: Path):
    """Yield (line_number, ref) for every wikilink / inline-path in the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    for ln, line in enumerate(text.splitlines(), start=1):
        for m in RE_WIKILINK.finditer(line):
            yield ln, m.group(1).strip()
        for m in RE_INLINE_PATH.finditer(line):
            yield ln, m.group(1).strip()


def collect_vault_files(vault: Path):
    """All .md files under vault root, as Path objects."""
    return [p for p in vault.rglob("*.md") if p.is_file()]


def run(vault: Path, scan_roots, ignore_orphans: bool):
    """Scan and return a structured report."""
    if not vault.exists():
        return {"error": f"vault not found: {vault}", "dead": [], "live": [], "orphans": []}

    dead = []
    live = []
    referenced_files = set()

    sources = list(scan_roots) if scan_roots else [vault]
    md_files = []
    for root in sources:
        if not root.exists():
            continue
        md_files.extend(p for p in root.rglob("*.md") if p.is_file())

    for src in md_files:
        for ln, ref in scan_file(src):
            if is_template(ref) or is_directory_ref(vault, ref):
                continue
            target = resolve(vault, ref)
            entry = {"source": str(src), "line": ln, "ref": ref,
                     "resolved": str(target)}
            if target.exists():
                live.append(entry)
                referenced_files.add(target.resolve())
            else:
                dead.append(entry)

    orphans = []
    if not ignore_orphans:
        for vf in collect_vault_files(vault):
            if vf.resolve() not in referenced_files:
                orphans.append(str(vf))

    return {"vault": str(vault), "dead": dead, "live": live, "orphans": orphans}


def main():
    parser = argparse.ArgumentParser(
        description="Wikilink / path-reference scanner for ORP vaults",
    )
    parser.add_argument("--vault", required=True,
                        help="Vault root (resolves all refs against this)")
    parser.add_argument("--scan", action="append",
                        help="Additional directories to scan for refs (e.g. a skills dir). "
                             "Repeatable. Defaults to scanning the vault itself.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of human-readable output")
    parser.add_argument("--ignore-orphans", action="store_true",
                        help="Skip orphan detection (faster, less noisy)")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    scan_roots = [Path(p).expanduser().resolve() for p in (args.scan or [])]

    report = run(vault, scan_roots, args.ignore_orphans)

    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        dead = report["dead"]
        live = report["live"]
        orphans = report["orphans"]
        print(f"Vault: {report['vault']}")
        print(f"  Live links: {len(live)}")
        print(f"  Dead links: {len(dead)}")
        if not args.ignore_orphans:
            print(f"  Orphan files (no inbound refs): {len(orphans)}")
        if dead:
            print("")
            print("Dead links:")
            for d in dead[:50]:
                print(f"  {d['source']}:{d['line']}  →  {d['ref']}  (expected: {d['resolved']})")
            if len(dead) > 50:
                print(f"  ... and {len(dead) - 50} more")

    sys.exit(1 if report["dead"] else 0)


if __name__ == "__main__":
    main()
