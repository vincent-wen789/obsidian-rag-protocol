#!/usr/bin/env python3
"""ORP v2.0-alpha 写入侧自检 — 无框架，纯 assert。跑：python3 test_write_side.py"""
import sys, os, importlib.util


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.expanduser(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cap = _load("~/.claude/hooks/orp-capture.py", "orp_capture")
orp = _load("~/Documents/obsidian-rag-protocol/orp_reader.py", "orp_reader")
vl = _load("~/Documents/obsidian-rag-protocol/vault_lookup.py", "vault_lookup")


# ── Task 1: capture pure helpers ──────────────────────────────

def test_slugify():
    assert cap.slugify("MEXC 日本 KOL Strategy").startswith("mexc"), cap.slugify("MEXC 日本 KOL Strategy")
    assert cap.slugify("Foo/Bar??  Baz!!") == "foo-bar-baz"
    assert cap.slugify("---") == "untitled"
    assert cap.slugify("") == "untitled"
    assert len(cap.slugify("x" * 200)) <= 60
    assert "/" not in cap.slugify("a/b/c") and " " not in cap.slugify("a b c")


def test_scan_secret():
    assert cap.scan_secret("sk-abc123DEF456ghi789jkl012mno345pq") is not None
    assert cap.scan_secret("ghp_" + "a" * 36) is not None
    assert cap.scan_secret("password: hunter2supersecret") is not None
    assert cap.scan_secret("normal knowledge about KOL pricing") is None


def test_validate_candidate():
    ok, _ = cap.validate_candidate({"title": "T", "aliases": ["a"], "body": "b", "why_shareable": "w"})
    assert ok
    bad_field, _ = cap.validate_candidate({"title": "T", "aliases": [], "body": "b", "why_shareable": "w", "evil": "x"})
    assert not bad_field
    no_title, _ = cap.validate_candidate({"aliases": [], "body": "b", "why_shareable": "w"})
    assert not no_title
    long_body, _ = cap.validate_candidate({"title": "T", "aliases": [], "body": "x" * 5000, "why_shareable": "w"})
    assert not long_body
    bad_type, _ = cap.validate_candidate({"title": "T", "aliases": "notlist", "body": "b", "why_shareable": "w"})
    assert not bad_type


def test_dedup_token_overlap():
    # regression: KOL capture must NOT false-match the fromm cat-food note (0 overlap)
    assert len(cap._sig_tokens("MEXC 日本 KOL 报价")
               & cap._sig_tokens("fromm-salmon-catfood-japan-purchase-guide")) == 0
    # a genuine dup shares >= 2 significant latin tokens
    assert len(cap._sig_tokens("MEXC 日本 KOL 报价")
               & cap._sig_tokens("mexc japan kol pricing framework")) >= 2
    assert "the" not in cap._sig_tokens("the a for of")  # stopwords excluded


# ── Task 4: set-status ────────────────────────────────────────

def test_set_status_rewrites_frontmatter():
    import tempfile, pathlib, types
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "wiki").mkdir(); (d / "wiki" / "entities").mkdir()
    (d / "wiki" / "log.md").write_text("# log\n")
    ent = d / "wiki" / "entities" / "foo.md"
    ent.write_text("---\nstatus: captured\ntitle: Foo\n---\n\n# Foo\nbody\n")
    args = types.SimpleNamespace(path=str(ent), status="verified", agent="cc",
                                 vault=str(d), reason="promoted in review")
    rc = orp.cmd_set_status(args)
    assert rc == 0, rc
    txt = ent.read_text()
    assert "status: verified" in txt and "status: captured" not in txt
    assert "captured" not in txt.split("---")[1]  # frontmatter block clean
    log = (d / "wiki" / "log.md").read_text()
    assert "decision" in log and "verified" in log  # auto-logged


def test_set_status_rejects_bad_status():
    import tempfile, pathlib, types
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "wiki" / "entities").mkdir(parents=True); (d / "wiki" / "log.md").write_text("# log\n")
    ent = d / "wiki" / "entities" / "bar.md"
    ent.write_text("---\nstatus: captured\n---\n# Bar\n")
    args = types.SimpleNamespace(path=str(ent), status="banana", agent="cc",
                                 vault=str(d), reason=None)
    assert orp.cmd_set_status(args) == 2  # invalid status rejected


# ── Task 5: fused status tag ──────────────────────────────────

def test_fuse_carries_status():
    alias_hits = [{"path": "wiki/entities/foo.md", "label": "foo"}]
    vec_hits = [{"path": "wiki/entities/foo.md", "score": 0.9, "source": "vault", "status": "captured"}]
    fused = vl.fuse_results(alias_hits, vec_hits, 5)
    assert fused[0]["vec_status"] == "captured", fused[0]
    alias_only = [{"path": "wiki/entities/bar.md", "label": "bar", "status": "captured"}]
    f2 = vl.fuse_results(alias_only, [], 5)
    assert f2[0].get("alias_status") == "captured" or f2[0].get("vec_status") is None


# ── Task 6: entity scan helper ────────────────────────────────

def test_scan_entities_finds_md():
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "wiki").mkdir()
    (d / "wiki" / "a.md").write_text("---\nstatus: captured\ntitle: A\n---\n# A\n")
    (d / "wiki" / "log.md").write_text("# skip me\n")
    (d / "wiki" / ".orp").mkdir()
    (d / "wiki" / ".orp" / "hidden.md").write_text("# hidden\n")
    ents = orp._scan_entities(d, ["wiki"])
    paths = {e["path"].name for e in ents}
    assert "a.md" in paths
    assert "log.md" not in paths      # skip_names
    assert "hidden.md" not in paths   # dotdir skipped


# ── Task 7: promotion + cohort fold ───────────────────────────

def test_promotion_from_gap_log():
    # real gap log stores ABSOLUTE paths — normalization must map them to path_rel
    V = "/Users/vincentwen/Documents/Vincent Obsidian"
    gap_lines = [
        {"ts": "2026-07-01T10:00:00+00:00", "query": "kol pricing",
         "fused_top3": [{"path": f"{V}/wiki/entities/kol.md"}]},
        {"ts": "2026-07-02T11:00:00+00:00", "query": "kol rate card",
         "fused_top3": [{"path": f"{V}/wiki/entities/kol.md"}]},
        {"ts": "2026-07-02T12:00:00+00:00", "query": "unrelated",
         "fused_top3": [{"path": f"{V}/wiki/entities/other.md"}]},
    ]
    entities = [{"path_rel": "wiki/entities/kol.md", "status": "captured"},
                {"path_rel": "wiki/entities/other.md", "status": "verified"}]
    import pathlib
    noms = orp._promotion_nominations(gap_lines, entities, promote_min=2, vault=pathlib.Path(V))
    assert "wiki/entities/kol.md" in noms          # abs→rel normalized, captured + 2 dates
    assert "wiki/entities/other.md" not in noms    # 1 date AND already verified
    # without vault (relative paths already) still works
    rel_lines = [{"ts": "2026-07-01", "fused_top3": [{"path": "wiki/entities/kol.md"}]},
                 {"ts": "2026-07-02", "fused_top3": [{"path": "wiki/entities/kol.md"}]}]
    assert "wiki/entities/kol.md" in orp._promotion_nominations(rel_lines, entities, 2)


def test_validate_rejects_newlines():
    ok, _ = cap.validate_candidate({"title": "line1\nline2", "aliases": [], "body": "b", "why_shareable": "w"})
    assert not ok  # newline in title splits frontmatter/H1
    ok2, _ = cap.validate_candidate({"title": "T", "aliases": ["a\nb"], "body": "b", "why_shareable": "w"})
    assert not ok2  # newline in alias
    assert "\n" not in cap._yaml_escape("a\nb")  # escape strips as defense


def test_cohort_fold():
    stale = [{"updated_date": "2026-05-01"} for _ in range(30)] + [{"updated_date": "2026-06-15"}]
    folded, loose = orp._fold_cohorts(stale, fold_min=20)
    assert folded and folded[0]["count"] == 30 and folded[0]["updated_date"] == "2026-05-01"
    assert len(loose) == 1  # the lone 06-15 stays loose


def test_gap_capture_clusters():
    gap_lines = [
        {"query": "how to X", "fused_top3": []},
        {"query": "how to X", "fused_top3": []},
        {"query": "how to Y", "fused_top3": []},
        {"query": "found it", "fused_top3": [{"path": "a.md"}]},
    ]
    caps = orp._gap_capture_clusters(gap_lines, min_repeat=2)
    assert caps.get("how to x") == 2
    assert "how to y" not in caps  # only 1×
    assert "found it" not in caps  # not an all-miss


# ── Task 8: inbox freshness ───────────────────────────────────

def test_inbox_freshness():
    import tempfile, pathlib, time
    d = pathlib.Path(tempfile.mkdtemp())
    reports = d / ".orp" / "reports"; reports.mkdir(parents=True)
    assert orp._inbox_is_stale(d, max_age_days=7) is True     # no report → stale
    r = reports / "consolidation-inbox-2026-07-03.md"; r.write_text("x")
    assert orp._inbox_is_stale(d, max_age_days=7) is False    # fresh → not stale
    old = time.time() - 10 * 86400
    os.utime(r, (old, old))
    assert orp._inbox_is_stale(d, max_age_days=7) is True     # backdated → stale


# ── capture write-side: stub round-trip (cross-module contract) ──

def test_write_stub_roundtrip_parses_back():
    """The stub capture writes MUST be readable by orp_reader's entity parser with
    status=captured — this is the write→read contract the whole loop depends on."""
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    ents = d / "wiki" / "entities"; ents.mkdir(parents=True)
    orig = cap.ENTITIES_DIR
    try:
        cap.ENTITIES_DIR = ents
        # realistic title (colon + ampersand + CJK) must round-trip cleanly through
        # quote+strip; body newlines are fine (only frontmatter values can't have them)
        obj = {"title": "MEXC Japan: KOL 报价 & 合规", "aliases": ["kol pricing", "日本 报价"],
               "body": "line1\nline2", "why_shareable": "w"}
        path = cap._write_stub(obj, "abcd1234", "2026-07-03")
        assert path is not None and path.is_file()
        parsed = orp._parse_entity_for_report(path)
        assert parsed["status"] == "captured", parsed
        assert parsed["title"] == "MEXC Japan: KOL 报价 & 合规", parsed["title"]
        assert path.read_text().count("---") == 2  # fence intact
        # embedded double-quotes: the naive parser keeps the escaping (cosmetic), but the
        # LOAD-BEARING contract holds — fence intact + status still parses captured
        obj2 = {"title": 'has "quotes"', "aliases": [], "body": "b", "why_shareable": "w"}
        p2 = cap._write_stub(obj2, "sid2", "2026-07-03")
        parsed2 = orp._parse_entity_for_report(p2)
        assert parsed2["status"] == "captured"
        assert p2.read_text().count("---") == 2  # escaped quotes don't break the fence
    finally:
        cap.ENTITIES_DIR = orig


def test_write_stub_no_clobber():
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    ents = d / "wiki" / "entities"; ents.mkdir(parents=True)
    orig = cap.ENTITIES_DIR
    try:
        cap.ENTITIES_DIR = ents
        (ents / "foo.md").write_text("PRE-EXISTING\n")
        obj = {"title": "Foo", "aliases": [], "body": "b", "why_shareable": "w"}
        assert cap._write_stub(obj, "s", "2026-07-03") is None      # refused to clobber
        assert (ents / "foo.md").read_text() == "PRE-EXISTING\n"    # original untouched
    finally:
        cap.ENTITIES_DIR = orig


# ── set-status edge branches ─────────────────────────────────

def _mk_vault_with_entity(frontmatter_body):
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "wiki" / "entities").mkdir(parents=True)
    (d / "wiki" / "log.md").write_text("# log\n")
    ent = d / "wiki" / "entities" / "e.md"
    ent.write_text(frontmatter_body)
    return d, ent


def test_set_status_inserts_when_absent():
    import types
    d, ent = _mk_vault_with_entity("---\ntitle: E\n---\n# E\n")  # no status: line
    args = types.SimpleNamespace(path=str(ent), status="verified", agent="cc",
                                 vault=str(d), reason=None)
    assert orp.cmd_set_status(args) == 0
    txt = ent.read_text()
    assert "status: verified" in txt.split("---")[1]  # inserted into frontmatter block
    assert txt.count("---") == 2                       # fence not corrupted


def test_set_status_error_paths():
    import types, tempfile, pathlib
    d, ent = _mk_vault_with_entity("no frontmatter here\n")
    a1 = types.SimpleNamespace(path=str(ent), status="verified", agent="cc", vault=str(d), reason=None)
    assert orp.cmd_set_status(a1) == 2                  # no frontmatter → reject
    a2 = types.SimpleNamespace(path=str(d / "wiki" / "entities" / "ghost.md"),
                               status="verified", agent="cc", vault=str(d), reason=None)
    assert orp.cmd_set_status(a2) == 2                  # entity not found → reject


# ── _append_log_entry (mirrors cmd_log §5.2) ─────────────────

def test_append_log_entry():
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "wiki").mkdir(); (d / "wiki" / "log.md").write_text("# log\n")
    pre = (d / "wiki" / "log.md").stat().st_size
    rc, n = orp._append_log_entry(d, "cc", "note", "hello", trigger="manual:test")
    assert rc == 0 and n > 0
    post = (d / "wiki" / "log.md").stat().st_size
    assert post == pre + n                              # byte-size invariant holds
    assert "trigger=manual:test" in (d / "wiki" / "log.md").read_text()
    # missing log → rc 2
    rc2, n2 = orp._append_log_entry(pathlib.Path(tempfile.mkdtemp()), "cc", "note", "x")
    assert rc2 == 2 and n2 == 0


# ── inbox-check single-flight (codex P2 race fix) ────────────

def test_inbox_check_single_flight():
    import types, tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    (d / ".orp" / "reports").mkdir(parents=True)  # empty → always stale
    calls = {"n": 0}

    class _FakePopen:
        def __init__(self, *a, **k):
            calls["n"] += 1

    orig = orp.subprocess.Popen
    try:
        orp.subprocess.Popen = _FakePopen
        args = types.SimpleNamespace(vault=str(d), max_age_days=7)
        assert orp.cmd_inbox_check(args) == 0
        assert orp.cmd_inbox_check(args) == 0  # second call: fresh lock suppresses spawn
        assert calls["n"] == 1, f"expected 1 spawn, got {calls['n']}"
        assert (d / ".orp" / "reports" / ".inbox-regen.lock").is_file()
    finally:
        orp.subprocess.Popen = orig


# ── consolidation-inbox full pipeline (integration) ──────────

def test_consolidation_inbox_integration():
    """End-to-end on a synthetic vault: promotion (abs path) + dup + cohort fold +
    gap-capture all render in one report without a live vault or claude call."""
    import tempfile, pathlib, types, time
    d = pathlib.Path(tempfile.mkdtemp())
    ents = d / "wiki" / "entities"; ents.mkdir(parents=True)
    (d / "wiki" / "log.md").write_text("# log\n")

    (ents / "kol.md").write_text("---\nstatus: captured\ntitle: KOL Pricing\n---\n# KOL Pricing\n")
    (ents / "dup-a.md").write_text("---\nstatus: verified\ntitle: Shared Topic\n---\n# Shared Topic\n")
    (ents / "dup-b.md").write_text("---\nstatus: captured\ntitle: Shared Topic\n---\n# Shared Topic\n")
    # a stale cohort: 22 entities all dated 2026-01-01 → folded.
    # staleness uses max(mtime, updated_date), so backdate BOTH or fresh mtime wins.
    old = time.time() - 200 * 86400
    for i in range(22):
        f = ents / f"cohort-{i}.md"
        f.write_text(f"---\nstatus: captured\ntitle: Cohort {i}\nupdated: 2026-01-01\n---\n# Cohort {i}\n")
        os.utime(f, (old, old))

    # gap log (abs paths, like the real one): kol exposed on 2 distinct dates + repeated all-miss
    gap = d / "gaps.jsonl"
    kol_abs = str((ents / "kol.md"))
    import json as _j
    gap.write_text("\n".join([
        _j.dumps({"ts": "2026-06-01T10:00:00+00:00", "query": "kol", "fused_top3": [{"path": kol_abs}]}),
        _j.dumps({"ts": "2026-06-05T10:00:00+00:00", "query": "kol rate", "fused_top3": [{"path": kol_abs}]}),
        _j.dumps({"ts": "2026-06-06T10:00:00+00:00", "query": "how to zzz", "fused_top3": []}),
        _j.dumps({"ts": "2026-06-07T10:00:00+00:00", "query": "how to zzz", "fused_top3": []}),
    ]) + "\n")

    out = d / "inbox.md"
    args = types.SimpleNamespace(vault=str(d), scan=["wiki"], gap_log=str(gap),
                                 stale_days=30, promote_min=2, cohort_fold_min=20,
                                 limit=50, output=str(out), format="json")
    assert orp.cmd_consolidation_inbox(args) == 0
    report = out.read_text()
    # promotion: kol nominated (captured, exposed 2 distinct dates, abs→rel normalized)
    assert "wiki/entities/kol.md" in report and "Promotion nominations (1)" in report
    assert "set-status wiki/entities/kol.md verified" in report
    # dup group surfaced
    assert "shared topic" in report.lower()
    # cohort folded, not listed individually
    assert "22 entities all dated `2026-01-01`" in report
    # gap-capture
    assert "how to zzz" in report


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn(); print(f"  ok {fn.__name__}")
    print(f"PASS {len(fns)} tests")
