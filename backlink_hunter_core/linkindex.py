"""Scalable local reverse backlink index built from Common Crawl WARC records.
Builds a real target -> sources index by extracting ALL outbound links from
archived pages, storing normalized target domains. Resumable via checkpoints,
streams records (no full-dataset loads), warns about storage/bandwidth.
"""
from __future__ import annotations
import asyncio
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from .commoncrawl import fetch_warc_bytes, query_cdx
from .config import Settings
from .htmlparse import extract_links
from .net import RateLimiter, make_session
from .normalize import hostname_of, normalize_url, registrable_domain
from .warc import parse_warc_record
INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS link_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_domain TEXT NOT NULL,
    target_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    anchor_text TEXT,
    link_type TEXT,
    collection TEXT,
    UNIQUE(target_url, source_url)
);
CREATE INDEX IF NOT EXISTS idx_li_target ON link_index(target_domain);
CREATE TABLE IF NOT EXISTS index_checkpoints (
    filename TEXT NOT NULL,
    offset INTEGER NOT NULL,
    processed_at TEXT,
    PRIMARY KEY (filename, offset)
);
"""
# rough average bytes per stored row (SQLite overhead + text), used for estimates
_AVG_ROW_BYTES = 320
@dataclass
class IndexStats:
    records_queried: int = 0
    records_downloaded: int = 0
    pages_parsed: int = 0
    links_indexed: int = 0
    skipped_checkpointed: int = 0
    failed: int = 0
def estimate_storage_bytes(expected_pages: int, avg_links_per_page: int = 40) -> int:
    """Rough storage estimate before processing."""
    return expected_pages * avg_links_per_page * _AVG_ROW_BYTES
class LinkIndex:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(INDEX_SCHEMA)
    def is_checkpointed(self, filename: str, offset: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM index_checkpoints WHERE filename=? AND offset=?",
                (filename, offset),
            ).fetchone()
            return row is not None
    def checkpoint(self, filename: str, offset: int, when: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO index_checkpoints(filename,offset,processed_at) "
                "VALUES (?,?,?)",
                (filename, offset, when),
            )
    def add_link(
        self,
        target_url: str,
        source_url: str,
        anchor: str,
        link_type: str,
        collection: str,
    ) -> bool:
        target_domain = registrable_domain(hostname_of(target_url))
        source_domain = registrable_domain(hostname_of(source_url))
        with self.connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO link_index(
                        target_domain,target_url,source_url,source_domain,
                        anchor_text,link_type,collection
                    ) VALUES (?,?,?,?,?,?,?)""",
                    (
                        target_domain, normalize_url(target_url),
                        normalize_url(source_url), source_domain,
                        anchor, link_type, collection,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False
    def query_backlinks(self, target_domain: str) -> list[dict]:
        target_domain = registrable_domain(target_domain)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM link_index WHERE target_domain=? ORDER BY source_domain",
                (target_domain,),
            ).fetchall()
            return [dict(r) for r in rows]
async def build_index(
    settings: Settings,
    index: LinkIndex,
    collection: str,
    seed_domains: list[str],
    *,
    max_records: int,
) -> IndexStats:
    """Stream WARC records for seed domains; index all outbound links. Resumable."""
    from .models import utcnow_iso
    stats = IndexStats()
    async with make_session(settings) as session:
        limiter = RateLimiter(settings)
        for seed in seed_domains:
            count = 0
            async for rec in query_cdx(session, collection, seed, limit=max_records):
                if count >= max_records:
                    break
                count += 1
                stats.records_queried += 1
                if index.is_checkpointed(rec.filename, rec.offset):
                    stats.skipped_checkpointed += 1
                    continue
                raw = await fetch_warc_bytes(
                    session, rec, max_bytes=settings.maximum_response_bytes
                )
                if raw is None:
                    stats.failed += 1
                    continue
                stats.records_downloaded += 1
                parsed = parse_warc_record(
                    raw, max_html_bytes=settings.maximum_response_bytes
                )
                if parsed and "html" in parsed.content_type.lower():
                    stats.pages_parsed += 1
                    page_url = parsed.target_uri or rec.url
                    _title, links = extract_links(parsed.html, page_url)
                    for l in links:
                        if index.add_link(
                            l.resolved, page_url, l.anchor_text,
                            l.link_type, collection,
                        ):
                            stats.links_indexed += 1
                index.checkpoint(rec.filename, rec.offset, utcnow_iso())
    return stats
def build_index_sync(
    settings: Settings,
    index: LinkIndex,
    collection: str,
    seed_domains: list[str],
    *,
    max_records: int,
) -> IndexStats:
    return asyncio.run(
        build_index(settings, index, collection, seed_domains, max_records=max_records)
    )
