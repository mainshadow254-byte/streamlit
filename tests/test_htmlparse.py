from pathlib import Path
from backlink_hunter_core.htmlparse import classify_rel, extract_links
from backlink_hunter_core.matching import MatchMode, matches_target
FIX = Path(__file__).parent / "fixtures" / "sample.html"
def test_rel_classification():
    assert classify_rel("nofollow") == "NOFOLLOW"
    assert classify_rel("sponsored") == "SPONSORED"
    assert classify_rel("ugc") == "UGC"
    assert classify_rel("nofollow ugc") == "MULTIPLE_REL_VALUES"
    assert classify_rel("") == "FOLLOW"
def test_extract_excludes_and_resolves():
    html = FIX.read_text(encoding="utf-8")
    title, links = extract_links(html, "https://blog.test/post")
    assert title == "Test Post"
    resolved = [l.resolved for l in links]
    assert "mailto:x@y.com" not in resolved
    assert "tel:+123" not in resolved
    assert any(r.startswith("https://blog.test/relative") for r in resolved)
    assert any(r.startswith("https://example.com/pr") for r in resolved)  # protocol-relative
def test_only_real_hyperlinks_count():
    html = FIX.read_text(encoding="utf-8")
    _title, links = extract_links(html, "https://blog.test/post")
    mk = dict(
        target_host="example.com", target_root="example.com",
        target_url="https://example.com/", target_path_prefix="/",
    )
    hits = [
        l for l in links
        if matches_target(l.resolved, mode=MatchMode.ROOT_AND_SUBDOMAINS, **mk)
    ]
    # www.example.com/product and //example.com/pr -> 2 real links; text mention excluded
    assert len(hits) == 2
    assert any(h.link_type == "NOFOLLOW" for h in hits)
