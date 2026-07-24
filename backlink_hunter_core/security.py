"""SSRF protection, URL safety, decompression-bomb guards, temp-file safety."""

from __future__ import annotations

import gzip

import ipaddress

import os

import socket

import tempfile

from pathlib import Path

from typing import Iterable, List, Optional, Tuple

from urllib.parse import urlparse

from .logging_setup import get_logger

log = get_logger("security")

ALLOWED_SCHEMES = {"http", "https"}

BLOCKED_HOSTNAMES = {

    "localhost",

    "metadata.google.internal",

}
BLOCKED_METADATA_IPS = {

    "169.254.169.254",

    "fd00:ec2::254",

    "100.100.100.200",

}

class SecurityError(Exception):

    """Raised when a URL or resource fails a safety check."""

def _is_blocked_ip(ip) -> bool:

    if str(ip) in BLOCKED_METADATA_IPS:

        return True

    return (

        ip.is_private

        or ip.is_loopback

        or ip.is_link_local

        or ip.is_reserved

        or ip.is_multicast

        or ip.is_unspecified

        or (getattr(ip, "is_site_local", False))

    )

def validate_url_scheme_host(url: str) -> Tuple[str, str, int]:

    parsed = urlparse(url)

    scheme = (parsed.scheme or "").lower()

    if scheme not in ALLOWED_SCHEMES:

        raise SecurityError(f"Scheme not allowed: {scheme!r}")

    host = (parsed.hostname or "").lower()

    if not host:

        raise SecurityError("URL has no hostname")

    if host in BLOCKED_HOSTNAMES:

        raise SecurityError(f"Blocked hostname: {host!r}")

    try:

        ip = ipaddress.ip_address(host)

        if _is_blocked_ip(ip):

            raise SecurityError(f"Blocked IP literal: {host!r}")

    except ValueError:

        pass

    port = parsed.port or (443 if scheme == "https" else 80)

    return scheme, host, port

def resolve_and_validate(host: str) -> List[str]:

    try:

        ip = ipaddress.ip_address(host)

        if _is_blocked_ip(ip):

            raise SecurityError(f"Blocked IP: {host!r}")

        return [str(ip)]

    except ValueError:

        pass

    try:

        infos = socket.getaddrinfo(host, None)

    except socket.gaierror as exc:

        raise SecurityError(f"DNS resolution failed for {host!r}: {exc}")

    addresses: List[str] = []

    for info in infos:

        addr = info[4][0]

        try:

            ip = ipaddress.ip_address(addr)

        except ValueError:

            raise SecurityError(f"Unparseable resolved address: {addr!r}")

        if _is_blocked_ip(ip):

            raise SecurityError(f"Host {host!r} resolves to blocked IP {addr}")

        addresses.append(str(ip))

    if not addresses:

        raise SecurityError(f"No addresses resolved for {host!r}")

    return addresses

def assert_safe_url(url: str) -> None:

    _, host, _ = validate_url_scheme_host(url)

    resolve_and_validate(host)

class _BytesReader:

    def __init__(self, data: bytes):

        self._data = data

        self._pos = 0

    def read(self, size: int = -1) -> bytes:

        if size < 0:

            chunk = self._data[self._pos:]

            self._pos = len(self._data)

            return chunk

        chunk = self._data[self._pos:self._pos + size]

        self._pos += len(chunk)

        return chunk

def safe_gzip_decompress(data: bytes, max_bytes: int) -> bytes:

    out = bytearray()

    with gzip.GzipFile(fileobj=_BytesReader(data)) as gz:

        while True:

            chunk = gz.read(65536)

            if not chunk:

                break

            out.extend(chunk)

            if len(out) > max_bytes:

                raise SecurityError(

                    f"Decompressed size exceeds limit ({max_bytes} bytes)"

                )

    return bytes(out)

def safe_gzip_stream(fileobj, max_bytes: int, chunk_size: int = 65536):

    total = 0

    with gzip.GzipFile(fileobj=fileobj) as gz:

        while True:

            chunk = gz.read(chunk_size)

            if not chunk:

                break

            total += len(chunk)

            if total > max_bytes:

                raise SecurityError(

                    f"Decompressed size exceeds limit ({max_bytes} bytes)"

                )

            yield chunk

ALLOWED_UPLOAD_SUFFIXES = {

    ".csv", ".jsonl", ".json", ".parquet",

    ".warc", ".wat", ".gz", ".warc.gz", ".wat.gz",

}

def is_allowed_upload(filename: str) -> bool:

    name = filename.lower()

    return any(name.endswith(suf) for suf in ALLOWED_UPLOAD_SUFFIXES)

def safe_join(base_dir: str, filename: str) -> str:

    base = Path(base_dir).resolve()

    candidate = (base / Path(filename).name).resolve()

    if base not in candidate.parents and candidate != base:

        raise SecurityError("Path traversal attempt detected")

    return str(candidate)

def secure_tempfile(suffix: str = "", prefix: str = "blh_", dir: Optional[str] = None) -> str:

    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)

    os.close(fd)

    return path

def cleanup_files(paths: Iterable[str]) -> None:

    for p in paths:

        try:

            if p and os.path.exists(p):

                os.remove(p)

        except OSError:

            log.warning("Could not remove temp file %s", p)
