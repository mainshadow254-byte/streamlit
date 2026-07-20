from backlink_hunter_core.export import to_csv, to_json, to_txt
ROWS = [{
    "source_url": "https://a.com/p", "source_domain": "a.com",
    "target_url": "https://example.com/x", "target_hostname": "example.com",
    "anchor_text": "hi", "link_type": "FOLLOW", "verification_status": "LIVE_CONFIRMED",
}]
def test_csv_has_headers_and_data():
    out = to_csv(ROWS)
    assert "source_url" in out
    assert "a.com" in out
def test_json_roundtrip():
    import json
    assert json.loads(to_json(ROWS))[0]["source_domain"] == "a.com"
def test_txt_variants():
    assert to_txt(ROWS, "source_urls") == "https://a.com/p"
    assert to_txt(ROWS, "source_domains") == "a.com"
    assert "https://a.com/p\thttps://example.com/x" in to_txt(ROWS, "pairs")
