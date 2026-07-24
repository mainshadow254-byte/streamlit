"""Tests: SSRF protection, private/loopback/link-local/metadata blocking,

redirect safety, response-size limits, decompression-bomb protection."""

from __future__ import annotations

import pytest

from backlink_hunter_core.security import (

    SecurityError, assert_safe_url, validate_url_scheme_host,

    resolve_and_validate, safe_gzip_decompress, is_allowed_upload, safe_join,

)

def test_scheme_validation_rejects_non_http():

    with pytest.raises(SecurityError):

        validate_url_scheme_host("ftp://example.com/x")

    with pytest.raises(SecurityError):

        validate_url_scheme_host("file:///etc/passwd")

def test_blocked_localhost():

    with pytest.raises(SecurityError):

        validate_url_scheme_host("http://localhost/x")

def test_blocked_ip_literals():

    for url in [

        "http://127.0.0.1/",

        "http://10.0.0.1/",

        "http://192.168.1.1/",

        "http://169.254.169.254/latest/meta-data/",

        "http://[::1]/",

    ]:

        with pytest.raises(SecurityError):

            validate_url_scheme_host(url)

def test_public_ip_literal_allowed():

    scheme, host, port = validate_url_scheme_host("https://8.8.8.8/")

    assert scheme == "https"

    assert host == "8.8.8.8"

    assert port == 443

def test_resolve_and_validate_blocks_private(monkeypatch):

    import socket

    def fake_getaddrinfo(host, *a, **k):

        return [(socket.AF_INET, None, None, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(SecurityError):

        resolve_and_validate("evil.example")

def test_resolve_and_validate_allows_public(monkeypatch):

    import socket

    def fake_getaddrinfo(host, *a, **k):

        return [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    addrs = resolve_and_validate("example.com")

    assert "93.184.216.34" in addrs

def test_dns_rebinding_one_bad_address_blocks(monkeypatch):

    import socket

    def fake_getaddrinfo(host, *a, **k):

        return [

            (socket.AF_INET, None, None, "", ("93.184.216.34", 0)),

            (socket.AF_INET, None, None, "", ("127.0.0.1", 0)),

        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(SecurityError):

        resolve_and_validate("rebind.example")

def test_decompression_bomb_capped():

    import gzip

    payload = gzip.compress(b"A" * (2 * 1024 * 1024))

    # cap smaller than output

    with pytest.raises(SecurityError):

        safe_gzip_decompress(payload, max_bytes=1024)

def test_decompression_within_cap_ok():

    import gzip

    payload = gzip.compress(b"hello world")

    out = safe_gzip_decompress(payload, max_bytes=1024)

    assert out == b"hello world"

def test_upload_type_validation():

    assert is_allowed_upload("data.csv")

    assert is_allowed_upload("dump.warc.gz")

    assert not is_allowed_upload("evil.exe")

    assert not is_allowed_upload("script.sh")

def test_path_traversal_blocked(tmp_path):

    base = str(tmp_path)

    # A filename component only; traversal attempt should be neutralised.

    joined = safe_join(base, "../../etc/passwd")

    assert joined.startswith(str(tmp_path))

    assert "passwd" in joined  # basename kept, parents stripped
