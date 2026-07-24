"""URL and domain normalization with public-suffix awareness."""

from __future__ import annotations

from typing import Optional

from urllib.parse import urlsplit, urlunsplit, urljoin

try:

    import tldextract  # type: ignore

    _EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

    _HAVE_TLDEXTRACT = True

except Exception:  # pragma: no cover

    _EXTRACT = None

    _HAVE_TLDEXTRACT = False

_MULTI_LABEL_SUFFIXES = {

    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk",

    "com.au", "net.au", "org.au", "gov.au",

    "co.jp", "or.jp", "ne.jp", "ac.jp",

    "com.br", "com.cn", "com.mx", "com.tr",

    "co.in", "co.nz", "co.za", "com.sg", "com.hk",

}

IGNORED_SCHEMES = {

    "javascript", "mailto", "tel", "data", "file", "ftp", "gopher",

    "sms", "callto", "skype",

}

_DEFAULT_PORTS = {"http": "80", "https": "443"}

def idna_encode(host: str) -> str:

    if not host:

        return ""

    host = host.strip().rstrip(".").lower()

    try:

        return host.encode("idna").decode("ascii")

    except (UnicodeError, UnicodeDecodeError):

        try:

            return host.encode("ascii", "ignore").decode("ascii")

        except Exception:

            return host

def registrable_domain(hostname: str) -> str:

    host = idna_encode(hostname)

    if not host:

        return ""

    if _HAVE_TLDEXTRACT and _EXTRACT is not None:

        ext = _EXTRACT(host)

        if ext.domain and ext.suffix:

            return f"{ext.domain}.{ext.suffix}"

        if ext.domain:

            return ext.domain

        return host

    labels = host.split(".")

    if len(labels) <= 2:

        return host

    last_two = ".".join(labels[-2:])

    if last_two in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:

        return ".".join(labels[-3:])

    return last_two

def extract_hostname(url: str) -> str:

    try:

        parts = urlsplit(url if "//" in url else "//" + url)

    except ValueError:

        return ""

    return idna_encode(parts.hostname or "")

def is_ignored_href(href: str) -> bool:

    if href is None:

        return True

    h = href.strip()

    if not h:

        return True

    if h.startswith("#"):

        return True

    scheme = ""

    if ":" in h and not h.startswith("//"):

        scheme = h.split(":", 1)[0].strip().lower()

    return scheme in IGNORED_SCHEMES

def resolve_url(base_url: str, href: str) -> Optional[str]:

    if is_ignored_href(href):

        return None

    href = href.strip()

    if href.startswith("//"):

        base_scheme = urlsplit(base_url).scheme or "https"

        href = f"{base_scheme}:{href}"

    try:

        resolved = urljoin(base_url, href)

    except ValueError:

        return None

    parts = urlsplit(resolved)

    if parts.scheme.lower() not in ("http", "https"):

        return None

    if not parts.hostname:

        return None

    return normalize_url(resolved)

def normalize_url(url: str, keep_fragment: bool = False) -> str:

    try:

        parts = urlsplit(url)

    except ValueError:

        return url

    scheme = (parts.scheme or "").lower()

    host = idna_encode(parts.hostname or "")

    netloc = host

    if parts.port and str(parts.port) != _DEFAULT_PORTS.get(scheme):

        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"

    query = parts.query

    fragment = parts.fragment if keep_fragment else ""

    return urlunsplit((scheme, netloc, path, query, fragment))

def normalize_target_domain(value: str) -> str:

    host = extract_hostname(value) or idna_encode(value)

    return registrable_domain(host)

def normalize_target_hostname(value: str) -> str:

    host = extract_hostname(value)

    if not host:

        host = idna_encode(value)

    return host

def path_of(url: str) -> str:

    try:

        return urlsplit(url).path or "/"

    except ValueError:

        return "/"
