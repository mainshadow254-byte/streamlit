from backlink_hunter_core.db import Database
from backlink_hunter_core.models import Backlink, utcnow_iso
def _bl() -> Backlink:
    return Backlink(
        source_url="https://a.com/p", source_domain="a.com",
        target_url="https://example.com/x", target_hostname="example.com",
        verification_status="LIVE_CONFIRMED", live_backlink_present=True,
        norm_source_url="https://a.com/p", norm_target_url="https://example.com/x",
    )
def test_insert_and_dedup(tmp_path):
    db = Database(tmp_path / "t.db")
    sid = db.create_search("example.com", "url_list", utcnow_iso())
    assert db.insert_backlink(sid, _bl()) is True
    assert db.insert_backlink(sid, _bl()) is False  # duplicate constraint
    rows = db.fetch_backlinks(sid)
    assert len(rows) == 1
    assert rows[0]["verification_status"] == "LIVE_CONFIRMED"
    assert rows[0]["live_backlink_present"] == 1
def test_error_log(tmp_path):
    db = Database(tmp_path / "t.db")
    db.log_error(None, "https://x", "timeout", "detail", utcnow_iso())
    assert len(db.fetch_errors()) == 1
