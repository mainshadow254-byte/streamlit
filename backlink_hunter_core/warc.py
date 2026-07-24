"""Streaming WARC parser.

Parses WARC records from a byte stream (optionally gzip-compressed), yielding

response records with their HTTP payload. Designed for streaming so whole files

are never loaded into memory. Decompression is size-capped.

"""

from __future__ import annotations

import io

from dataclasses import dataclass, field

from typing import Dict, Iterator, Optional, BinaryIO

from .config import get_config

from .logging_setup import get_logger

from .security import safe_gzip_stream, SecurityError

log = get_logger("warc")

@dataclass

class WarcRecord:

    record_type: str

    target_uri: str

    content_type: str

    headers: Dict[str, str] = field(default_factory=dict)

    http_status: Optional[int] = None

    http_headers: Dict[str, str] = field(default_factory=dict)

    payload: bytes = b""

    @property

    def html(self) -> str:

        try:

            return self.payload.decode("utf-8", errors="replace")

        except Exception:

            return ""

def _read_headers(stream: BinaryIO) -> Optional[Dict[str, str]]:

    """Read WARC header block (until blank line). Returns None at EOF."""

    headers: Dict[str, str] = {}

    first = stream.readline()

    if not first:

        return None

    # Skip blank lines between records.

    while first.strip() == b"":

        first = stream.readline()

        if not first:

            return None

    line = first

    if not line.startswith(b"WARC/"):

        # Not a WARC record start; try to resync by reading forward.

        return {}

    headers["_version"] = line.strip().decode("ascii", "replace")

    while True:

        line = stream.readline()

        if not line or line in (b"\r\n", b"\n"):

            break

        if b":" in line:

            k, v = line.split(b":", 1)

            headers[k.strip().decode("ascii", "replace").lower()] = \

                v.strip().decode("utf-8", "replace")

    return headers

def _parse_http_payload(block: bytes) -> (Optional[int], Dict[str, str], bytes):

    """Split an HTTP response block into (status, headers, body)."""

    sep = b"\r\n\r\n"

    idx = block.find(sep)

    if idx == -1:

        sep = b"\n\n"

        idx = block.find(sep)

        if idx == -1:

            return None, {}, block

    head = block[:idx]

    body = block[idx + len(sep):]

    lines = head.split(b"\n")

    status = None

    http_headers: Dict[str, str] = {}

    if lines:

        status_line = lines[0].strip().decode("ascii", "replace")

        parts = status_line.split()

        if len(parts) >= 2 and parts[0].startswith("HTTP"):

            try:

                status = int(parts[1])

            except ValueError:

                status = None

        for hl in lines[1:]:

            if b":" in hl:

                k, v = hl.split(b":", 1)

                http_headers[k.strip().decode("ascii", "replace").lower()] = \

                    v.strip().decode("utf-8", "replace")

    return status, http_headers, body

def iter_warc_records(stream: BinaryIO, gzipped: bool = False,

                      only_responses: bool = True) -> Iterator[WarcRecord]:

    """Yield WarcRecord objects from a WARC stream."""

    cfg = get_config()

    if gzipped:

        # Decompress into a bounded in-memory buffer, then parse.

        buf = io.BytesIO()

        total = 0

        for chunk in safe_gzip_stream(stream, cfg.max_decompressed_bytes):

            buf.write(chunk)

            total += len(chunk)

        buf.seek(0)

        stream = buf

    while True:

        headers = _read_headers(stream)

        if headers is None:

            break

        if not headers:

            continue

        try:

            length = int(headers.get("content-length", "0"))

        except ValueError:

            length = 0

        payload = stream.read(length) if length > 0 else b""

        # Consume trailing CRLFCRLF between records.

        stream.read(4)

        rec_type = headers.get("warc-type", "")

        if only_responses and rec_type != "response":

            continue

        target_uri = headers.get("warc-target-uri", "")

        content_type = headers.get("content-type", "")

        status, http_headers, body = (None, {}, payload)

        if rec_type == "response":

            status, http_headers, body = _parse_http_payload(payload)

        yield WarcRecord(

            record_type=rec_type,

            target_uri=target_uri,

            content_type=content_type,

            headers=headers,

            http_status=status,

            http_headers=http_headers,

            payload=body,

        )

def iter_warc_file(path: str, only_responses: bool = True) -> Iterator[WarcRecord]:

    """Open a .warc or .warc.gz file and yield records."""

    gz = path.lower().endswith(".gz")

    with open(path, "rb") as fh:

        yield from iter_warc_records(fh, gzipped=gz, only_responses=only_responses)✅ Part 1 of this batch complete — warc.py is whole.Now the WAT parser.PART: backlink_hunter_core/wat.pyPythonCopied!Copy"""Streaming WAT parser.

WAT records are themselves WARC "metadata" records whose payload is JSON

describing a captured page, including extracted outbound links under

Envelope > Payload-Metadata > HTTP-Response-Metadata > HTML-Metadata > Links.

We reuse the WARC framing from warc.py, then decode the JSON payload of each

metadata record and yield structured page-link data.

"""

from __future__ import annotations

import json

from dataclasses import dataclass, field

from typing import BinaryIO, Dict, Iterator, List, Optional

from .logging_setup import get_logger

from .warc import iter_warc_records, iter_warc_file

log = get_logger("wat")

@dataclass

class WatLink:

    url: str            # raw href/url as recorded

    text: str = ""      # anchor text

    rel: str = ""

    alt: str = ""

    path: str = ""      # e.g. "A@/href", "IMG@/src"

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

    """Yield WatPage objects from a WAT stream."""

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

        yield from iter_wat_records(fh, gzipped=gz)✅ Part complete — warc.py and wat.py are whole.Say next for commoncrawl.py (collection listing + CDX lookups + byte-range fetching).
