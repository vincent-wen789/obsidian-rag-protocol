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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn(); print(f"  ok {fn.__name__}")
    print(f"PASS {len(fns)} tests")
