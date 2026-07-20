from backlink_hunter_core.linkindex import LinkIndex, estimate_storage_bytes
def test_add_query_and_dedup(tmp_path):
    idx = LinkIndex(tmp_path / "li.db")
    assert idx.add_link(
        "https://example.com/a", "https://blog.org/p", "anchor", "FOLLOW", "CC"
    ) is True
    # same (target,source) -> duplicate
    assert idx.add_link(
        "https://example.com/a", "https://blog.org/p", "anchor", "FOLLOW", "CC"
    ) is False
    rows = idx.query_backlinks("example.com")
    assert len(rows) == 1
    assert rows[0]["source_domain"] == "blog.org"
def test_checkpoint(tmp_path):
    idx = LinkIndex(tmp_path / "li.db")
    assert idx.is_checkpointed("f.warc.gz", 100) is False
    idx.checkpoint("f.warc.gz", 100, "2026-01-01T00:00:00+00:00")
    assert idx.is_checkpointed("f.warc.gz", 100) is True
def test_estimate():
    assert estimate_storage_bytes(1000) > 0
