"""Public-suffix-aware URL/domain normalization."""
from __future__ import annotations
from urllib.parse import urlsplit, urlunsplit
import tldextract
# Bundled snapshot; no network call at runtime.
_extract = tldextract.TLDExtract(suffix_list_urls=())
def registrable_domain(host: str) -> str:
    """Return eTLD+1, e.g. 'www.amazon.co.uk' -> 'amazon.co.uk'."""
    host = (host or "").strip().lower().rstrip(".")
    ext = _extract(host)
    if not ext.domain or not ext.suffix:
        return host
    return f"{ext.domain}.{ext.suffix}"
def hostname_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
def normalize_url(url: str, *, strip_fragment: bool = True) -> str:
    """Normalize scheme/host casing, default ports, fragments, repeated slashes.
    Query parameters are preserved (never stripped blindly).
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    port = parts.port
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if path == "":
        path = "/"
    fragment = "" if strip_fragment else parts.fragment
    return urlunsplit((scheme, host, path, parts.query, fragment))
def normalize_domain_input(raw: str) -> str:
    """Accept 'https://www.amazon.com/path', 'amazon.com', etc. -> registrable domain."""
    raw = (raw or "").strip()
    if "://" not in raw:
        raw = "http://" + raw
    return registrable_domain(hostname_of(raw))
