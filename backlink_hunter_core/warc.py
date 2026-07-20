"""WARC record parsing from raw (gzip) byte ranges fetched from Common Crawl."""
from __future__ import annotations
import gzip
import zlib
from dataclasses import dataclass
from typing import Optional
@dataclass
class WarcResponse:
    target_uri: str
    http_status: Optional[int]
    content_type: str
    html: str
def _decompress_member(raw: bytes) -> bytes:
    """CC stores each record as an independent gzip member."""
    try:
        return gzip.decompress(raw)
    except (OSError, EOFError):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return d.decompress(raw)
def parse_warc_record(
    raw_bytes: bytes, *, max_html_bytes: int = 10_485_760
) -> Optional[WarcResponse]:
    """Parse one gzip-compressed WARC 'response' record into a WarcResponse."""
    data = _decompress_member(raw_bytes)
    sep = data.find(b"\r\n\r\n")
    if sep == -1:
        return None
    warc_headers = data[:sep].decode("utf-8", "replace")
    remainder = data[sep + 4:]
    if "warc-type: response" not in warc_headers.lower():
        return None
    target_uri = ""
    for line in warc_headers.splitlines():
        if line.lower().startswith("warc-target-uri:"):
            target_uri = line.split(":", 1)[1].strip()
    http_sep = remainder.find(b"\r\n\r\n")
    if http_sep == -1:
        return None
    http_head = remainder[:http_sep].decode("utf-8", "replace")
    body = remainder[http_sep + 4:]
    status: Optional[int] = None
    content_type = ""
    lines = http_head.splitlines()
    if lines:
        parts = lines[0].split()
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
    for line in lines[1:]:
        if line.lower().startswith("content-type:"):
            content_type = line.split(":", 1)[1].strip()
    if len(body) > max_html_bytes:
        body = body[:max_html_bytes]
    return WarcResponse(
        target_uri=target_uri,
        http_status=status,
        content_type=content_type,
        html=body.decode("utf-8", "replace"),
    )
