"""Streaming WARC parser."""

from __future__ import annotations

import io

from dataclasses import dataclass, field

from typing import Dict, Iterator, Optional, BinaryIO, Tuple

from .config import get_config

from .logging_setup import get_logger

from .security import safe_gzip_stream

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

    headers: Dict[str, str] = {}

    first = stream.readline()

    if not first:

        return None

    while first.strip() == b"":

        first = stream.readline()

        if not first:

            return None

    line = first

    if not line.startswith(b"WARC/"):

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

def _parse_http_payload(block: bytes) -> Tuple[Optional[int], Dict[str, str], bytes]:

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

    cfg = get_config()

    if gzipped:

        buf = io.BytesIO()

        for chunk in safe_gzip_stream(stream, cfg.max_decompressed_bytes):

            buf.write(chunk)

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

    gz = path.lower().endswith(".gz")

    with open(path, "rb") as fh:

        yield from iter_warc_records(fh, gzipped=gz, only_responses=only_responses)
