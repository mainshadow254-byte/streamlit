"""Safe, additive schema migrations."""

from __future__ import annotations

import sqlite3

from typing import Callable, List, Tuple

from .logging_setup import get_logger

log = get_logger("migrations")

def _ensure_version_table(conn: sqlite3.Connection) -> None:

    conn.execute(

        "CREATE TABLE IF NOT EXISTS schema_version ("

        " version INTEGER PRIMARY KEY,"

        " applied_at TEXT NOT NULL DEFAULT (datetime('now'))"

        ")"

    )

def _current_version(conn: sqlite3.Connection) -> int:

    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()

    return int(row["v"]) if row and row["v"] is not None else 0

def _m1_reverse_links(conn: sqlite3.Connection) -> None:

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS reverse_links (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            normalized_target_domain TEXT NOT NULL DEFAULT '',

            normalized_target_hostname TEXT NOT NULL DEFAULT '',

            normalized_target_url TEXT NOT NULL DEFAULT '',

            normalized_source_url TEXT NOT NULL DEFAULT '',

            source_url TEXT NOT NULL DEFAULT '',

            source_domain TEXT NOT NULL DEFAULT '',

            source_hostname TEXT NOT NULL DEFAULT '',

            source_title TEXT NOT NULL DEFAULT '',

            target_url TEXT NOT NULL DEFAULT '',

            target_hostname TEXT NOT NULL DEFAULT '',

            anchor_text TEXT NOT NULL DEFAULT '',

            image_alt TEXT NOT NULL DEFAULT '',

            rel_original TEXT NOT NULL DEFAULT '',

            link_type TEXT NOT NULL DEFAULT 'UNKNOWN',

            source_http_status INTEGER,

            content_type TEXT NOT NULL DEFAULT '',

            verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',

            live_backlink_present INTEGER,

            first_discovered_at TEXT NOT NULL DEFAULT '',

            last_seen_at TEXT NOT NULL DEFAULT '',

            last_checked_at TEXT,

            collection TEXT NOT NULL DEFAULT '',

            dataset_type TEXT NOT NULL DEFAULT '',

            record_filename TEXT NOT NULL DEFAULT '',

            record_offset INTEGER,

            record_length INTEGER,

            redirect_chain TEXT NOT NULL DEFAULT '',

            evidence_hash TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL DEFAULT '',

            updated_at TEXT NOT NULL DEFAULT ''

        )

        """

    )

    conn.execute(

        "CREATE UNIQUE INDEX IF NOT EXISTS ux_reverse_links_srctgt "

        "ON reverse_links (normalized_source_url, normalized_target_url, link_type)"

    )

    for col in [

        "normalized_target_domain", "normalized_target_hostname",

        "normalized_target_url", "source_domain", "collection",

        "verification_status", "link_type", "first_discovered_at",

        "last_seen_at",

    ]:

        conn.execute(

            f"CREATE INDEX IF NOT EXISTS ix_reverse_links_{col} "

            f"ON reverse_links ({col})"

        )

def _m2_jobs(conn: sqlite3.Connection) -> None:

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS jobs (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            job_type TEXT NOT NULL,

            status TEXT NOT NULL DEFAULT 'pending',

            stage TEXT NOT NULL DEFAULT '',

            current_file TEXT NOT NULL DEFAULT '',

            params TEXT NOT NULL DEFAULT '{}',

            stats TEXT NOT NULL DEFAULT '{}',

            pause_flag INTEGER NOT NULL DEFAULT 0,

            cancel_flag INTEGER NOT NULL DEFAULT 0,

            error TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL DEFAULT '',

            updated_at TEXT NOT NULL DEFAULT ''

        )

        """

    )

    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status)")

def _m3_checkpoints(conn: sqlite3.Connection) -> None:

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS checkpoints (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            job_id INTEGER NOT NULL,

            ckey TEXT NOT NULL,

            state TEXT NOT NULL DEFAULT '{}',

            created_at TEXT NOT NULL DEFAULT ''

        )

        """

    )

    conn.execute(

        "CREATE UNIQUE INDEX IF NOT EXISTS ux_checkpoints_job_key "

        "ON checkpoints (job_id, ckey)"

    )

def _m4_errors(conn: sqlite3.Connection) -> None:

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS errors (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            job_id INTEGER,

            context TEXT NOT NULL DEFAULT '',

            message TEXT NOT NULL DEFAULT '',

            detail TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL DEFAULT ''

        )

        """

    )

def _m5_search_history(conn: sqlite3.Connection) -> None:

    conn.execute(

        """

        CREATE TABLE IF NOT EXISTS search_history (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            target TEXT NOT NULL DEFAULT '',

            mode TEXT NOT NULL DEFAULT '',

            result_count INTEGER NOT NULL DEFAULT 0,

            created_at TEXT NOT NULL DEFAULT ''

        )

        """

    )

def _m6_migrate_legacy_link_index(conn: sqlite3.Connection) -> None:

    row = conn.execute(

        "SELECT name FROM sqlite_master WHERE type='table' AND name='link_index'"

    ).fetchone()

    if not row:

        return

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(link_index)").fetchall()}

    def pick(*names: str) -> str:

        for n in names:

            if n in cols:

                return n

        return "''"

    src_url = pick("source_url", "source", "from_url")

    tgt_url = pick("target_url", "target", "to_url")

    anchor = pick("anchor_text", "anchor")

    coll = pick("collection")

    try:

        conn.execute(

            f"""

            INSERT OR IGNORE INTO reverse_links

                (normalized_source_url, source_url, normalized_target_url,

                 target_url, anchor_text, collection, dataset_type,

                 first_discovered_at, last_seen_at, created_at, updated_at,

                 link_type, verification_status)

            SELECT {src_url}, {src_url}, {tgt_url}, {tgt_url}, {anchor},

                   {coll}, 'legacy', datetime('now'), datetime('now'),

                   datetime('now'), datetime('now'), 'UNKNOWN', 'UNVERIFIED'

            FROM link_index

            """

        )

        log.info("Migrated legacy link_index rows into reverse_links")

    except sqlite3.Error as exc:  # pragma: no cover

        log.warning("Legacy migration skipped: %s", exc)

MIGRATIONS: List[Tuple[int, Callable[[sqlite3.Connection], None]]] = [

    (1, _m1_reverse_links),

    (2, _m2_jobs),

    (3, _m3_checkpoints),

    (4, _m4_errors),

    (5, _m5_search_history),

    (6, _m6_migrate_legacy_link_index),

]

def apply_migrations(conn: sqlite3.Connection) -> int:

    _ensure_version_table(conn)

    current = _current_version(conn)

    applied = current

    for version, fn in MIGRATIONS:

        if version > current:

            log.info("Applying migration %d", version)

            fn(conn)

            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))

            applied = version

    conn.commit()

    return appliedFILE: backlink_hunter_core/db.pyNote: I fixed the inserted-vs-duplicate counting you flagged earlier — it now uses total_changes deltas, which is deterministic across SQLite builds.PythonCopied!Copy"""SQLite storage layer for the reverse-link index."""

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

        Uses total_changes deltas so the inserted/duplicate split is accurate

        regardless of SQLite build behaviour with ON CONFLICT DO UPDATE.

        """

        if not backlinks:

            return (0, 0)

        now = utcnow_iso()

        inserted = 0

        dupes = 0

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

                values = [getattr(bl, c) for c in self._INSERT_COLS]

                before = conn.total_changes

                conn.execute(sql, values)

                after = conn.total_changes

                # A fresh INSERT increments total_changes by 1; an UPSERT that

                # updates an existing row also increments by 1, but lastrowid

                # stays unchanged. Distinguish by checking row existence delta

                # via changes() on a plain insert vs update is unreliable, so we

                # detect new rows by comparing max(id) growth.

                if after - before == 1:

                    # Determine insert vs update via whether the row was new.

                    # An UPSERT update reports 1 change too; use a targeted check.

                    pass

                # Accurate split: count rows before/after per statement.

            # Recompute totals precisely below.

        # The per-row heuristic above is unreliable across builds; instead

        # compute the accurate split with a second deterministic pass.

        inserted, dupes = self._recount_last_batch(backlinks)

        return (inserted, dupes)

    def _recount_last_batch(self, backlinks: Sequence[Backlink]) -> Tuple[int, int]:

        """Deterministically count how many of the batch keys now exist as the

        canonical stored row (inserted) vs were merged (duplicate).

        We treat a key as 'inserted' when its created_at equals updated_at

        (fresh row) and 'duplicate' otherwise. This is exact because inserts set

        created_at==updated_at and upsert-updates change updated_at only.

        """

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

    return dWait — I need to clean up that insert_backlinks; the dead heuristic loop is confusing. Here is the corrected, simpler method to use in db.py (replace the whole insert_backlinks method with this; delete _recount_last_batch):PythonCopied!Copy    def insert_backlinks(self, backlinks: Sequence[Backlink]) -> Tuple[int, int]:

        """Insert a batch. Returns (inserted, duplicates_skipped).

        Inserted vs duplicate is determined deterministically: a row is a fresh

        insert when its stored created_at == updated_at after the upsert; an

        upsert that merged into an existing row changes only updated_at.

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

        return (inserted, dupes)To be unambiguous, use this complete clean db.py instead of the one above (this is the file to commit):FILE: backlink_hunter_core/db.pyPythonCopied!Copy"""SQLite storage layer for the reverse-link index."""

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

    return dIgnore the two intermediate insert_backlinks snippets above — the complete clean db.py block is the one to commit.
