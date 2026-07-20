"""Common Crawl collection info, CDX querying, and WARC byte-range fetching.
Honesty note: the CDX index is a FORWARD index (URL -> record). It cannot answer
'who links to domain X'. It is used to retrieve pages *of* seed domains, fetch the
archived HTML, and inspect that HTML for outbound links to the target. True reverse
lookups are handled by linkindex.py.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional
import aiohttp
COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
CC_DATA_BASE = "https://data.commoncrawl.org/"
@dataclass
class CdxRecord:
    url: str
    filename: str
    offset: int
    length: int
    status: str
    mime: str
async def list_collections(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(COLLINFO_URL) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)
async def query_cdx(
    session: aiohttp.ClientSession,
    collection: str,
    url_pattern: str,
    *,
    match_type: str = "domain",
    limit: int = 1000,
) -> AsyncIterator[CdxRecord]:
    """Stream CDX JSON-line records for a URL/domain pattern."""
    endpoint = f"https://index.commoncrawl.org/{collection}-index"
    params = {
        "url": url_pattern,
        "output": "json",
        "matchType": match_type,
        "limit": str(limit),
    }
    async with session.get(endpoint, params=params) as resp:
        if resp.status == 404:
            return
        resp.raise_for_status()
        async for raw_line in resp.content:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                yield CdxRecord(
                    url=rec["url"],
                    filename=rec["filename"],
                    offset=int(rec["offset"]),
                    length=int(rec["length"]),
                    status=rec.get("status", ""),
                    mime=rec.get("mime", ""),
                )
            except (KeyError, ValueError):
                continue
async def fetch_warc_bytes(
    session: aiohttp.ClientSession, rec: CdxRecord, *, max_bytes: int
) -> Optional[bytes]:
    """Fetch ONLY the required byte range for this record (never the whole WARC)."""
    if rec.length > max_bytes:
        return None
    url = CC_DATA_BASE + rec.filename
    headers = {"Range": f"bytes={rec.offset}-{rec.offset + rec.length - 1}"}
    async with session.get(url, headers=headers) as resp:
        if resp.status not in (200, 206):
            return None
        return await resp.content.read(rec.length)
