"""Target matching with strict false-positive protection."""
from __future__ import annotations
from enum import Enum
from urllib.parse import urlsplit
from .normalize import hostname_of, normalize_url, registrable_domain
class MatchMode(str, Enum):
    EXACT_HOST = "exact_host"
    ROOT_AND_SUBDOMAINS = "root_and_subdomains"
    EXACT_URL = "exact_url"
    PATH_PREFIX = "path_prefix"
def _host_is_or_subdomain_of(host: str, root: str) -> bool:
    """Dot-boundary check: 'a.amazon.com' matches 'amazon.com', but
    'notamazon.com' and 'amazon.com.evil.org' do NOT."""
    host = host.lower().rstrip(".")
    root = root.lower().rstrip(".")
    return host == root or host.endswith("." + root)
def matches_target(
    candidate_url: str,
    *,
    mode: MatchMode,
    target_host: str = "",
    target_root: str = "",
    target_url: str = "",
    target_path_prefix: str = "",
) -> bool:
    """Return True only when candidate_url genuinely points at the target."""
    host = hostname_of(candidate_url)
    if not host:
        return False
    if mode is MatchMode.EXACT_HOST:
        return host == target_host.lower().rstrip(".")
    if mode is MatchMode.ROOT_AND_SUBDOMAINS:
        root = target_root or registrable_domain(target_host)
        # registrable domain must equal root -> defeats 'amazon.com.evil.org'
        return registrable_domain(host) == root and _host_is_or_subdomain_of(host, root)
    if mode is MatchMode.EXACT_URL:
        return normalize_url(candidate_url) == normalize_url(target_url)
    if mode is MatchMode.PATH_PREFIX:
        root = target_root or registrable_domain(target_host)
        if not _host_is_or_subdomain_of(host, root):
            return False
        return urlsplit(normalize_url(candidate_url)).path.startswith(
            target_path_prefix or "/"
        )
    return False
