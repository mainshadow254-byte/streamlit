import gzip  
  
from backlink_hunter_core.warc import parse_warc_record  
  
  
def build(uri: str, body: bytes) -> bytes:  
    http = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + body  
    headers = (  
        "WARC/1.0\r\n"  
        "WARC-Type: response\r\n"  
        f"WARC-Target-URI: {uri}\r\n"  
        f"Content-Length: {len(http)}\r\n"  
    ).encode()  
    return gzip.compress(headers + b"\r\n" + http)  
  
  
def test_parse_response_record():  
    raw = build(  
        "https://blog.test/p",  
        b"<html><title>T</title><a href='https://example.com'>x</a></html>",  
    )  
    r = parse_warc_record(raw)  
    assert r is not None  
    assert r.http_status == 200  
    assert r.target_uri == "https://blog.test/p"  
    assert "example.com" in r.html  
    assert "text/html" in r.content_type  
  
  
def test_non_response_record_ignored():  
    http = b"HTTP/1.1 200 OK\r\n\r\nx"  
    headers = b"WARC/1.0\r\nWARC-Type: request\r\nWARC-Target-URI: x\r\n"  
    raw = gzip.compress(headers + b"\r\n" + http)  
    assert parse_warc_record(raw) is None
