"""Regenerate text/binary fixtures. Run: python tests/build_fixtures.py"""  
from __future__ import annotations  
  
import gzip  
from pathlib import Path  
  
FIX = Path(__file__).parent / "fixtures"  
  
  
def build_warc_member(uri: str, body: bytes) -> bytes:  
    http = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + body  
    warc_headers = (  
        "WARC/1.0\r\n"  
        "WARC-Type: response\r\n"  
        f"WARC-Target-URI: {uri}\r\n"  
        f"Content-Length: {len(http)}\r\n"  
    ).encode()  
    return gzip.compress(warc_headers + b"\r\n" + http)  
  
  
if __name__ == "__main__":  
    FIX.mkdir(parents=True, exist_ok=True)  
    body = (  
        b"<html><head><title>Archived</title></head><body>"  
        b"<a href='https://example.com/from-archive'>link</a></body></html>"  
    )  
    (FIX / "sample_record.warc.gz").write_bytes(  
        build_warc_member("https://archive.test/page", body)  
    )  
    print("Fixtures written to", FIX)
