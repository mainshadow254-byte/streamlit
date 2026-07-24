"""Database-backed search: filtering, counting, pagination, sort, export iteration."""

from __future__ import annotations

from dataclasses import dataclass, field

from typing import Any, Dict, Iterator, List, Optional, Tuple

from .db import Database

from .matching import TargetSpec

from .models import MatchMode

SORTABLE = {

    "source_domain", "source_url", "target_url", "anchor_text", "link_type",

    "verification_status", "source_http_status", "first_discovered_at",

    "last_seen_at", "last_checked_at",

}

@dataclass

class SearchFilters:

    target: str = ""

    mode: str = MatchMode.ROOT_DOMAIN

    verification_status: Optional[str] = None

    live_only: Optional[bool] = None

    link_types: List[str] = field(default_factory=list)

    source_http_status: Optional[int] = None

    source_domain: Optional[str] = None

    anchor_contains: Optional[str] = None

    collection: Optional[str] = None

    dataset_type: Optional[str] = None

    first_seen_from: Optional[str] = None

    last_seen_to: Optional[str] = None

    exclude_blank_anchor: bool = False

    unique_source_page: bool = False

    unique_source_domain: bool = False

    sort_by: str = "last_seen_at"

    sort_desc: bool = True

class SearchService:

    def __init__(self, db: Database):

        self.db = db

    def _build_where(self, f: SearchFilters) -> Tuple[str, List[Any]]:

        spec = TargetSpec.parse(f.target, f.mode)

        clauses: List[str] = []

        params: List[Any] = []

        if f.target:

            if f.mode == MatchMode.EXACT_HOSTNAME:

                clauses.append("normalized_target_hostname = ?")

                params.append(spec.hostname)

            elif f.mode == MatchMode.EXACT_URL:

                clauses.append("normalized_target_url = ?")

                params.append(spec.url)

            elif f.mode == MatchMode.PATH_PREFIX:

                clauses.append("normalized_target_domain = ?")

                params.append(spec.domain)

                clauses.append("normalized_target_url LIKE ?")

                params.append(f"%{spec.path_prefix}%")

            else:

                clauses.append("normalized_target_domain = ?")

                params.append(spec.domain)

        if f.verification_status:

            clauses.append("verification_status = ?")

            params.append(f.verification_status)

        if f.live_only is True:

            clauses.append("live_backlink_present = 1")

        elif f.live_only is False:

            clauses.append("(live_backlink_present = 0 OR live_backlink_present IS NULL)")

        if f.link_types:

            marks = ",".join("?" for _ in f.link_types)

            clauses.append(f"link_type IN ({marks})")

            params.extend(f.link_types)

        if f.source_http_status is not None:

            clauses.append("source_http_status = ?")

            params.append(f.source_http_status)

        if f.source_domain:

            clauses.append("source_domain = ?")

            params.append(f.source_domain.strip().lower())

        if f.anchor_contains:

            clauses.append("anchor_text LIKE ?")

            params.append(f"%{f.anchor_contains}%")

        if f.collection:

            clauses.append("collection = ?")

            params.append(f.collection)

        if f.dataset_type:

            clauses.append("dataset_type = ?")

            params.append(f.dataset_type)

        if f.first_seen_from:

            clauses.append("first_discovered_at >= ?")

            params.append(f.first_seen_from)

        if f.last_seen_to:

            clauses.append("last_seen_at <= ?")

            params.append(f.last_seen_to)

        if f.exclude_blank_anchor:

            clauses.append("(anchor_text != '' OR image_alt != '')")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        return where, params

    def _order_by(self, f: SearchFilters) -> str:

        col = f.sort_by if f.sort_by in SORTABLE else "last_seen_at"

        direction = "DESC" if f.sort_desc else "ASC"

        return f" ORDER BY {col} {direction}, id {direction}"

    def _from_clause(self, f: SearchFilters) -> str:

        if f.unique_source_domain:

            return "(SELECT * FROM reverse_links GROUP BY source_domain) AS reverse_links"

        if f.unique_source_page:

            return ("(SELECT * FROM reverse_links GROUP BY normalized_source_url) "

                    "AS reverse_links")

        return "reverse_links"

    def count(self, f: SearchFilters) -> int:

        where, params = self._build_where(f)

        frm = self._from_clause(f)

        sql = f"SELECT COUNT(*) AS c FROM {frm}{where}"

        row = self.db.conn.execute(sql, params).fetchone()

        return int(row["c"]) if row else 0

    def page(self, f: SearchFilters, page: int = 1,

             page_size: int = 50) -> List[Dict[str, Any]]:

        where, params = self._build_where(f)

        frm = self._from_clause(f)

        order = self._order_by(f)

        offset = max(0, (max(1, page) - 1) * page_size)

        sql = f"SELECT * FROM {frm}{where}{order} LIMIT ? OFFSET ?"

        rows = self.db.conn.execute(sql, params + [page_size, offset]).fetchall()

        return [dict(r) for r in rows]

    def iter_all(self, f: SearchFilters, chunk: int = 1000) -> Iterator[Dict[str, Any]]:

        where, params = self._build_where(f)

        frm = self._from_clause(f)

        order = self._order_by(f)

        offset = 0

        while True:

            sql = f"SELECT * FROM {frm}{where}{order} LIMIT ? OFFSET ?"

            rows = self.db.conn.execute(sql, params + [chunk, offset]).fetchall()

            if not rows:

                break

            for r in rows:

                yield dict(r)

            offset += chunk

    def available_collections(self) -> List[str]:

        rows = self.db.conn.execute(

            "SELECT DISTINCT collection FROM reverse_links "

            "WHERE collection != '' ORDER BY collection"

        ).fetchall()

        return [r["collection"] for r in rows]

    def available_source_domains(self, limit: int = 500) -> List[str]:

        rows = self.db.conn.execute(

            "SELECT source_domain, COUNT(*) AS n FROM reverse_links "

            "GROUP BY source_domain ORDER BY n DESC LIMIT ?", (limit,)

        ).fetchall()

        return [r["source_domain"] for r in rows if r["source_domain"]]
