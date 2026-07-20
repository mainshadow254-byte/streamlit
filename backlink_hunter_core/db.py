"""SQLite persistence layer (WAL, parameterized SQL, dedup constraint)."""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from .models import Backlink
SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_domain TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backlinks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES searches(id),
    source_url TEXT NOT NULL,
    norm_source_url TEXT NOT NULL,
    source_domain TEXT,
    source_title TEXT,
    target_url TEXT NOT NULL,
    norm_target_url TEXT NOT NULL,
    target_hostname TEXT,
    anchor_text TEXT,
    image_alt TEXT,
    link_type TEXT,
    rel TEXT,
    source_http_status INTEGER,
    content_type TEXT,
    verification_status TEXT,
    live_backlink_present INTEGER,
    first_discovered_at TEXT,
    last_checked_at TEXT,
    common_crawl_collection TEXT,
    warc_filename TEXT,
    warc_offset INTEGER,
    warc_length INTEGER,
    redirect_chain TEXT,
    UNIQUE(search_id, norm_source_url, norm_target_url)
);
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER,
    url TEXT,
    kind TEXT,
    detail TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bl_search ON backlinks(search_id);
CREATE INDEX IF NOT EXISTS idx_bl_target ON backlinks(target_hostname);
"""
class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init()
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
    def create_search(self, target_domain: str, mode: str, created_at: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO searches(target_domain, mode, created_at) VALUES (?,?,?)",
                (target_domain, mode, created_at),
            )
            return int(cur.lastrowid)
    def insert_backlink(self, search_id: int, bl: Backlink) -> bool:
        """Return True if inserted, False if it was a duplicate (constraint hit)."""
        present = (
            1 if bl.live_backlink_present
            else 0 if bl.live_backlink_present is not None
            else None
        )
        with self.connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO backlinks(
                        search_id, source_url, norm_source_url, source_domain, source_title,
                        target_url, norm_target_url, target_hostname, anchor_text, image_alt,
                        link_type, rel, source_http_status, content_type, verification_status,
                        live_backlink_present, first_discovered_at, last_checked_at,
                        common_crawl_collection, warc_filename, warc_offset, warc_length,
                        redirect_chain
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        search_id, bl.source_url, bl.norm_source_url, bl.source_domain,
                        bl.source_title, bl.target_url, bl.norm_target_url, bl.target_hostname,
                        bl.anchor_text, bl.image_alt, bl.link_type, bl.rel,
                        bl.source_http_status, bl.content_type, bl.verification_status,
                        present, bl.first_discovered_at, bl.last_checked_at,
                        bl.common_crawl_collection, bl.warc_filename, bl.warc_offset,
                        bl.warc_length, bl.redirect_chain,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False
    def fetch_backlinks(self, search_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backlinks WHERE search_id=? ORDER BY source_domain",
                (search_id,),
            ).fetchall()
            return [dict(r) for r in rows]
    def list_searches(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM searches ORDER BY id DESC LIMIT 100"
            ).fetchall()
            return [dict(r) for r in rows]
    def fetch_errors(self, search_id: int | None = None) -> list[dict]:
        with self.connect() as conn:
            if search_id is None:
                rows = conn.execute(
                    "SELECT * FROM errors ORDER BY id DESC LIMIT 200"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM errors WHERE search_id=? ORDER BY id DESC LIMIT 200",
                    (search_id,),
                ).fetchall()
            return [dict(r) for r in rows]
    def log_error(
        self, search_id: int | None, url: str, kind: str, detail: str, created_at: str
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO errors(search_id,url,kind,detail,created_at) VALUES (?,?,?,?,?)",
                (search_id, url, kind, detail[:2000], created_at),
            )
