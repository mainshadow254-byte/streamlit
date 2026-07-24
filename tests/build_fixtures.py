#!/usr/bin/env python3

"""Build local test fixtures for Backlink Hunter.

Creates small, self-contained WARC, WAT, and CSV fixtures containing GENUINE

hyperlink records plus plain-text mentions (which must NOT be counted). These

are test fixtures only — always tagged dataset_type='fixture' when indexed —

and must never mix with production search results.

Run:  python tests/build_fixtures.py

Output: tests/fixtures/

"""

from __future__ import annotations

import gzip

import json

import os

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

SOURCE_URL = "https://reviewblog.example/post-1"

TARGET_URL = "https://www.amazon.com/dp/B000TEST"

FIXTURE_HTML = """<!DOCTYPE html>

<html>

<head><title>My Review Blog</title></head>

<body>

  <h1>Product review</h1>

  <p>I really like this product. You can buy it on

     <a href="https://www.amazon.com/dp/B000TEST" rel="nofollow sponsored">Amazon</a>.</p>

  <p>I also mention amazon.com here in plain text, but this is NOT a link.</p>

  <a href="/relative/page">A relative internal link</a>

  <a href="//cdn.example.net/asset.js">protocol-relative</a>

  <a href="mailto:owner@example.com">email me</a>

  <a href="javascript:void(0)">js link</a>

  <!-- <a href="https://www.amazon.com/commented">commented out</a> -->

  <a href="https://shop.amazon.co.uk/deals">UK subdomain link</a>

  <a href="https://notamazon.com/page">false positive domain</a>

</body>

</html>

"""

def _warc_record(html: str) -> bytes:

    http_block = (

        "HTTP/1.1 200 OK\r\n"

        "Content-Type: text/html; charset=utf-8\r\n"

        f"Content-Length: {len(html.encode('utf-8'))}\r\n"

        "\r\n"

    ).encode("utf-8") + html.encode("utf-8")

    warc_header = (

        "WARC/1.0\r\n"

        "WARC-Type: response\r\n"

        f"WARC-Target-URI: {SOURCE_URL}\r\n"

        "WARC-Date: 2024-01-01T00:00:00Z\r\n"

        "Content-Type: application/http; msgtype=response\r\n"

        f"Content-Length: {len(http_block)}\r\n"

        "\r\n"

    ).encode("utf-8")

    return warc_header + http_block + b"\r\n\r\n"

def build_warc() -> str:

    os.makedirs(FIXTURES_DIR, exist_ok=True)

    path = os.path.join(FIXTURES_DIR, "sample.warc")

    with open(path, "wb") as fh:

        fh.write(_warc_record(FIXTURE_HTML))

    # gzipped variant

    with open(path, "rb") as src, gzip.open(path + ".gz", "wb") as dst:

        dst.write(src.read())

    return path

def build_wat() -> str:

    os.makedirs(FIXTURES_DIR, exist_ok=True)

    path = os.path.join(FIXTURES_DIR, "sample.wat")

    wat_doc = {

        "Envelope": {

            "WARC-Header-Metadata": {

                "WARC-Type": "response",

                "WARC-Target-URI": SOURCE_URL,

            },

            "Payload-Metadata": {

                "HTTP-Response-Metadata": {

                    "HTML-Metadata": {

                        "Head": {"Title": "My Review Blog"},

                        "Links": [

                            {"url": "https://www.amazon.com/dp/B000TEST",

                             "text": "Amazon", "rel": "nofollow sponsored",

                             "path": "A@/href"},

                            {"url": "/relative/page", "text": "Relative",

                             "path": "A@/href"},

                            {"url": "//cdn.example.net/asset.js",

                             "text": "", "path": "A@/href"},

                            {"url": "https://shop.amazon.co.uk/deals",

                             "text": "UK deals", "path": "A@/href"},

                            {"url": "https://notamazon.com/page",

                             "text": "Not amazon", "path": "A@/href"},

                        ],

                    }

                }

            },

        }

    }

    payload = json.dumps(wat_doc).encode("utf-8")

    warc_header = (

        "WARC/1.0\r\n"

        "WARC-Type: metadata\r\n"

        f"WARC-Target-URI: {SOURCE_URL}\r\n"

        "Content-Type: application/json\r\n"

        f"Content-Length: {len(payload)}\r\n"

        "\r\n"

    ).encode("utf-8")

    with open(path, "wb") as fh:

        fh.write(warc_header + payload + b"\r\n\r\n")

    with open(path, "rb") as src, gzip.open(path + ".gz", "wb") as dst:

        dst.write(src.read())

    return path

def build_csv() -> str:

    os.makedirs(FIXTURES_DIR, exist_ok=True)

    path = os.path.join(FIXTURES_DIR, "sample.csv")

    with open(path, "w", encoding="utf-8") as fh:

        fh.write("source_url,target_url,anchor_text,rel,collection\n")

        fh.write(f"{SOURCE_URL},{TARGET_URL},Amazon,nofollow sponsored,fixture\n")

        fh.write(f"{SOURCE_URL},https://shop.amazon.co.uk/deals,UK deals,,fixture\n")

    return path

def build_all() -> None:

    warc = build_warc()

    wat = build_wat()

    csv = build_csv()

    print(f"Built fixtures in {FIXTURES_DIR}:")

    for p in (warc, warc + ".gz", wat, wat + ".gz", csv):

        print(f"  - {p}")

if __name__ == "__main__":

    build_all()✅ tests/build_fixtures.py is whole.Now the test suite. PART: tests/conftest.pyPythonCopied!Copy"""Shared pytest fixtures."""

from __future__ import annotations

import os

import sys

import pytest

# Ensure repo root on path.

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backlink_hunter_core.config import Config, set_config  # noqa: E402

from backlink_hunter_core.db import Database  # noqa: E402

@pytest.fixture()

def tmp_config(tmp_path):

    cfg = Config()

    cfg.db_path = str(tmp_path / "test.db")

    cfg.log_dir = str(tmp_path / "logs")

    cfg.respect_robots = False

    set_config(cfg)

    return cfg

@pytest.fixture()

def db(tmp_config):

    database = Database(tmp_config)

    yield database

    database.close()

@pytest.fixture(scope="session", autouse=True)

def build_fixtures_once():

    from tests.build_fixtures import build_all

    try:

        build_all()

    except Exception:

        pass

    yield✅ tests/conftest.py is whole.Say next for the actual test modules (normalization/matching, htmlparse/rel, db/migrations/search/export, WAT/WARC/import, verification/SSRF, jobs/checkpoints, empty-index + proof mode).
