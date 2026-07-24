"""Common Crawl integration.

Provides:

  - collection listing (collinfo.json)

  - CDX index queries for a domain/url

  - byte-range retrieval of WARC/WAT records via the safe HTTP client

Network access is required only for real Common Crawl operations; all functions

degrade gracefully and raise clear errors when offline. Unit tests mock the

HTTP client, so importing this module never triggers network access.

"""

from __future__ import annotations

import gzip

import io

import json

from dataclasses import dataclass, field

from typing import Dict, Iterator, List, Optional

from .config import Config, get_config

from .logging_setup import get_logger

from .net import FetchError, SafeHTTPClient

from .warc import iter_warc_records

from .wat import iter_wat_records

log = get_logger("commoncrawl")

@dataclass

class Collection:

    id: str

    name: str

    cdx_api: str

    timegate: str = ""

@dataclass

class CdxRecord:

    urlkey: str

    timestamp: str

    url: str

    mime: str

    status: str

    digest: str

    length: int

    offset: int

    filename: str

    @property

    def warc_url(self) -> str:

        return filename_to_data_url(self.filename)

def filename_to_data_url(filename: str, cfg: Optional[Config] = None) -> str:

    cfg = cfg or get_config()

    return f"{cfg.cc_data_host}/{filename}"

class CommonCrawlClient:

    def __init__(self, client: Optional[SafeHTTPClient] = None,

                 cfg: Optional[Config] = None):

        self.cfg = cfg or get_config()

        self.client = client or SafeHTTPClient(self.cfg)

    # ------------------------------------------------------------------ #

    def list_collections(self) -> List[Collection]:

        res = self.client.fetch(self.cfg.cc_collinfo_url, respect_robots=False)

        if res.status != 200:

            raise FetchError(f"collinfo returned {res.status}")

        data = json.loads(res.text)

        out: List[Collection] = []

        for item in data:

            out.append(Collection(

                id=item.get("id", ""),

                name=item.get("name", ""),

                cdx_api=item.get("cdx-api", ""),

                timegate=item.get("timegate", ""),

            ))

        return out

    def _cdx_api_for(self, collection_id: str) -> str:

        return f"{self.cfg.cc_index_server}/{collection_id}-index"

    # ------------------------------------------------------------------ #

    def query_cdx(self, collection_id: str, url_pattern: str,

                  limit: int = 1000, match_type: str = "domain",

                  filters: Optional[List[str]] = None) -> Iterator[CdxRecord]:

        """Query the CDX index. Yields CdxRecord objects.

        match_type: 'exact' | 'prefix' | 'host' | 'domain'

        """

        api = self._cdx_api_for(collection_id)

        query = (

            f"{api}?url={url_pattern}&output=json"

            f"&matchType={match_type}&limit={limit}"

        )

        for extra in (filters or []):

            query += f"&filter={extra}"

        res = self.client.fetch(query, respect_robots=False)

        if res.status == 404:

            return

        if res.status != 200:

            raise FetchError(f"CDX query returned {res.status}")

        for line in res.text.splitlines():

            line = line.strip()

            if not line:

                continue

            try:

                obj = json.loads(line)

            except json.JSONDecodeError:

                continue

            try:

                yield CdxRecord(

                    urlkey=obj.get("urlkey", ""),

                    timestamp=obj.get("timestamp", ""),

                    url=obj.get("url", ""),

                    mime=obj.get("mime", ""),

                    status=obj.get("status", ""),

                    digest=obj.get("digest", ""),

                    length=int(obj.get("length", 0) or 0),

                    offset=int(obj.get("offset", 0) or 0),

                    filename=obj.get("filename", ""),

                )

            except (ValueError, TypeError):

                continue

    # ------------------------------------------------------------------ #

    def fetch_record_bytes(self, filename: str, offset: int,

                           length: int) -> bytes:

        """Fetch a single gzipped WARC/WAT record via HTTP Range."""

        url = filename_to_data_url(filename, self.cfg)

        raw = self.client.get_range(url, offset, length)

        return raw

    def iter_warc_from_record(self, filename: str, offset: int, length: int):

        """Fetch a WARC record byte range and parse it (single record)."""

        raw = self.fetch_record_bytes(filename, offset, length)

        stream = io.BytesIO(raw)

        yield from iter_warc_records(stream, gzipped=True, only_responses=True)

    def iter_wat_from_record(self, filename: str, offset: int, length: int):

        raw = self.fetch_record_bytes(filename, offset, length)

        stream = io.BytesIO(raw)

        yield from iter_wat_records(stream, gzipped=True)

    # ------------------------------------------------------------------ #

    def list_wat_paths(self, collection_id: str,

                       max_files: Optional[int] = None) -> List[str]:

        """Fetch the wat.paths.gz listing for a collection.

        Returns relative dataset paths under the CC data host.

        """

        url = (f"{self.cfg.cc_data_host}/crawl-data/"

               f"{collection_id}/wat.paths.gz")

        res = self.client.fetch(url, respect_robots=False)

        if res.status != 200:

            raise FetchError(f"wat.paths returned {res.status}")

        try:

            text = gzip.decompress(res.body).decode("utf-8", errors="replace")

        except (OSError, EOFError) as exc:

            raise FetchError(f"Could not decompress wat.paths: {exc}")

        paths = [ln.strip() for ln in text.splitlines() if ln.strip()]

        if max_files:

            paths = paths[:max_files]

        return paths

    def list_warc_paths(self, collection_id: str,

                        max_files: Optional[int] = None) -> List[str]:

        url = (f"{self.cfg.cc_data_host}/crawl-data/"

               f"{collection_id}/warc.paths.gz")

        res = self.client.fetch(url, respect_robots=False)

        if res.status != 200:

            raise FetchError(f"warc.paths returned {res.status}")

        try:

            text = gzip.decompress(res.body).decode("utf-8", errors="replace")

        except (OSError, EOFError) as exc:

            raise FetchError(f"Could not decompress warc.paths: {exc}")

        paths = [ln.strip() for ln in text.splitlines() if ln.strip()]

        if max_files:

            paths = paths[:max_files]

        return paths

    def stream_wat_file(self, relative_path: str) -> Iterator:

        """Stream and parse an entire WAT file from Common Crawl.

        Yields WatPage objects. The file is streamed and decompressed with a

        size cap; it is not fully buffered beyond the gzip bound in warc.py.

        """

        url = f"{self.cfg.cc_data_host}/{relative_path}"

        res = self.client.fetch(url, respect_robots=False,

                                max_bytes=self.cfg.max_decompressed_bytes)

        stream = io.BytesIO(res.body)

        yield from iter_wat_records(stream, gzipped=relative_path.endswith(".gz"))✅ Part complete — commoncrawl.py is whole.Say next for importers.py (CSV / JSONL / Parquet / WARC / WAT / gzip user-supplied dataset importers with validation → Backlink records).
