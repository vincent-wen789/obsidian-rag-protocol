#!/usr/bin/env python3
"""
vault_vec.py — Semantic search companion for Vincent's Obsidian vault.

Sits alongside ~/.hermes/scripts/orp_reader.py without modifying it.
Search ladder (CLAUDE.md):
  1. orp_reader.py match   (exact alias + token, fast path)
  2. vault_vec.py search   (semantic, this script)
  3. grep -r               (keyword fallback)

Storage:
  ~/.claude/data/vault-vec/vault-vec.npy        L2-normalized float32 matrix
  ~/.claude/data/vault-vec/vault-vec.meta.json  per-row {rel_path, mtime, size, hash, headers, status}
  ~/.claude/data/vault-vec/vault-vec.about.json index-level {embedding_model, embed_dim, vec_count, ...}

CLI:
  vault_vec.py index                                   full rebuild
  vault_vec.py update                                  incremental (mtime/size diff)
  vault_vec.py search "query" [-k 5] [-t 0.3] [--format paths|json]
  vault_vec.py status

Exit codes:
  0 hit / success | 1 no hit / no changes | 2 index missing/corrupt | 3 API/config error
"""

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

# macOS IPv6 fix: force IPv4 for all DNS resolution.
# api.openai.com (Cloudflare) sometimes returns AAAA records; httpx tries IPv6
# first, but macOS IPv6出口经常不通 → "Connection error". Same fix as pulse.py.
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

VAULT = Path(os.environ.get('ORP_VAULT_PATH', '/Users/vincentwen/Documents/Vincent Obsidian'))
MEMORY_ROOT = Path.home() / '.claude' / 'projects'  # */memory/*.md
DATA_DIR = Path.home() / '.claude' / 'data' / 'vault-vec'
VEC_PATH = DATA_DIR / 'vault-vec.npy'
META_PATH = DATA_DIR / 'vault-vec.meta.json'
ABOUT_PATH = DATA_DIR / 'vault-vec.about.json'
HERMES_ENV = Path.home() / '.hermes' / '.env'

EMBED_MODEL = 'text-embedding-3-small'
EMBED_DIM = 1536
ABOUT_SCHEMA_VERSION = 1
MAX_TOKENS_PER_FILE = 8000  # model limit is 8192; leave safety margin
BATCH_SIZE = 64

# §7.5 freshness obligation — semantic-layer staleness thresholds, the
# vector-index equivalent of orp_health.py's alias-layer check. Stale when
# age >= STALE_DAYS OR eligible-but-missing drift > DRIFT_PCT_MAX of eligible
# entries (defaults per spec §7.5; aligned with the §4.2 4-day window).
# `status --strict` exits non-zero on staleness so it can gate CI / agent start.
STALE_DAYS = 4
DRIFT_PCT_MAX = 0.05

EXCLUDE_DIRS = {'.obsidian', '.orp', '.git', '.trash', 'node_modules', '.smart-env'}

# v1.5.1 C3: status filter. Default excludes stale + archived from retrieval.
# Files without (or with unrecognized) `status:` frontmatter default to 'captured':
# live (retrievable) and honest (not claiming verification). v1.7.1 reconciliation —
# keeps this semantic layer in agreement with the alias layer (orp_reader.DEFAULT_STATUS).
ALL_STATUS_VALUES = frozenset({
    'captured', 'candidate', 'verified', 'retrievable', 'stale', 'archived'
})
DEFAULT_INCLUDED_STATUS = frozenset({
    'captured', 'candidate', 'verified', 'retrievable'
})
DEFAULT_FALLBACK_STATUS = 'captured'  # for files without frontmatter status field

_FRONTMATTER_STATUS_RE = re.compile(r'^status:\s*(\S+)', re.MULTILINE)

_ENCODER = None
def _enc():
    global _ENCODER
    if _ENCODER is None:
        import tiktoken
        _ENCODER = tiktoken.get_encoding('cl100k_base')
    return _ENCODER


def load_env():
    if os.environ.get('OPENAI_API_KEY'):
        return
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text().splitlines():
            if line.startswith('OPENAI_API_KEY='):
                v = line.split('=', 1)[1].strip().strip('"').strip("'")
                if v:
                    os.environ['OPENAI_API_KEY'] = v
                    return
    print('ERROR: OPENAI_API_KEY unavailable (env or ~/.hermes/.env)', file=sys.stderr)
    sys.exit(3)


def find_markdown_files():
    """Yield (source, abs_path, display_path) for all indexable .md files.

    source: 'vault' for Obsidian, 'memory' for ~/.claude/projects/*/memory/.
    display_path: source-relative path for nicer reporting.
    """
    # Obsidian vault
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        for f in files:
            if f.endswith('.md') and not f.startswith('.'):
                abs_p = Path(root) / f
                yield 'vault', abs_p, str(abs_p.relative_to(VAULT))
    # Per-project memory dirs
    if MEMORY_ROOT.exists():
        for proj in sorted(MEMORY_ROOT.iterdir()):
            mem_dir = proj / 'memory'
            if not mem_dir.is_dir():
                continue
            for f in sorted(mem_dir.iterdir()):
                if f.is_file() and f.suffix == '.md' and not f.name.startswith('.'):
                    yield 'memory', f, f'{proj.name}/memory/{f.name}'


def file_signature(path):
    st = path.stat()
    return st.st_mtime, st.st_size


def hash_content(text):
    return hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()[:16]


def read_for_embed(path):
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return None
    enc = _enc()
    tokens = enc.encode(text)
    if len(tokens) > MAX_TOKENS_PER_FILE:
        text = enc.decode(tokens[:MAX_TOKENS_PER_FILE])
    return text


def extract_headers(text, max_n=3):
    out = []
    for line in text.splitlines():
        if line.startswith('#'):
            out.append(line.strip()[:120])
            if len(out) >= max_n:
                break
    return out


def extract_status(path_or_text):
    """Parse YAML frontmatter for `status:` field. Missing or unrecognized → 'captured'
    (see DEFAULT_FALLBACK_STATUS).

    Accepts either a Path (reads first 4KB) or a text string. Used by both
    indexing (per-file) and lookups (re-parsed if meta missing).
    """
    try:
        if isinstance(path_or_text, Path):
            with open(path_or_text, 'r', encoding='utf-8', errors='replace') as f:
                head = f.read(4096)
        else:
            head = path_or_text[:4096]
    except Exception:
        return DEFAULT_FALLBACK_STATUS
    if not head.startswith('---'):
        return DEFAULT_FALLBACK_STATUS
    end = head.find('\n---', 3)
    if end < 0:
        return DEFAULT_FALLBACK_STATUS
    fm = head[3:end]
    m = _FRONTMATTER_STATUS_RE.search(fm)
    if not m:
        return DEFAULT_FALLBACK_STATUS
    val = m.group(1).strip().strip('"').strip("'").rstrip(',').lower()
    if val not in ALL_STATUS_VALUES:
        return DEFAULT_FALLBACK_STATUS  # unrecognized → treat as captured (live), don't filter
    return val


def read_about():
    """Read the sidecar; returns dict or None if missing/corrupt."""
    if not ABOUT_PATH.exists():
        return None
    try:
        return json.loads(ABOUT_PATH.read_text())
    except Exception:
        return None


def write_about(vec_count, created_at=None):
    """Write/refresh the sidecar with current model + counts."""
    now = time.strftime('%Y-%m-%dT%H:%M:%S%z') or time.strftime('%Y-%m-%dT%H:%M:%SZ')
    payload = {
        'schema_version': ABOUT_SCHEMA_VERSION,
        'embedding_model': EMBED_MODEL,
        'embed_dim': EMBED_DIM,
        'vec_count': vec_count,
        'created_at': created_at or now,
        'updated_at': now,
    }
    ABOUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def check_model_compat():
    """Return (level, message). level ∈ {'ok', 'no_sidecar', 'soft', 'hard'}.

    - 'ok'         → model + dim both match current constants
    - 'no_sidecar' → pre-v1.6 index, no sidecar yet (treated as OK; will be written
                     on next build/update)
    - 'soft'       → model name differs but embed_dim matches; search results are
                     still numerically valid (vectors comparable) but ranking is in
                     degraded space — caller may continue with warn
    - 'hard'       → embed_dim differs; vectors live in different spaces, results
                     are not just degraded — they're invalid (or crash). Caller MUST
                     fail closed (no search) until rebuild.
    """
    about = read_about()
    if about is None:
        return 'no_sidecar', 'no model metadata sidecar (pre-v1.6 index; will be written on next build)'
    indexed_model = about.get('embedding_model')
    indexed_dim = about.get('embed_dim')
    if indexed_dim != EMBED_DIM:
        return 'hard', (
            f'embed_dim mismatch (HARD): indexed={indexed_dim} current={EMBED_DIM} — '
            f'vectors live in different spaces; results are invalid. '
            f'Run `vault_vec.py index` to rebuild before searching.'
        )
    if indexed_model != EMBED_MODEL:
        return 'soft', (
            f'embedding model differs but dim matches (SOFT): indexed={indexed_model!r} '
            f'current={EMBED_MODEL!r} — search ranking degraded; rerun '
            f'`vault_vec.py index` to refresh.'
        )
    return 'ok', ''


def _resolve_embed_attempts():
    """Honor ORP_EMBED_MAX_RETRIES env var (daily cron passes 3 to cap the
    retry wall-clock at 14s; weekly full rebuild keeps the default of 7 ≈
    4.2min — only the full rebuild needs that much patience because it's
    the line of defense against iCloud-induced silent content drift).
    Returns int. Falls back to 7 on any parse error.
    """
    raw = os.environ.get('ORP_EMBED_MAX_RETRIES', '').strip()
    if not raw:
        return 7
    try:
        n = int(raw)
        return n if n >= 1 else 7
    except ValueError:
        return 7


def _embed_with_retry(client, texts, *, attempts=None, base_delay=2.0):
    """Embed `texts`, retrying transient failures with exponential backoff.

    Default `attempts` is resolved at call time from ORP_EMBED_MAX_RETRIES
    (or 7 if unset). The daily cron uses 3 (2/4/8s = 14s cap) so a hard
    outage fails fast and trips the wrapper's circuit breaker instead of
    burning 4.2min. The weekly full rebuild keeps 7 because the longer
    horizon is what bounds iCloud-induced silent content drift to ≤7d.
    """
    if attempts is None:
        attempts = _resolve_embed_attempts()
    base = str(getattr(client, 'base_url', None) or
               os.environ.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1')
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            return client.embeddings.create(model=EMBED_MODEL, input=texts)
        except Exception as e:
            last_err = e
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(f'  embed attempt {attempt}/{attempts} failed at {base} '
                  f'({type(e).__name__}: {e}); retry in {delay:.0f}s',
                  file=sys.stderr)
            time.sleep(delay)
    raise last_err


def build_index(incremental):
    import numpy as np
    from openai import OpenAI

    load_env()
    # Explicit base_url to bypass empty OPENAI_BASE_URL env var pollution
    client = OpenAI(timeout=30.0, base_url="https://api.openai.com/v1")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing = {}
    created_at = None  # preserved across incremental builds
    if incremental and META_PATH.exists() and VEC_PATH.exists():
        # F: invalidate existing vectors if sidecar reports any mismatch.
        # Both 'hard' (dim) and 'soft' (model-only) require full re-embed:
        # soft = vectors numerically comparable but trained differently → ranking drift
        # hard = vectors live in different dim spaces → outright invalid
        level, msg = check_model_compat()
        if level in ('hard', 'soft'):
            print(f'WARN: {msg}; discarding incremental cache, full rebuild', file=sys.stderr)
        else:
            try:
                meta = json.loads(META_PATH.read_text())
                vecs = np.load(VEC_PATH)
                if len(meta) == vecs.shape[0]:
                    for i, m in enumerate(meta):
                        key = m.get('abs_path') or m.get('rel_path')  # backward compat
                        existing[key] = (m, vecs[i])
                print(f'Loaded existing index: {len(existing)} entries', file=sys.stderr)
                prev_about = read_about()
                if prev_about:
                    created_at = prev_about.get('created_at')
            except Exception as e:
                print(f'Existing index unreadable ({e}); full rebuild', file=sys.stderr)
                existing = {}

    files = list(find_markdown_files())
    src_counts = {}
    for source, _, _ in files:
        src_counts[source] = src_counts.get(source, 0) + 1
    src_summary = ' '.join(f'{k}={v}' for k, v in sorted(src_counts.items()))
    print(f'Scanning {len(files)} markdown files ({src_summary})…', file=sys.stderr)

    to_embed = []
    keep = []
    for source, abs_p, disp in files:
        key = str(abs_p)
        try:
            mtime, size = file_signature(abs_p)
        except OSError:
            continue
        if key in existing:
            old_m, old_v = existing[key]
            if old_m.get('mtime') == mtime and old_m.get('size') == size:
                # Cache hit on embedding, but refresh status (cheap reparse)
                old_m = dict(old_m)
                old_m['status'] = extract_status(abs_p)
                keep.append((old_m, old_v))
                continue
        text = read_for_embed(abs_p)
        if not text or not text.strip():
            continue
        to_embed.append((source, key, disp, text, mtime, size))

    print(f'Cache hit: {len(keep)} | To embed: {len(to_embed)}', file=sys.stderr)

    new_entries = []
    total_tokens = 0
    t0 = time.time()
    for batch_start in range(0, len(to_embed), BATCH_SIZE):
        batch = to_embed[batch_start:batch_start + BATCH_SIZE]
        texts = [b[3] for b in batch]
        try:
            r = _embed_with_retry(client, texts)
        except Exception as e:
            print(f'ERROR embedding batch {batch_start // BATCH_SIZE + 1} after retries: {e}', file=sys.stderr)
            sys.exit(3)
        total_tokens += r.usage.total_tokens
        for (source, abs_path, disp, text, mtime, size), data in zip(batch, r.data):
            new_entries.append(({
                'source': source,
                'abs_path': abs_path,
                'rel_path': disp,
                'mtime': mtime,
                'size': size,
                'hash': hash_content(text),
                'headers': extract_headers(text),
                'first_line': (text.splitlines()[0][:140] if text.splitlines() else ''),
                'status': extract_status(text),
            }, np.array(data.embedding, dtype=np.float32)))
        print(f'  batch {batch_start // BATCH_SIZE + 1}/{(len(to_embed) + BATCH_SIZE - 1) // BATCH_SIZE}: {len(batch)} files', file=sys.stderr)

    all_entries = keep + new_entries
    if not all_entries:
        print('No entries to index.', file=sys.stderr)
        return 2 if not incremental else 1

    vecs = np.stack([v for _, v in all_entries])
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    vecs = vecs / norms

    np.save(VEC_PATH, vecs)
    META_PATH.write_text(json.dumps([m for m, _ in all_entries], indent=2, ensure_ascii=False))
    write_about(vec_count=len(all_entries), created_at=created_at)

    dt = time.time() - t0
    cost = total_tokens * 0.02 / 1_000_000
    print(f'Indexed: {len(all_entries)} entries | {dt:.1f}s | {total_tokens:,} new tokens (~${cost:.4f})', file=sys.stderr)
    return 0


def parse_status_filter(spec):
    """Convert CLI --include-status spec to a frozenset of allowed statuses.

    Accepted:
      None / unset    → DEFAULT_INCLUDED_STATUS (excludes stale + archived)
      'all'           → ALL_STATUS_VALUES (no filtering)
      'a,b,c'         → frozenset of comma-split tokens, validated
    """
    if spec is None:
        return DEFAULT_INCLUDED_STATUS
    spec = spec.strip()
    if spec.lower() == 'all':
        return ALL_STATUS_VALUES
    tokens = {t.strip().lower() for t in spec.split(',') if t.strip()}
    bad = tokens - ALL_STATUS_VALUES
    if bad:
        print(f'WARN: unknown status filter values {sorted(bad)}; valid: {sorted(ALL_STATUS_VALUES)}', file=sys.stderr)
        tokens = tokens & ALL_STATUS_VALUES
    return frozenset(tokens) if tokens else DEFAULT_INCLUDED_STATUS


def search(query, top_k, threshold, fmt, include_status):
    import numpy as np
    from openai import OpenAI

    if not VEC_PATH.exists() or not META_PATH.exists():
        print('ERROR: index missing. Run `vault_vec.py index`.', file=sys.stderr)
        return 2

    # F: fail closed on HARD mismatch (embed_dim differs — vectors invalid).
    # SOFT mismatch (same dim, different model) → warn but continue with degraded ranking.
    level, msg = check_model_compat()
    if level == 'hard':
        print(f'ERROR: {msg}', file=sys.stderr)
        return 2
    if level == 'soft':
        print(f'WARN: {msg}', file=sys.stderr)

    allowed = parse_status_filter(include_status)
    filter_active = allowed != ALL_STATUS_VALUES

    load_env()
    client = OpenAI(timeout=30.0, base_url="https://api.openai.com/v1")
    vecs = np.load(VEC_PATH)
    meta = json.loads(META_PATH.read_text())

    try:
        r = _embed_with_retry(client, [query])
    except Exception as e:
        print(f'ERROR embedding query: {e}', file=sys.stderr)
        return 3
    qv = np.array(r.data[0].embedding, dtype=np.float32)
    qv = qv / (np.linalg.norm(qv) or 1)

    sims = vecs @ qv
    order = np.argsort(-sims)
    hits = []
    skipped_by_status = 0
    # widen window when filter is active to ensure top_k post-filter
    window = top_k * 5 if filter_active else top_k * 3
    for i in order[:window]:
        score = float(sims[i])
        if score < threshold:
            break
        m = meta[i]
        # Resolve abs_path
        abs_str = m.get('abs_path') or str(VAULT / m['rel_path'])
        abs_p = Path(abs_str)
        if not abs_p.exists():
            continue
        # v1.5.1 C3: status filter
        entry_status = (m.get('status') or DEFAULT_FALLBACK_STATUS).lower()
        if entry_status not in allowed:
            skipped_by_status += 1
            continue
        hits.append({
            'score': round(score, 3),
            'source': m.get('source', 'vault'),
            'status': entry_status,
            'path': abs_str,
            'rel_path': m.get('rel_path', ''),
            'first_line': m.get('first_line', ''),
            'headers': m.get('headers', []),
        })
        if len(hits) >= top_k:
            break

    if not hits:
        if filter_active and skipped_by_status:
            print(f'(no hits; {skipped_by_status} filtered by status — try --include-status=all)', file=sys.stderr)
        return 1

    if fmt == 'json':
        print(json.dumps(hits, indent=2, ensure_ascii=False))
    else:
        for h in hits:
            print(f"{h['score']:.3f}\t[{h['source']}/{h['status']}]\t{h['path']}")
    return 0


def status(strict=False):
    if not VEC_PATH.exists() or not META_PATH.exists():
        print('index: MISSING', file=sys.stderr)
        return 2
    import numpy as np
    vecs = np.load(VEC_PATH)
    meta = json.loads(META_PATH.read_text())
    age_days = (time.time() - VEC_PATH.stat().st_mtime) / 86400

    # Counts by source
    idx_src = {}
    for m in meta:
        s = m.get('source', 'vault')
        idx_src[s] = idx_src.get(s, 0) + 1
    disk_src = {}
    disk_paths = set()
    for source, abs_path, _ in find_markdown_files():
        disk_src[source] = disk_src.get(source, 0) + 1
        disk_paths.add(str(abs_path))

    # §7.5 drift = eligible-but-missing, computed BY PATH (set difference) against
    # the §2.2/§2.3 eligibility filter (find_markdown_files) — NOT a count delta.
    # A count delta (total_disk - len(meta)) silently nets to zero when a newly
    # eligible file and a stale/deleted indexed row cancel out, masking the very
    # add/delete/move drift the gate must catch (spec: "never the layer measured
    # against its own last snapshot"). Legacy rows without abs_path fall back to
    # rel_path, which won't match a disk abs path → counted as missing (fail-safe:
    # over-reports drift, triggering a harmless rebuild, never under-reports).
    indexed_paths = {m.get('abs_path') or m.get('rel_path') for m in meta}
    total_disk = len(disk_paths)
    missing = len(disk_paths - indexed_paths)
    drift_pct = missing / max(total_disk, 1)

    print(f'index: {len(meta)} entries, shape {vecs.shape}, age {age_days:.1f}d')
    print(f'  by source (indexed): ' + ' '.join(f'{k}={v}' for k, v in sorted(idx_src.items())))
    print(f'  by source (on-disk): ' + ' '.join(f'{k}={v}' for k, v in sorted(disk_src.items())))
    print(f'  drift: {missing} eligible-but-missing ({drift_pct:.0%} of {total_disk} on disk); run `update` to sync')

    # F: embedding model versioning
    about = read_about()
    level = None
    if about is None:
        print('  model: (no sidecar — pre-v1.6 index, will be written on next build/update)')
    else:
        level, msg = check_model_compat()
        marker = {
            'ok': 'OK',
            'no_sidecar': 'NO-SIDECAR',
            'soft': 'SOFT-MISMATCH',
            'hard': 'HARD-MISMATCH',
        }.get(level, level.upper())
        print(f'  model: {about.get("embedding_model")} dim={about.get("embed_dim")} schema=v{about.get("schema_version")} [{marker}]')
        if msg:
            print(f'    ↳ {msg}')
        if about.get('created_at'):
            print(f'  built:  {about.get("created_at")} → updated {about.get("updated_at")}')

    # §7.5 machine-checkable freshness gate. Default is observational (exit 0).
    # --strict escalates staleness to a non-zero exit so the check can gate CI or
    # block agent startup — the semantic-layer equivalent of `orp_health.py
    # --strict` for the alias layer (which §7.5 requires every layer to provide).
    if strict:
        reasons = []
        if age_days >= STALE_DAYS:
            reasons.append(f'age {age_days:.1f}d >= {STALE_DAYS}d')
        if drift_pct > DRIFT_PCT_MAX:
            reasons.append(f'drift {drift_pct:.0%} > {DRIFT_PCT_MAX:.0%}')
        if level == 'hard':
            reasons.append('hard embedding-model mismatch (index unusable)')
        if reasons:
            print(f'  STALE (--strict): {"; ".join(reasons)} — run `vault_vec.py update`',
                  file=sys.stderr)
            return 2
        print('  fresh (--strict): within §7.5 freshness obligation')
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('index')
    sub.add_parser('update')
    sp = sub.add_parser('search')
    sp.add_argument('query')
    sp.add_argument('-k', '--top-k', type=int, default=5)
    sp.add_argument('-t', '--threshold', type=float, default=0.3)
    sp.add_argument('--format', choices=['paths', 'json'], default='paths')
    sp.add_argument('--include-status', default=None,
                    help="Comma-separated status whitelist or 'all'. "
                         f"Default: {','.join(sorted(DEFAULT_INCLUDED_STATUS))} (excludes stale/archived)")
    sps = sub.add_parser('status')
    sps.add_argument('--strict', action='store_true',
                     help='exit non-zero when the index is stale '
                          f'(age >= {STALE_DAYS}d OR drift > {DRIFT_PCT_MAX:.0%} '
                          'eligible-but-missing); gates CI / agent startup per §7.5')
    args = ap.parse_args()

    if args.cmd == 'index':
        sys.exit(build_index(incremental=False))
    if args.cmd == 'update':
        sys.exit(build_index(incremental=True))
    if args.cmd == 'search':
        sys.exit(search(args.query, args.top_k, args.threshold, args.format, args.include_status))
    if args.cmd == 'status':
        sys.exit(status(args.strict))


if __name__ == '__main__':
    main()
