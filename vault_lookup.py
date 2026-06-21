#!/usr/bin/env python3
"""
vault_lookup.py — Unified vault retrieval entry point + fail-improve logger.

Orchestrates the two-layer retrieval ladder (alias via orp_reader, semantic via
vault_vec) and logs every gap where alias missed but vec recovered. This is the
"system gets smarter on its own" pattern from Gbrain (intent classifier
deterministic % from failures).

Single command for Claude Code to call instead of remembering the cascade:

    python3 vault_lookup.py search "<query>" [-k 5] [--no-log] [--format json|paths]
    python3 vault_lookup.py backlinks <target> [--include-status all] [--format json|paths]
    python3 vault_lookup.py review [--since 7d] [--top 20]
    python3 vault_lookup.py status

Output schema (search, --format json):
    {
      "query": "...",
      "alias": {"exit": 0|1|2|3, "hits": [{path, label}]},
      "vec":   {"exit": 0|1|2|3, "hits": [{path, score, source, headers}]},
      "gap_detected": bool,           # alias missed but vec recovered
      "recommendation": "alias_hit" | "vec_recovery" | "all_miss"
    }

Log format (~/.claude/data/orp-misses.jsonl, JSONL append-only):
    {"ts": "...", "query": "...", "alias_exit": 1, "alias_count": 0,
     "vec_count": 5, "gap": true, "vec_winners": [...top 3...]}

Exit codes:
    0 hit (alias / vec / backlinks)
    1 all miss / no backlinks (Claude should fall to grep)
    2 system error (index missing, etc.)

Backlinks design notes:
    Stateless (no third index). Walks vault on each call. ~800 entries → ms-range.
    Mixed resolver: accepts basename ("notebooklm-handoff-playbook") OR full
    vault-relative path ("wiki/concepts/X.md"). Cross-namespace (wiki/ +
    hermes-knowledge/ both scanned, addresses v1.5.1 namespace split).
    Default skips referrers with status=archived/stale (same as vault_vec).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ORP_READER = Path.home() / '.hermes' / 'scripts' / 'orp_reader.py'
VAULT_VEC = Path(__file__).resolve().parent / 'vault_vec.py'
LOG_DIR = Path.home() / '.claude' / 'data'
LOG_PATH = LOG_DIR / 'orp-misses.jsonl'


# ---------- RRF fusion ----------

RRF_K = 60  # standard rank smoothing constant (Cormack 2009)


def fuse_results(alias_hits, vec_hits, top_k):
    """Reciprocal Rank Fusion across alias and vec rankers.

    score(path) = sum over rankers r of 1 / (RRF_K + rank_r(path))

    A path present in both rankers gets summed → boosted naturally.
    A path in only one ranker gets a partial score → still surfaces.
    Returns sorted list of dicts with rrf_score + provenance for each path.
    """
    by_path = {}

    for rank, h in enumerate(alias_hits, start=1):
        p = h.get('path', '')
        if not p:
            continue
        e = by_path.setdefault(p, {'path': p, 'sources': [], 'rrf_score': 0.0})
        if 'alias' not in e['sources']:
            e['sources'].append('alias')
            e['alias_rank'] = rank
            e['rrf_score'] += 1.0 / (RRF_K + rank)
            if h.get('label'):
                e['alias_label'] = h['label']

    for rank, h in enumerate(vec_hits, start=1):
        p = h.get('path', '')
        if not p:
            continue
        e = by_path.setdefault(p, {'path': p, 'sources': [], 'rrf_score': 0.0})
        if 'vec' not in e['sources']:
            e['sources'].append('vec')
            e['vec_rank'] = rank
            e['vec_score'] = h.get('score')
            e['vec_source'] = h.get('source')
            e['vec_status'] = h.get('status')  # v1.5.1 C3
            e['rrf_score'] += 1.0 / (RRF_K + rank)

    fused = sorted(by_path.values(), key=lambda x: -x['rrf_score'])[:top_k]
    # Round RRF score for display sanity
    for e in fused:
        e['rrf_score'] = round(e['rrf_score'], 5)
    return fused


# ---------- Layer 1: orp_reader.py wrapper ----------

def run_orp_reader(query):
    """Run orp_reader.py match. Returns {exit, hits: [{path, label}]}."""
    if not ORP_READER.exists():
        return {'exit': 2, 'hits': [], 'error': 'orp_reader.py missing'}
    try:
        r = subprocess.run(
            ['python3', str(ORP_READER), 'match', query],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {'exit': 2, 'hits': [], 'error': 'timeout'}
    except Exception as e:
        return {'exit': 2, 'hits': [], 'error': str(e)}

    hits = []
    for line in r.stdout.splitlines():
        # Format: "entry_id\t/abs/path\t[matched: alias]"
        parts = line.split('\t')
        if len(parts) >= 2:
            label = ''
            if len(parts) >= 3:
                m = re.search(r'\[matched:\s*(.+)\]', parts[2])
                if m:
                    label = m.group(1).strip()
            hits.append({'path': parts[1], 'entry_id': parts[0], 'label': label})
    return {'exit': r.returncode, 'hits': hits}


# ---------- Layer 2: vault_vec.py wrapper ----------

def run_vault_vec(query, top_k, threshold, include_status=None):
    """Run vault_vec.py search --format json. Returns {exit, hits}.

    v1.5.1 C3: optional include_status passthrough (None = vault_vec default,
    which excludes stale + archived).
    """
    if not VAULT_VEC.exists():
        return {'exit': 2, 'hits': [], 'error': 'vault_vec.py missing'}
    cmd = ['python3', str(VAULT_VEC), 'search', query,
           '-k', str(top_k), '-t', str(threshold), '--format', 'json']
    if include_status:
        cmd.extend(['--include-status', include_status])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {'exit': 2, 'hits': [], 'error': 'timeout'}
    except Exception as e:
        return {'exit': 2, 'hits': [], 'error': str(e)}

    hits = []
    if r.returncode == 0 and r.stdout.strip():
        try:
            hits = json.loads(r.stdout)
        except json.JSONDecodeError:
            pass
    return {'exit': r.returncode, 'hits': hits}


# ---------- Gap logger ----------

OVERBROAD_MIN = 30   # alias_count >= this → query fanned out too wide (precision signal)


def log_outcome(query, alias, vec, gap, fused=None):
    """Append a JSONL line. Never crashes — logging best-effort."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        alias_count = len(alias['hits'])
        record = {
            'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'query': query,
            'alias_exit': alias['exit'],
            'alias_count': alias_count,
            'alias_labels': [h.get('label', '') for h in alias['hits'][:5] if h.get('label')],
            'vec_count': len(vec['hits']),
            'gap': gap,
            # precision instrumentation: over-broad alias fan-out is the dominant
            # failure mode the gap flag (alias-miss only) is structurally blind to.
            'alias_overbroad': alias_count >= OVERBROAD_MIN,
        }
        # Record fused top-3 on EVERY line (not just gap lines) so retrieval
        # quality (top-k, not just hit/miss) is measurable from the log alone.
        # `is not None` not truthiness: an all-miss line (fused == []) still gets
        # `fused_top3: []` so the schema is consistent across every record.
        if fused is not None:
            record['fused_top3'] = [
                {'rrf_score': round(e.get('rrf_score', 0), 5),
                 'sources': e.get('sources'), 'path': e.get('path')}
                for e in fused[:3]
            ]
        if gap and vec['hits']:
            record['vec_winners'] = [
                {'score': h.get('score'), 'path': h.get('path'),
                 'source': h.get('source'), 'rel_path': h.get('rel_path')}
                for h in vec['hits'][:3]
            ]
        with LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'WARN: failed to log outcome: {e}', file=sys.stderr)


# ---------- search command ----------

def cmd_search(query, top_k, threshold, no_log, fmt, include_status=None):
    # Pull more from each ranker than top_k so RRF has range to fuse
    alias = run_orp_reader(query)
    vec = run_vault_vec(query, max(top_k * 2, 10), threshold, include_status)

    alias_hit = alias['exit'] == 0 and len(alias['hits']) > 0
    vec_hit = vec['exit'] == 0 and len(vec['hits']) > 0
    gap = (not alias_hit) and vec_hit

    if alias_hit:
        rec = 'alias_hit'
    elif vec_hit:
        rec = 'vec_recovery'
    else:
        rec = 'all_miss'

    fused = fuse_results(alias['hits'], vec['hits'], top_k)

    if not no_log:
        log_outcome(query, alias, vec, gap, fused)

    result = {
        'query': query,
        'recommendation': rec,
        'gap_detected': gap,
        'fused': fused,
        'alias': alias,
        'vec': vec,
    }

    if fmt == 'json':
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:  # paths
        if rec == 'all_miss':
            print(f'# query: {query}  recommendation: all_miss', file=sys.stderr)
            print('(no hits — fall to grep)', file=sys.stderr)
        else:
            print(f'# query: {query}  recommendation: {rec}  fused_top={len(fused)}')
            for e in fused:
                tag = '+'.join(e['sources'])
                # v1.5.1 C3: include status tag when known (from vec layer)
                status = e.get('vec_status')
                src_marker = f"[{tag}/{status}]" if status else f"[{tag}]"
                detail_parts = []
                if 'alias_rank' in e:
                    detail_parts.append(f"alias_rank={e['alias_rank']}")
                if 'vec_rank' in e:
                    detail_parts.append(f"vec={e['vec_rank']}/{e.get('vec_score', 0):.3f}")
                if e.get('vec_source') and e['vec_source'] != 'vault':
                    detail_parts.append(f"src={e['vec_source']}")
                detail = ' '.join(detail_parts)
                label = f"  [alias: {e['alias_label']}]" if e.get('alias_label') else ''
                print(f"{e['rrf_score']:.5f}  {src_marker:24s}  {detail:38s}  {e['path']}{label}")
            if gap:
                print('# ⚠ gap_detected: alias missed but vec recovered — logged for review', file=sys.stderr)

    return 1 if rec == 'all_miss' else 0


# ---------- backlinks command ----------

WIKILINK_RE = re.compile(r'\[\[([^\]\n]+?)\]\]')


def _normalize_link(raw):
    """Strip |display, #heading, ^block from raw [[...]] content."""
    s = raw.strip()
    if '|' in s:
        s = s.split('|', 1)[0].strip()
    for sep in ('#', '^'):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    s = s.lstrip('./').lstrip('/')
    if s.endswith('.md'):
        s = s[:-3]
    return s


def _walk_vault(vault, exclude_dirs):
    """Yield (abs_path, rel_path_str) for every .md under vault."""
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]
        for f in files:
            if not f.endswith('.md') or f.startswith('.'):
                continue
            abs_p = Path(root) / f
            yield abs_p, str(abs_p.relative_to(vault))


def resolve_target(target):
    """Resolve user input → match-set + canonical paths.

    Accepts:
      basename: "notebooklm-handoff-playbook"
      basename with .md: "notebooklm-handoff-playbook.md"
      full vault-rel path: "wiki/concepts/dev-tools/notebooklm-handoff-playbook.md"

    Returns dict with input, basename, canonical_paths (list of vault-rel),
    ambiguous (bool: basename matches >1 file).
    """
    from vault_vec import VAULT, EXCLUDE_DIRS  # type: ignore[import-not-found]

    t = target.strip().lstrip('/')
    if t.endswith('.md'):
        t = t[:-3]
    is_full_path = '/' in t
    basename = t.rsplit('/', 1)[-1] if is_full_path else t

    canonical_paths = []
    for abs_p, rel in _walk_vault(VAULT, EXCLUDE_DIRS):
        stem = abs_p.stem
        if stem != basename:
            continue
        rel_stem = rel[:-3] if rel.endswith('.md') else rel
        if is_full_path and rel_stem != t:
            continue
        canonical_paths.append(rel)

    return {
        'input': target,
        'basename': basename,
        'canonical_paths': canonical_paths,
        'ambiguous': len(canonical_paths) > 1 and not is_full_path,
    }


def find_backlinks(target_info, include_status=None):
    """Scan vault for [[...]] referring to target. Returns list of referrers."""
    from vault_vec import VAULT, EXCLUDE_DIRS, extract_status, DEFAULT_INCLUDED_STATUS  # type: ignore[import-not-found]

    basename = target_info['basename']
    canonical_set = set(target_info['canonical_paths'])
    canonical_stems = {p[:-3] if p.endswith('.md') else p for p in canonical_set}

    if include_status == 'all':
        allowed = None
    elif include_status:
        allowed = {s.strip().lower() for s in include_status.split(',') if s.strip()}
    else:
        # Default: the §1.2 live set (captured/candidate/verified/retrievable) — skip
        # archived/stale. extract_status maps missing/unrecognized → captured (live), so
        # un-statused referrers stay included. v1.7.1: was {'verified','draft'} ('draft'
        # is not a valid §1.2 status, and it dropped captured/candidate/retrievable).
        allowed = set(DEFAULT_INCLUDED_STATUS)

    referrers = []
    for abs_p, rel in _walk_vault(VAULT, EXCLUDE_DIRS):
        if rel in canonical_set:
            continue
        try:
            text = abs_p.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        if '[[' not in text:
            continue
        status = extract_status(text)
        if allowed is not None and status not in allowed:
            continue

        file_links = []
        for line_idx, line in enumerate(text.splitlines(), start=1):
            for m in WIKILINK_RE.finditer(line):
                raw = m.group(1)
                norm = _normalize_link(raw)
                if not norm:
                    continue
                norm_base = norm.rsplit('/', 1)[-1] if '/' in norm else norm
                # Match if normalized link equals a canonical path stem,
                # OR if it's a bare basename matching ours
                hit = (norm in canonical_stems) or (norm_base == basename and '/' not in norm)
                if hit:
                    file_links.append({
                        'line': line_idx,
                        'link_form': f'[[{raw}]]',
                        'normalized': norm,
                    })
        if file_links:
            referrers.append({
                'path': str(abs_p),
                'rel_path': rel,
                'status': status,
                'links': file_links,
            })

    referrers.sort(key=lambda r: r['rel_path'])
    return referrers


def cmd_backlinks(target, include_status, fmt):
    info = resolve_target(target)
    referrers = find_backlinks(info, include_status)
    total_links = sum(len(r['links']) for r in referrers)

    if fmt == 'json':
        print(json.dumps({
            'target': info['input'],
            'resolved': info,
            'referrers': referrers,
            'count_referrers': len(referrers),
            'count_links': total_links,
        }, indent=2, ensure_ascii=False))
    else:
        print(f"# backlinks for: {target}")
        if not info['canonical_paths']:
            print(f"# ⚠ target not found in vault — scanning for dangling [[{info['basename']}]] refs")
        else:
            for cp in info['canonical_paths']:
                print(f"# canonical: {cp}")
            if info['ambiguous']:
                print(f"# ⚠ ambiguous: '{info['basename']}' matches {len(info['canonical_paths'])} files — backlinks merged")
        print(f"# {len(referrers)} referrer(s), {total_links} total link(s)")
        if include_status:
            print(f"# status filter: {include_status}")
        print()
        if not referrers:
            print("(no backlinks — fall to grep if uncertain)", file=sys.stderr)
        else:
            for r in referrers:
                print(f"[{r['status']:8s}] {r['rel_path']}")
                for link in r['links']:
                    print(f"           L{link['line']:>4d}  {link['link_form']}")

    return 0 if referrers else 1


# ---------- review command ----------

_DURATION_RE = re.compile(r'^(\d+)([dhmw])$')

def parse_since(s):
    if not s:
        return None
    m = _DURATION_RE.match(s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {'d': timedelta(days=n), 'h': timedelta(hours=n),
             'm': timedelta(minutes=n), 'w': timedelta(weeks=n)}[unit]
    return datetime.now(timezone.utc) - delta


def cmd_review(since, top_n):
    if not LOG_PATH.exists():
        print(f'No log at {LOG_PATH}. Run some queries first.', file=sys.stderr)
        return 1

    cutoff = parse_since(since)
    records = []
    total = 0
    with LOG_PATH.open(encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            if cutoff:
                try:
                    ts = datetime.fromisoformat(r['ts'])
                    if ts < cutoff:
                        continue
                except Exception:
                    continue
            records.append(r)

    if not records:
        print(f'No records in window. Total in log: {total}', file=sys.stderr)
        return 1

    n_total = len(records)
    n_alias_hit = sum(1 for r in records if r.get('alias_count', 0) > 0)
    n_vec_hit = sum(1 for r in records if r.get('vec_count', 0) > 0)
    n_gap = sum(1 for r in records if r.get('gap'))
    n_allmiss = sum(1 for r in records if r.get('alias_count', 0) == 0 and r.get('vec_count', 0) == 0)

    print(f'=== ORP retrieval review (window: {since or "all"}) ===')
    print(f'Total lookups: {n_total}')
    print(f'  alias_hit rate:    {n_alias_hit:>4}  ({n_alias_hit / n_total * 100:.0f}%)')
    print(f'  vec_hit  rate:    {n_vec_hit:>4}  ({n_vec_hit / n_total * 100:.0f}%)')
    print(f'  GAP (alias miss, vec saved): {n_gap}  ({n_gap / n_total * 100:.0f}%)   ← candidates for alias additions')
    print(f'  all_miss rate:    {n_allmiss:>4}  ({n_allmiss / n_total * 100:.0f}%)')
    print()

    # Group gap queries by top vec winner, split by source (vault vs memory)
    vault_targets = {}    # alias-actionable
    memory_targets = {}   # vec-only by design
    for r in records:
        if not r.get('gap'):
            continue
        winners = r.get('vec_winners', [])
        if not winners:
            continue
        top = winners[0]
        path_key = top.get('rel_path') or top.get('path')
        bucket = vault_targets if top.get('source') == 'vault' else memory_targets
        bucket.setdefault(path_key, []).append(r['query'])

    if vault_targets:
        print(f'=== ACTIONABLE: vault gap targets (propose alias to Hermes) ===')
        ranked = sorted(vault_targets.items(), key=lambda kv: -len(kv[1]))[:top_n]
        for path, queries in ranked:
            print(f'\n[{len(queries)} miss(es)] → {path}')
            for q in queries[:6]:
                print(f'    "{q}"')
            if len(queries) > 6:
                print(f'    … +{len(queries) - 6} more')
        print()
    else:
        print('=== ACTIONABLE: vault gap targets — none ===\n')

    if memory_targets:
        n_mem_total = sum(len(v) for v in memory_targets.values())
        print(f'=== INFORMATIONAL: memory-only gaps ({n_mem_total} queries · vec is the right layer, alias cannot help) ===')
        ranked = sorted(memory_targets.items(), key=lambda kv: -len(kv[1]))[:top_n]
        for path, queries in ranked:
            print(f'\n[{len(queries)}] → {path}')
            for q in queries[:4]:
                print(f'    "{q}"')
            if len(queries) > 4:
                print(f'    … +{len(queries) - 4} more')
    return 0


# ---------- status command ----------

def cmd_status():
    print(f'orp_reader.py:  {"✓" if ORP_READER.exists() else "✗ MISSING"}  ({ORP_READER})')
    print(f'vault_vec.py:   {"✓" if VAULT_VEC.exists() else "✗ MISSING"}  ({VAULT_VEC})')
    print(f'miss log:       {LOG_PATH}')
    if LOG_PATH.exists():
        try:
            lines = LOG_PATH.read_text(encoding='utf-8').splitlines()
            print(f'  total records: {len(lines)}')
            print(f'  size: {LOG_PATH.stat().st_size:,} bytes')
            if lines:
                last = json.loads(lines[-1])
                print(f'  last entry:    {last.get("ts")}')
        except Exception as e:
            print(f'  (read error: {e})')
    else:
        print('  (no log yet)')
    return 0


# ---------- doctor command (unified health rollup) ----------
#
# ORP has 3 maintained retrieval/telemetry subsystems that previously each had
# their own `status` command (vault_lookup / vault_vec / orp_reader). Checking
# health meant running 3 separate commands — the fragmentation that let the vec
# layer silently rot 10.8d (2026-06-03 checkpoint). `doctor` rolls all 3 into one
# read with staleness thresholds, so degradation is visible at a glance.
#
# Boundary note (v1.7 design principle): ORP owns the health CONTRACT + the
# refresh COMMANDS; the deployment layer (Hermes cron / launchd) owns WHEN they
# run. doctor is the alarm; the scheduled `vault_vec.py update` is the auto-fix.

VEC_AGE_WARN_DAYS = 3.0       # vec index older than this → stale (vault drifts ~1/3 per 10d)
VEC_DRIFT_WARN = 25          # |on-disk − indexed| files before flagging drift
ALIAS_AGE_WARN_HOURS = 36.0   # alias index rebuilds daily; >36h = a rebuild was missed
GAP_ALLMISS_WARN = 0.05       # 7d all_miss rate above this → retrieval degrading
GAP_OVERBROAD_WARN = 0.20     # 7d over-broad (alias_count≥OVERBROAD_MIN) rate above this → alias precision degrading
GAP_MIN_VOLUME = 20           # gap-rate warnings need ≥ this many lookups; below it a single miss already blows past 5% (1/8=12%) — pure small-sample noise, not degradation


def _vec_health():
    """Vec/semantic layer health via direct import (no numpy load, no API)."""
    out = {'layer': 'vec', 'ok': True}
    try:
        import vault_vec as vv
    except Exception as e:
        return {'layer': 'vec', 'ok': False, 'error': f'import vault_vec failed: {e}'}
    if not vv.VEC_PATH.exists() or not vv.META_PATH.exists():
        return {'layer': 'vec', 'ok': False, 'error': 'index missing (run `vault_vec.py index`)'}
    try:
        meta = json.loads(vv.META_PATH.read_text())
        out['entries'] = len(meta)
        out['age_days'] = (time.time() - vv.VEC_PATH.stat().st_mtime) / 86400
        # §7.5 drift = eligible-but-missing BY PATH (set difference), mirroring
        # vault_vec.status() — NOT a count delta. abs(on_disk - len(meta)) nets to
        # zero when an add and a stale/deleted row cancel out, masking the rename/
        # move drift the gate must catch. Legacy rows w/o abs_path fall back to
        # rel_path → won't match a disk abs path → counted missing (fail-safe:
        # over-reports, triggering a harmless rebuild, never under-reports).
        disk_paths = {str(abs_path) for _, abs_path, _ in vv.find_markdown_files()}
        indexed_paths = {m.get('abs_path') or m.get('rel_path') for m in meta}
        out['on_disk'] = len(disk_paths)
        out['drift'] = len(disk_paths - indexed_paths)
        level, msg = vv.check_model_compat()
        out['model_level'] = level          # ok / no_sidecar / soft / hard
        out['model_msg'] = msg
        about = vv.read_about()
        out['model'] = about.get('embedding_model') if about else None
    except Exception as e:
        out['ok'] = False
        out['error'] = str(e)
    return out


_TZ_OFFSET_RE = re.compile(r'([+-]\d{2})(\d{2})$')


def _parse_ts(s):
    """Robust ISO parse — tolerate ±HHMM offsets (orp_reader emits +0900, no colon).

    datetime.fromisoformat only accepts ±HH:MM before Python 3.11. Normalize first.
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        fixed = _TZ_OFFSET_RE.sub(r'\1:\2', s)
        try:
            return datetime.fromisoformat(fixed)
        except ValueError:
            return None


def _alias_health():
    """Alias/keyword layer health by parsing `orp_reader.py status` text."""
    out = {'layer': 'alias', 'ok': False}
    if not ORP_READER.exists():
        out['error'] = 'orp_reader.py missing'
        return out
    try:
        r = subprocess.run(['python3', str(ORP_READER), 'status'],
                           capture_output=True, text=True, timeout=10)
    except Exception as e:
        out['error'] = str(e)
        return out
    txt = (r.stdout or '').strip()
    out['ok'] = r.returncode == 0
    out['raw'] = txt
    m = re.search(r'(\d+)\s+entries', txt)
    if m:
        out['entries'] = int(m.group(1))
    m = re.search(r'updated\s+([0-9T:+\-]+)', txt)
    if m:
        out['updated'] = m.group(1)
        ts = _parse_ts(out['updated'])
        if ts is not None:
            out['age_hours'] = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    out['fresh'] = 'fresh' in txt and 'stale' not in txt
    return out


def _gap_health(days=7):
    """Gap-log telemetry health: recent volume + all_miss rate."""
    out = {'layer': 'gap', 'ok': True, 'window_days': days, 'records': 0,
           'recent': 0, 'all_miss': 0, 'all_miss_rate': 0.0,
           'overbroad': 0, 'overbroad_rate': 0.0}
    if not LOG_PATH.exists():
        return out
    try:
        lines = LOG_PATH.read_text(encoding='utf-8').splitlines()
    except Exception as e:
        out['ok'] = False
        out['error'] = str(e)
        return out
    out['records'] = len(lines)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for ln in lines:
        try:
            rr = json.loads(ln)
            if datetime.fromisoformat(rr['ts']) >= cutoff:
                recent.append(rr)
        except Exception:
            continue
    out['recent'] = len(recent)
    out['all_miss'] = sum(1 for r in recent
                          if r.get('alias_count', 0) == 0 and r.get('vec_count', 0) == 0)
    out['all_miss_rate'] = (out['all_miss'] / len(recent)) if recent else 0.0
    out['overbroad'] = sum(1 for r in recent if r.get('alias_overbroad'))
    out['overbroad_rate'] = (out['overbroad'] / len(recent)) if recent else 0.0
    if lines:
        try:
            out['last_ts'] = json.loads(lines[-1]).get('ts')
        except Exception:
            pass
    return out


def cmd_doctor(fmt='text', window=7):
    vec = _vec_health()
    alias = _alias_health()
    gap = _gap_health(window)

    warnings = []   # (layer, message, fix)
    criticals = []  # (layer, message, fix)

    # --- vec layer verdict ---
    if not vec.get('ok'):
        criticals.append(('vec', vec.get('error', 'unknown error'), 'python3 vault_vec.py index'))
    else:
        if vec.get('model_level') == 'hard':
            criticals.append(('vec', f"model mismatch: {vec.get('model_msg')}", 'python3 vault_vec.py index'))
        elif vec.get('model_level') == 'soft':
            warnings.append(('vec', f"soft model mismatch: {vec.get('model_msg')}", 'rebuild when convenient'))
        if vec.get('age_days', 0) > VEC_AGE_WARN_DAYS:
            warnings.append(('vec', f"index stale {vec['age_days']:.1f}d (>{VEC_AGE_WARN_DAYS:.0f}d)",
                             'python3 vault_vec.py update'))
        if vec.get('drift', 0) > VEC_DRIFT_WARN:
            warnings.append(('vec', f"drift {vec['drift']} files (>{VEC_DRIFT_WARN})",
                             'python3 vault_vec.py update'))

    # --- alias layer verdict ---
    if not alias.get('ok'):
        criticals.append(('alias', alias.get('error', 'status failed'), 'check orp_reader.py'))
    elif alias.get('age_hours') is not None and alias['age_hours'] > ALIAS_AGE_WARN_HOURS:
        warnings.append(('alias', f"index {alias['age_hours']:.0f}h old (>{ALIAS_AGE_WARN_HOURS:.0f}h — daily rebuild may have failed)",
                         'check vault-index-rebuild cron'))

    # --- gap telemetry verdict ---
    if not gap.get('ok'):
        warnings.append(('gap', gap.get('error', 'log read failed'), 'check orp-misses.jsonl'))
    elif gap.get('recent', 0) >= GAP_MIN_VOLUME and gap.get('all_miss_rate', 0) > GAP_ALLMISS_WARN:
        warnings.append(('gap', f"all_miss {gap['all_miss_rate']*100:.0f}% over {window}d (>{GAP_ALLMISS_WARN*100:.0f}%) — retrieval degrading",
                         'review gaps: vault_lookup.py review'))
    if gap.get('ok') and gap.get('recent', 0) >= GAP_MIN_VOLUME and gap.get('overbroad_rate', 0) > GAP_OVERBROAD_WARN:
        warnings.append(('gap', f"over-broad {gap['overbroad_rate']*100:.0f}% over {window}d (>{GAP_OVERBROAD_WARN*100:.0f}%) — alias precision degrading (single-token fan-out)",
                         'review: vault_lookup.py review'))

    overall = 'critical' if criticals else ('warn' if warnings else 'healthy')

    if fmt == 'json':
        print(json.dumps({
            'overall': overall,
            'layers': {'vec': vec, 'alias': alias, 'gap': gap},
            'warnings': [{'layer': l, 'msg': m, 'fix': f} for l, m, f in warnings],
            'criticals': [{'layer': l, 'msg': m, 'fix': f} for l, m, f in criticals],
        }, indent=2, ensure_ascii=False))
        return 2 if criticals else (1 if warnings else 0)

    icon = {'healthy': '✅', 'warn': '⚠', 'critical': '✗'}[overall]
    n_issues = len(warnings) + len(criticals)
    head = 'all systems healthy' if overall == 'healthy' else f'{n_issues} issue(s)'
    print(f'=== ORP doctor — {icon} {head} ===\n')

    def _layer_icon(layer):
        if any(l == layer for l, _, _ in criticals):
            return '✗'
        if any(l == layer for l, _, _ in warnings):
            return '⚠'
        return '✅'

    # alias
    if alias.get('ok'):
        fr = 'fresh' if alias.get('fresh') else 'stale'
        age = f"{alias['age_hours']:.0f}h ago" if alias.get('age_hours') is not None else '?'
        print(f"  {_layer_icon('alias')} [alias] vault-index.json  "
              f"{alias.get('entries', '?')} entries · updated {age} · {fr}")
    else:
        print(f"  ✗ [alias] {alias.get('error')}")

    # vec
    if vec.get('ok'):
        ml = {'ok': 'OK', 'no_sidecar': 'NO-SIDECAR', 'soft': 'SOFT', 'hard': 'HARD'}.get(vec.get('model_level'), '?')
        print(f"  {_layer_icon('vec')} [vec]   vault-vec          "
              f"{vec.get('entries', '?')} entries · age {vec.get('age_days', 0):.1f}d · "
              f"drift {vec.get('drift', '?')} · model {ml}")
    else:
        print(f"  ✗ [vec]   {vec.get('error')}")

    # gap
    print(f"  {_layer_icon('gap')} [gap]   orp-misses.jsonl   "
          f"{gap.get('records', 0)} records · {window}d: {gap.get('recent', 0)} lookups, "
          f"{gap.get('all_miss', 0)} all_miss ({gap.get('all_miss_rate', 0)*100:.0f}%), "
          f"{gap.get('overbroad', 0)} over-broad ({gap.get('overbroad_rate', 0)*100:.0f}%)")

    if warnings or criticals:
        print('\n  actions:')
        for l, m, f in criticals:
            print(f"    ✗ [{l}] {m}\n        → {f}")
        for l, m, f in warnings:
            print(f"    ⚠ [{l}] {m}\n        → {f}")
    else:
        print('\n  (no action needed)')

    # low-volume caveat — gap-rate thresholds can't trip meaningfully below
    # GAP_MIN_VOLUME, so they're suppressed there (see the >= gate above).
    if gap.get('recent', 0) < GAP_MIN_VOLUME:
        print(f"\n  note: only {gap.get('recent', 0)} lookups in {window}d (<{GAP_MIN_VOLUME}) — gap-rate warnings suppressed (low-confidence at this volume)")

    return 2 if criticals else (1 if warnings else 0)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('search', help='Run alias + vec retrieval, log gaps')
    sp.add_argument('query')
    sp.add_argument('-k', '--top-k', type=int, default=5)
    sp.add_argument('-t', '--threshold', type=float, default=0.3)
    sp.add_argument('--no-log', action='store_true', help='Skip telemetry logging')
    sp.add_argument('--format', choices=['paths', 'json'], default='paths')
    sp.add_argument('--include-status', default=None,
                    help="Forward to vault_vec: comma-list or 'all' (default excludes stale/archived)")

    bp = sub.add_parser('backlinks', help='Find vault notes that link to <target>')
    bp.add_argument('target', help="Basename ('foo') or vault-rel path ('wiki/foo.md')")
    bp.add_argument('--include-status', default=None,
                    help="'all' or comma-list (default: live statuses captured,candidate,verified,retrievable — skip archived/stale)")
    bp.add_argument('--format', choices=['paths', 'json'], default='paths')

    rp = sub.add_parser('review', help='Summarize gap log for alias improvement')
    rp.add_argument('--since', default='7d', help='Time window: 1h, 7d, 4w (default 7d)')
    rp.add_argument('--top', type=int, default=20, help='Top N gap targets to show')

    sub.add_parser('status', help='Check installation + log health')

    dp = sub.add_parser('doctor', help='Unified health rollup across alias + vec + gap layers')
    dp.add_argument('--format', choices=['text', 'json'], default='text')
    dp.add_argument('--window', type=int, default=7, help='Gap-log window in days (default 7)')

    args = ap.parse_args()
    if args.cmd == 'search':
        sys.exit(cmd_search(args.query, args.top_k, args.threshold, args.no_log,
                            args.format, args.include_status))
    if args.cmd == 'backlinks':
        sys.exit(cmd_backlinks(args.target, args.include_status, args.format))
    if args.cmd == 'review':
        sys.exit(cmd_review(args.since, args.top))
    if args.cmd == 'status':
        sys.exit(cmd_status())
    if args.cmd == 'doctor':
        sys.exit(cmd_doctor(args.format, args.window))


if __name__ == '__main__':
    main()
