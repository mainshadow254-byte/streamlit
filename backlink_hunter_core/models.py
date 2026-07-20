"""Typed data models. Every value is sourced from real data; nothing is fabricated."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
@dataclass
class Backlink:
    source_url: str
    source_domain: str
    target_url: str
    target_hostname: str
    anchor_text: str = ""
    image_alt: str = ""
    link_type: str = "UNKNOWN"  # FOLLOW/NOFOLLOW/SPONSORED/UGC/MULTIPLE_REL_VALUES/UNKNOWN
    rel: str = ""
    source_title: str = ""
    source_http_status: Optional[int] = None
    content_type: str = ""
    verification_status: str = ""  # LIVE_CONFIRMED / ARCHIVED_CONFIRMED / ARCHIVED_ONLY
    live_backlink_present: Optional[bool] = None
    first_discovered_at: str = field(default_factory=utcnow_iso)
    last_checked_at: str = field(default_factory=utcnow_iso)
    common_crawl_collection: str = ""
    warc_filename: str = ""
    warc_offset: Optional[int] = None
    warc_length: Optional[int] = None
    redirect_chain: str = ""  # JSON-encoded list
    norm_source_url: str = ""
    norm_target_url: str = ""
    def as_row(self) -> dict:
        return asdict(self)
@dataclass
class SearchStats:
    records_queried: int = 0
    records_downloaded: int = 0
    pages_parsed: int = 0
    backlinks_discovered: int = 0
    backlinks_verified: int = 0
    exact_duplicates: int = 0
    normalized_duplicates: int = 0
    same_page_repeats: int = 0
    failed_requests: int = 0
    def as_dict(self) -> dict:
        return asdict(self)
