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

    return applied
