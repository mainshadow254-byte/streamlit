"""Tests: URL normalization, domain normalization, matching, false positives."""

from __future__ import annotations

from backlink_hunter_core.normalize import (

    extract_hostname, is_ignored_href, normalize_url, registrable_domain,

    resolve_url, normalize_target_domain,

)
from backlink_hunter_core.matching import TargetSpec, link_matches_target

from backlink_hunter_core.models import MatchMode

def test_registrable_domain_basic():

    assert registrable_domain("www.amazon.com") == "amazon.com"

    assert registrable_domain("shop.amazon.com") == "amazon.com"

    assert registrable_domain("amazon.com") == "amazon.com"

def test_registrable_domain_multilabel_suffix():

    assert registrable_domain("shop.amazon.co.uk") == "amazon.co.uk"

    assert registrable_domain("www.example.co.uk") == "example.co.uk"

def test_normalize_url_removes_default_port_and_fragment():

    assert normalize_url("https://Example.com:443/path#frag") == \

        "https://example.com/path"

    assert normalize_url("http://example.com:80/") == "http://example.com/"

def test_normalize_url_preserves_query():

    url = "https://example.com/search?q=shoes&page=2"

    assert normalize_url(url) == url

def test_ignored_schemes():

    assert is_ignored_href("mailto:x@y.com")

    assert is_ignored_href("javascript:void(0)")

    assert is_ignored_href("tel:+123")

    assert is_ignored_href("data:text/plain,hi")

    assert is_ignored_href("")

    assert is_ignored_href("#section")

    assert not is_ignored_href("https://example.com")

def test_resolve_relative_and_protocol_relative():

    base = "https://blog.example/post"

    assert resolve_url(base, "/a/b").startswith("https://blog.example/a/b")

    assert resolve_url(base, "//cdn.example.net/x").startswith("https://cdn.example.net/x")

    assert resolve_url(base, "mailto:a@b.com") is None

def test_exact_hostname_match():

    spec = TargetSpec.parse("amazon.com", MatchMode.EXACT_HOSTNAME)

    assert not link_matches_target("https://www.amazon.com/x", spec)

    assert link_matches_target("https://amazon.com/x", spec)

def test_root_domain_match_includes_subdomains():

    spec = TargetSpec.parse("amazon.com", MatchMode.ROOT_DOMAIN)

    assert link_matches_target("https://www.amazon.com/x", spec)

    assert link_matches_target("https://shop.amazon.com/x", spec)

    assert link_matches_target("https://amazon.com/x", spec)

def test_false_positive_domains_rejected():

    spec = TargetSpec.parse("amazon.com", MatchMode.ROOT_DOMAIN)

    assert not link_matches_target("https://notamazon.com/x", spec)

    assert not link_matches_target("https://amazon.com.example.org/x", spec)

def test_exact_url_match():

    spec = TargetSpec.parse("https://amazon.com/dp/1", MatchMode.EXACT_URL)

    assert link_matches_target("https://amazon.com/dp/1", spec)

    assert not link_matches_target("https://amazon.com/dp/2", spec)

def test_path_prefix_match():

    spec = TargetSpec.parse("amazon.com/dp", MatchMode.PATH_PREFIX)

    assert link_matches_target("https://amazon.com/dp/123", spec)

    assert not link_matches_target("https://amazon.com/gp/123", spec)

def test_normalize_target_domain_from_url():

    assert normalize_target_domain("https://www.amazon.com/dp/1") == "amazon.com"
