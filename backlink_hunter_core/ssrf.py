"""SSRF protection: resolve DNS and reject non-public destinations."""
from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlsplit
_ALLOWED_SCHEMES = {"http", "https"}
_METADATA_IPS = {"169.254.169.254", "fd00:ec2::254"}
class BlockedTargetError(Exception):
    pass
def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    bad = (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )
    return not bad
def assert_safe_url(url: str) -> list[str]:
    """Validate scheme, resolve host, ensure every resolved IP is public.
    Returns the resolved IPs, or raises BlockedTargetError."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BlockedTargetError(f"Blocked scheme: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise BlockedTargetError("Missing host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedTargetError(f"DNS resolution failed: {exc}") from exc
    ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise BlockedTargetError("No addresses resolved")
    for ip in ips:
        if ip in _METADATA_IPS or not _ip_is_public(ip):
            raise BlockedTargetError(f"Blocked non-public address: {ip}")
    return ips
