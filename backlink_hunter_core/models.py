"""Domain models and enumerations shared across the codebase."""

from __future__ import annotations

from dataclasses import dataclass, field

from datetime import datetime, timezone

from typing import Optional

class LinkType:

    FOLLOW = "FOLLOW"

    NOFOLLOW = "NOFOLLOW"

    SPONSORED = "SPONSORED"

    UGC = "UGC"

    MULTIPLE_REL_VALUES = "MULTIPLE_REL_VALUES"

    UNKNOWN = "UNKNOWN"

    ALL = {FOLLOW, NOFOLLOW, SPONSORED, UGC, MULTIPLE_REL_VALUES, UNKNOWN}

class VerificationStatus:

    LIVE_CONFIRMED = "LIVE_CONFIRMED"

    ARCHIVED_CONFIRMED = "ARCHIVED_CONFIRMED"

    ARCHIVED_ONLY = "ARCHIVED_ONLY"

    REMOVED = "REMOVED"

    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

    VERIFICATION_FAILED = "VERIFICATION_FAILED"

    UNVERIFIED = "UNVERIFIED"

    ALL = {

        LIVE_CONFIRMED, ARCHIVED_CONFIRMED, ARCHIVED_ONLY, REMOVED,

        SOURCE_UNAVAILABLE, VERIFICATION_FAILED, UNVERIFIED,

    }

class DatasetType:

    LIVE = "live"

    WARC = "warc"

    WAT = "wat"

    CSV = "csv"

    JSONL = "jsonl"

    PARQUET = "parquet"

    LINK_GRAPH = "link_graph"

    FIXTURE = "fixture"

    ALL = {LIVE, WARC, WAT, CSV, JSONL, PARQUET, LINK_GRAPH, FIXTURE}

class MatchMode:

    EXACT_HOSTNAME = "exact_hostname"

    ROOT_DOMAIN = "root_domain"

    EXACT_URL = "exact_url"

    PATH_PREFIX = "path_prefix"

    ALL = {EXACT_HOSTNAME, ROOT_DOMAIN, EXACT_URL, PATH_PREFIX}

class JobStatus:

    PENDING = "pending"

    RUNNING = "running"

    PAUSED = "paused"

    STOPPING = "stopping"

    STOPPED = "stopped"

    COMPLETED = "completed"

    FAILED = "failed"

    ALL = {PENDING, RUNNING, PAUSED, STOPPING, STOPPED, COMPLETED, FAILED}

    ACTIVE = {PENDING, RUNNING, PAUSED, STOPPING}

def utcnow_iso() -> str:

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

@dataclass

class Backlink:

    normalized_target_domain: str = ""

    normalized_target_hostname: str = ""

    normalized_target_url: str = ""

    normalized_source_url: str = ""

    source_url: str = ""

    source_domain: str = ""

    source_hostname: str = ""

    source_title: str = ""

    target_url: str = ""

    target_hostname: str = ""

    anchor_text: str = ""

    image_alt: str = ""

    rel_original: str = ""

    link_type: str = LinkType.UNKNOWN

    source_http_status: Optional[int] = None

    content_type: str = ""

    verification_status: str = VerificationStatus.UNVERIFIED

    live_backlink_present: Optional[int] = None

    first_discovered_at: str = field(default_factory=utcnow_iso)

    last_seen_at: str = field(default_factory=utcnow_iso)

    last_checked_at: Optional[str] = None

    collection: str = ""

    dataset_type: str = ""

    record_filename: str = ""

    record_offset: Optional[int] = None

    record_length: Optional[int] = None

    redirect_chain: str = ""

    evidence_hash: str = ""

    id: Optional[int] = None

    created_at: Optional[str] = None

    updated_at: Optional[str] = None

@dataclass

class ExtractedLink:

    href: str

    resolved_url: str

    hostname: str

    anchor_text: str = ""

    image_alt: str = ""

    rel_original: str = ""

    link_type: str = LinkType.UNKNOWN

    is_image: bool = False
