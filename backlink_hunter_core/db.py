"""SQLite storage layer for the reverse-link index."""

from __future__ import annotations

import json

import os

import sqlite3

import threading

from contextlib import contextmanager

from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .config import Config, get_config

from .logging_setup import get_logger

from .migrations import apply_migrations

from .models import Backlink, JobStatus, utcnow_iso

log = get_logger("db")

class Database:

    def __init__(self, cfg: Optional[Config] = None):

        self.cfg = cfg or get_config()

        if self.cfg.db_backend != "sqlite":

            raise NotImplementedError(

                "Only the sqlite backend is implemented. Set db_backend='sqlite'. "

                "PostgreSQL is a documented future option."

            )

        self.path = self.cfg.db_path

        self._local = threading.local()

        self._write_lock = threading.Lock()

        self.open()

    def open(self) -> None:

        conn = self._connect()

        apply_migrations(conn)

    def _connect(self) -> sqlite3.Connection:

        conn = getattr(self._local, "conn", None)

        if conn is not None:

            return conn

        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)

        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA foreign_keys=ON")

        if self.cfg.sqlite_wal:

            conn.execute("PRAGMA journal_mode=WAL")

        conn.execute("PRAGMA synchronous=NORMAL")

        conn.execute("PRAGMA busy_timeout=30000")

        self._local.conn = conn

        return conn

    @property

    def conn(self) -> sqlite3.Connection:

        return self._connect()

    @contextmanager

    def transaction(self) -> Iterator[sqlite3.Connection]:

        conn = self._connect()

        with self._write_lock:

            try:

                yield conn

                conn.commit()

            except Exception:

                conn.rollback()

                raise

    def close(self) -> None:

        conn = getattr(self._local, "conn", None)

        if conn is not None:

            conn.close()

            self._local.conn = None

    _INSERT_COLS = [

        "normalized_target_domain", "normalized_target_hostname",

        "normalized_target_url", "normalized_source_url", "source_url",

        "source_domain", "source_hostname", "source_title", "target_url",

        "target_hostname", "anchor_text", "image_alt", "rel_original",

        "link_type", "source_http_status", "content_type",

        "verification_status", "live_backlink_present", "first_discovered_at",

        "last_seen_at", "last_checked_at", "collection", "dataset_type",

        "record_filename", "record_offset", "record_length", "redirect_chain",

        "evidence_hash", "created_at", "updated_at",

    ]

    def insert_backlinks(self, backlinks: Sequence[Backlink]) -> Tuple[int, int]:

        """Insert a batch. Returns (inserted, duplicates_skipped).

        Inserted vs duplicate is determined deterministically: a fresh insert

        stores created_at == updated_at; an upsert that merged an existing row

        changes only updated_at.

        """

        if not backlinks:

            return (0, 0)

        now = utcnow_iso()

        placeholders = ",".join("?" for _ in self._INSERT_COLS)

        sql = (

            f"INSERT INTO reverse_links ({','.join(self._INSERT_COLS)}) "

            f"VALUES ({placeholders}) "

            f"ON CONFLICT(normalized_source_url, normalized_target_url, link_type) "

            f"DO UPDATE SET last_seen_at=excluded.last_seen_at, "

            f"  source_http_status=COALESCE(excluded.source_http_status, reverse_links.source_http_status), "

            f"  verification_status=excluded.verification_status, "

            f"  live_backlink_present=excluded.live_backlink_present, "

            f"  last_checked_at=COALESCE(excluded.last_checked_at, reverse_links.last_checked_at), "

            f"  redirect_chain=CASE WHEN excluded.redirect_chain != '' THEN excluded.redirect_chain ELSE reverse_links.redirect_chain END, "

            f"  evidence_hash=CASE WHEN excluded.evidence_hash != '' THEN excluded.evidence_hash ELSE reverse_links.evidence_hash END, "

            f"  updated_at=excluded.updated_at"

        )

        with self.transaction() as conn:

            for bl in backlinks:

                bl.created_at = bl.created_at or now

                bl.updated_at = now

                conn.execute(sql, [getattr(bl, c) for c in self._INSERT_COLS])

        inserted = 0

        dupes = 0

        conn = self._connect()

        for bl in backlinks:

            row = conn.execute(

                "SELECT created_at, updated_at FROM reverse_links "

                "WHERE normalized_source_url=? AND normalized_target_url=? "

                "AND link_type=?",

                (bl.normalized_source_url, bl.normalized_target_url, bl.link_type),

            ).fetchone()

            if row is None:

                continue

            if row["created_at"] == row["updated_at"]:

                inserted += 1

            else:

                dupes += 1

        return (inserted, dupes)

    def total_backlinks(self) -> int:

        row = self.conn.execute("SELECT COUNT(*) AS c FROM reverse_links").fetchone()

        return int(row["c"]) if row else 0

    def is_empty(self) -> bool:

        return self.total_backlinks() == 0

    def stats(self) -> Dict[str, Any]:

        c = self.conn

        def scalar(sql: str) -> int:

            r = c.execute(sql).fetchone()

            return int(r[0]) if r and r[0] is not None else 0

        collections = [

            dict(row) for row in c.execute(

                "SELECT collection, COUNT(*) AS n FROM reverse_links "

                "GROUP BY collection ORDER BY n DESC"

            ).fetchall()

        ]

        db_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0

        return {

            "db_path": os.path.abspath(self.path),

            "db_exists": os.path.exists(self.path),

            "db_size_bytes": db_size,

            "total_backlinks": scalar("SELECT COUNT(*) FROM reverse_links"),

            "unique_source_pages": scalar(

                "SELECT COUNT(DISTINCT normalized_source_url) FROM reverse_links"),

            "unique_source_domains": scalar(

                "SELECT COUNT(DISTINCT source_domain) FROM reverse_links"),

            "unique_target_domains": scalar(

                "SELECT COUNT(DISTINCT normalized_target_domain) FROM reverse_links"),

            "collections": collections,

            "failed_records": scalar("SELECT COUNT(*) FROM errors"),

            "checkpoints": scalar("SELECT COUNT(*) FROM checkpoints"),

            "active_jobs": scalar(

                "SELECT COUNT(*) FROM jobs WHERE status IN "

                "('pending','running','paused','stopping')"),

        }

    def integrity_check(self) -> str:

        row = self.conn.execute("PRAGMA integrity_check").fetchone()

        return row[0] if row else "unknown"

    def compact(self) -> None:

        with self._write_lock:

            self.conn.execute("VACUUM")

    def delete_collection(self, collection: str) -> int:

        with self.transaction() as conn:

            cur = conn.execute(

                "DELETE FROM reverse_links WHERE collection=?", (collection,))

            return cur.rowcount

    def create_job(self, job_type: str, params: Dict[str, Any]) -> int:

        now = utcnow_iso()

        with self.transaction() as conn:

            cur = conn.execute(

                "INSERT INTO jobs (job_type, status, params, stats, "

                "created_at, updated_at) VALUES (?,?,?,?,?,?)",

                (job_type, JobStatus.PENDING, json.dumps(params),

                 json.dumps({}), now, now),

            )

            return int(cur.lastrowid)

    def update_job(self, job_id: int, **fields: Any) -> None:

        if not fields:

            return

        if "stats" in fields and isinstance(fields["stats"], dict):

            fields["stats"] = json.dumps(fields["stats"])

        fields["updated_at"] = utcnow_iso()

        cols = ",".join(f"{k}=?" for k in fields)

        with self.transaction() as conn:

            conn.execute(f"UPDATE jobs SET {cols} WHERE id=?",

                         list(fields.values()) + [job_id])

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:

        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

        return _job_row(row) if row else None

    def list_jobs(self, active_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:

        if active_only:

            rows = self.conn.execute(

                "SELECT * FROM jobs WHERE status IN "

                "('pending','running','paused','stopping') "

                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

        else:

            rows = self.conn.execute(

                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

        return [_job_row(r) for r in rows]

    def set_job_control(self, job_id: int, pause: Optional[bool] = None,

                        cancel: Optional[bool] = None) -> None:

        fields: Dict[str, Any] = {}

        if pause is not None:

            fields["pause_flag"] = 1 if pause else 0

        if cancel is not None:

            fields["cancel_flag"] = 1 if cancel else 0

        if fields:

            self.update_job(job_id, **fields)

    def save_checkpoint(self, job_id: int, key: str, state: Dict[str, Any]) -> None:

        now = utcnow_iso()

        with self.transaction() as conn:

            conn.execute(

                "INSERT INTO checkpoints (job_id, ckey, state, created_at) "

                "VALUES (?,?,?,?) "

                "ON CONFLICT(job_id, ckey) DO UPDATE SET "

                "state=excluded.state, created_at=excluded.created_at",

                (job_id, key, json.dumps(state), now),

            )

    def load_checkpoint(self, job_id: int, key: str) -> Optional[Dict[str, Any]]:

        row = self.conn.execute(

            "SELECT state FROM checkpoints WHERE job_id=? AND ckey=?",

            (job_id, key)).fetchone()

        return json.loads(row["state"]) if row else None

    def record_error(self, context: str, message: str,

                     job_id: Optional[int] = None, detail: str = "") -> None:

        with self.transaction() as conn:

            conn.execute(

                "INSERT INTO errors (job_id, context, message, detail, created_at) "

                "VALUES (?,?,?,?,?)",

                (job_id, context, message, detail, utcnow_iso()),

            )

    def list_errors(self, limit: int = 200) -> List[Dict[str, Any]]:

        rows = self.conn.execute(

            "SELECT * FROM errors ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

        return [dict(r) for r in rows]

    def clear_errors(self) -> None:

        with self.transaction() as conn:

            conn.execute("DELETE FROM errors")

    def add_history(self, target: str, mode: str, result_count: int) -> None:

        with self.transaction() as conn:

            conn.execute(

                "INSERT INTO search_history (target, mode, result_count, created_at) "

                "VALUES (?,?,?,?)",

                (target, mode, result_count, utcnow_iso()),

            )

    def list_history(self, limit: int = 100) -> List[Dict[str, Any]]:

        rows = self.conn.execute(

            "SELECT * FROM search_history ORDER BY id DESC LIMIT ?",

            (limit,)).fetchall()

        return [dict(r) for r in rows]

def _job_row(row: sqlite3.Row) -> Dict[str, Any]:

    d = dict(row)

    for k in ("params", "stats"):

        if d.get(k):

            try:

                d[k] = json.loads(d[k])

            except (json.JSONDecodeError, TypeError):

                d[k] = {}

        else:

            d[k] = {}

    return d
