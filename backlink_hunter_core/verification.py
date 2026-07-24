"""Live verification of indexed backlinks.

Given an indexed source page, re-fetch it safely and confirm whether the

hyperlink to the target still exists. Archived evidence is preserved even when

the live link is gone. Never marks an unavailable page as live.

"""

from __future__ import annotations

import hashlib

import json

from dataclasses import dataclass

from typing import Any, Dict, List, Optional

from .config import Config, get_config

from .db import Database

from .htmlparse import parse_html_links, parse_title

from .logging_setup import get_logger

from .matching import TargetSpec, link_matches_target

from .models import MatchMode, VerificationStatus, utcnow_iso

from .net import FetchError, SafeHTTPClient

from .security import SecurityError

log = get_logger("verification")

@dataclass

class VerificationResult:

    source_url: str

    target: str

    status: str

    http_status: Optional[int] = None

    content_type: str = ""

    live_present: Optional[bool] = None

    redirect_chain: List[str] = None  # type: ignore

    checked_at: str = ""

    evidence_hash: str = ""

    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:

        return {

            "source_url": self.source_url,

            "target": self.target,

            "verification_status": self.status,

            "source_http_status": self.http_status,

            "content_type": self.content_type,

            "live_backlink_present": (

                None if self.live_present is None else int(self.live_present)

            ),

            "redirect_chain": json.dumps(self.redirect_chain or []),

            "last_checked_at": self.checked_at,

            "evidence_hash": self.evidence_hash,

            "detail": self.detail,

        }

class Verifier:

    def __init__(self, db: Optional[Database] = None,

                 client: Optional[SafeHTTPClient] = None,

                 cfg: Optional[Config] = None):

        self.cfg = cfg or get_config()

        self.db = db

        self.client = client or SafeHTTPClient(self.cfg)

    # ------------------------------------------------------------------ #

    def verify(self, source_url: str, target: str,

               mode: str = MatchMode.ROOT_DOMAIN,

               had_archive: bool = True) -> VerificationResult:

        """Verify a single source page for a live link to `target`."""

        spec = TargetSpec.parse(target, mode)

        checked_at = utcnow_iso()

        result = VerificationResult(

            source_url=source_url, target=target,

            status=VerificationStatus.UNVERIFIED,

            redirect_chain=[], checked_at=checked_at,

        )

        try:

            res = self.client.fetch(source_url, method="GET")

        except SecurityError as exc:

            result.status = VerificationStatus.VERIFICATION_FAILED

            result.detail = f"blocked: {exc}"

            return result

        except FetchError as exc:

            result.status = VerificationStatus.SOURCE_UNAVAILABLE

            result.detail = str(exc)

            # Preserve archive knowledge.

            if had_archive:

                result.status = VerificationStatus.ARCHIVED_ONLY

            return result

        result.http_status = res.status

        result.content_type = res.content_type

        result.redirect_chain = res.redirect_chain

        if res.status >= 400 or not res.body:

            result.status = (

                VerificationStatus.ARCHIVED_ONLY if had_archive

                else VerificationStatus.SOURCE_UNAVAILABLE

            )

            return result

        html = res.text

        result.evidence_hash = hashlib.sha256(

            (res.final_url + "|" + str(res.status) + "|" +

             hashlib.sha256(res.body).hexdigest()).encode("utf-8")

        ).hexdigest()

        links = parse_html_links(html, res.final_url)

        present = any(

            link_matches_target(link.resolved_url, spec) for link in links

        )

        result.live_present = present

        if present:

            result.status = (

                VerificationStatus.LIVE_CONFIRMED if not had_archive

                else VerificationStatus.ARCHIVED_CONFIRMED

            )

            # ARCHIVED_CONFIRMED = was archived AND still live.

            # Prefer LIVE_CONFIRMED wording when caller cares only about live:

            if not had_archive:

                result.status = VerificationStatus.LIVE_CONFIRMED

        else:

            result.status = VerificationStatus.REMOVED

        return result

    # ------------------------------------------------------------------ #

    def verify_and_store(self, backlink_id: int, source_url: str, target: str,

                         mode: str = MatchMode.ROOT_DOMAIN,

                         had_archive: bool = True) -> VerificationResult:

        """Verify then persist the outcome onto the reverse_links row."""

        result = self.verify(source_url, target, mode, had_archive)

        if self.db is not None:

            data = result.to_dict()

            with self.db.transaction() as conn:

                conn.execute(

                    "UPDATE reverse_links SET "

                    " verification_status=?, source_http_status=?, "

                    " content_type=?, live_backlink_present=?, "

                    " redirect_chain=?, last_checked_at=?, "

                    " evidence_hash=CASE WHEN ?!='' THEN ? ELSE evidence_hash END, "

                    " updated_at=? "

                    "WHERE id=?",

                    (

                        data["verification_status"], data["source_http_status"],

                        data["content_type"], data["live_backlink_present"],

                        data["redirect_chain"], data["last_checked_at"],

                        data["evidence_hash"], data["evidence_hash"],

                        utcnow_iso(), backlink_id,

                    ),

                )

        return result

    def verify_source_list(self, target: str, source_urls: List[str],

                           mode: str = MatchMode.ROOT_DOMAIN

                           ) -> List[VerificationResult]:

        """Verify a supplied list of source URLs against a target (no DB needed)."""

        results = []

        for url in source_urls:

            url = url.strip()

            if not url:

                continue

            results.append(self.verify(url, target, mode, had_archive=False))

        return results✅ Part complete — verification.py is whole.Say next for warc.py and wat.py (streaming WARC/WAT record parsers with decompression-bomb guards).
