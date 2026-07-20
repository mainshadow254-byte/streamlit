from backlink_hunter_core.normalize import (
    normalize_domain_input, normalize_url, registrable_domain,
)
def test_registrable_multilevel_tld():
    assert registrable_domain("www.amazon.co.uk") == "amazon.co.uk"
def test_registrable_simple():
    assert registrable_domain("a.b.example.com") == "example.com"
def test_domain_input_variants():
    assert normalize_domain_input("https://www.amazon.com/path") == "amazon.com"
    assert normalize_domain_input("amazon.com") == "amazon.com"
    assert normalize_domain_input("www.amazon.com") == "amazon.com"
def test_normalize_url_defaults():
    assert normalize_url("HTTP://Example.com:80/a//b#frag") == "http://example.com/a/b"
def test_normalize_url_preserves_query():
    assert normalize_url("https://x.com/p?a=1&b=2") == "https://x.com/p?a=1&b=2"
