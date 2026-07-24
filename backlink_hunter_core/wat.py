"""Streaming WAT parser."""

from __future__ import annotations

import json

from dataclasses import dataclass, field

from typing import BinaryIO, Dict, Iterator, List, Optional

from .logging_setup import get_logger

from .warc import iter_warc_records

log = get_logger("wat")

@dataclass

class WatLink:

    url: str

    text: str = ""

    rel: str = ""

    alt: str = ""

    path: str = ""

@dataclass

class WatPage:

    source_url: str

    title: str = ""

    links: List[WatLink] = field(default_factory=list)

def _extract_links(html_meta: Dict) -> List[WatLink]:

    out: List[WatLink] = []

    raw_links = html_meta.get("Links") or []

    for item in raw_links:

        if not isinstance(item, dict):

            continue

        url = item.get("url") or item.get("href") or ""

        if not url:

            continue

        out.append(WatLink(

            url=url,

            text=item.get("text", "") or "",

            rel=item.get("rel", "") or "",

            alt=item.get("alt", "") or "",

            path=item.get("path", "") or "",

        ))

    return out

def _page_from_json(doc: Dict) -> Optional[WatPage]:

    try:

        envelope = doc["Envelope"]

        warc_hdr = envelope.get("WARC-Header-Metadata", {})

        source_url = warc_hdr.get("WARC-Target-URI", "")

        payload_meta = envelope.get("Payload-Metadata", {})

        http_meta = payload_meta.get("HTTP-Response-Metadata", {})

        html_meta = http_meta.get("HTML-Metadata", {})

    except (KeyError, AttributeError, TypeError):

        return None

    if not source_url:

        return None

    head = html_meta.get("Head", {}) if isinstance(html_meta, dict) else {}

    title = head.get("Title", "") if isinstance(head, dict) else ""

    links = _extract_links(html_meta) if isinstance(html_meta, dict) else []

    return WatPage(source_url=source_url, title=title, links=links)

def iter_wat_records(stream: BinaryIO, gzipped: bool = False) -> Iterator[WatPage]:

    for rec in iter_warc_records(stream, gzipped=gzipped, only_responses=False):

        if rec.record_type != "metadata":

            continue

        try:

            doc = json.loads(rec.payload.decode("utf-8", errors="replace"))

        except (json.JSONDecodeError, UnicodeDecodeError):

            continue

        page = _page_from_json(doc)

        if page:

            yield page

def iter_wat_file(path: str) -> Iterator[WatPage]:

    gz = path.lower().endswith(".gz")

    with open(path, "rb") as fh:

        yield from iter_wat_records(fh, gzipped=gz)
