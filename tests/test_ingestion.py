"""Tests: WAT parsing, WARC parsing, file import validation, archived insertion."""

from __future__ import annotations

import os

import pytest

from backlink_hunter_core.importers import (

    ImportError_, import_csv, import_file, import_wat, import_warc,

)
from backlink_hunter_core.models import MatchMode

from backlink_hunter_core.search import SearchFilters, SearchService

from backlink_hunter_core.wat import iter_wat_file

from backlink_hunter_core.warc import iter_warc_file

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def test_wat_parsing_yields_source_and_links():

    path = os.path.join(FIX, "sample.wat")

    pages = list(iter_wat_file(path))

    assert len(pages) == 1

    page = pages[0]

    assert page.source_url.startswith("https://reviewblog.example")

    urls = [l.url for l in page.links]

    assert any("amazon.com/dp/B000TEST" in u for u in urls)

def test_warc_parsing_extracts_html_links():

    path = os.path.join(FIX, "sample.warc")

    recs = list(iter_warc_file(path))

    assert len(recs) == 1

    assert recs[0].record_type == "response"

    assert "amazon.com" in recs[0].html

def test_wat_import_excludes_plaintext_and_false_positives(db):

    path = os.path.join(FIX, "sample.wat")

    bls = list(import_wat(path, collection="fixture"))

    db.insert_backlinks(bls)

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", mode=MatchMode.ROOT_DOMAIN)

    assert svc.count(f) >= 1

def test_warc_import_inserts_backlinks(db):

    path = os.path.join(FIX, "sample.warc")

    bls = list(import_warc(path, collection="fixture"))

    inserted, _ = db.insert_backlinks(bls)

    assert inserted >= 1

    svc = SearchService(db)

    assert svc.count(SearchFilters(target="amazon.com")) >= 1

def test_csv_import(db):

    path = os.path.join(FIX, "sample.csv")

    bls = list(import_csv(path))

    assert len(bls) >= 2

    db.insert_backlinks(bls)

    svc = SearchService(db)

    assert svc.count(SearchFilters(target="amazon.com")) >= 1

def test_csv_missing_columns_rejected(tmp_path):

    bad = tmp_path / "bad.csv"

    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")

    with pytest.raises(ImportError_):

        list(import_csv(str(bad)))

def test_unsupported_format_rejected(tmp_path):

    bad = tmp_path / "data.xyz"

    bad.write_text("nope", encoding="utf-8")

    with pytest.raises(ImportError_):

        list(import_file(str(bad)))

def test_gzip_warc_import(db):

    path = os.path.join(FIX, "sample.warc.gz")

    bls = list(import_warc(path, collection="fixture"))

    assert len(bls) >= 1
