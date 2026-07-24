"""Tests: migrations, insertion/dedup, paginated search, filters, streamed export."""

from __future__ import annotations

import json

import os

from backlink_hunter_core.export import (

    export_csv, export_json, export_source_urls, export_source_target_pairs,

    read_and_cleanup,

)
from backlink_hunter_core.importers import build_backlink

from backlink_hunter_core.models import DatasetType, LinkType, MatchMode

from backlink_hunter_core.search import SearchFilters, SearchService

def _mk(source, target, **kw):

    return build_backlink(source_url=source, target_url=target,

                          dataset_type=DatasetType.FIXTURE,

                          collection="test", **kw)

def test_migrations_create_tables(db):

    names = {r["name"] for r in db.conn.execute(

        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    assert "reverse_links" in names

    assert "jobs" in names

    assert "checkpoints" in names

    assert "errors" in names

    assert "search_history" in names

    assert "schema_version" in names

def test_insert_and_count(db):

    bls = [

        _mk("https://a.example/1", "https://amazon.com/x", anchor_text="a"),

        _mk("https://b.example/2", "https://amazon.com/y", anchor_text="b"),

    ]

    inserted, dupes = db.insert_backlinks(bls)

    assert inserted == 2

    assert db.total_backlinks() == 2

def test_duplicate_source_target_deduped(db):

    bl1 = _mk("https://a.example/1", "https://amazon.com/x")

    bl2 = _mk("https://a.example/1", "https://amazon.com/x")

    db.insert_backlinks([bl1])

    db.insert_backlinks([bl2])

    assert db.total_backlinks() == 1

def test_paginated_search(db):

    bls = [_mk(f"https://s{i}.example/p", "https://amazon.com/x")

           for i in range(25)]

    db.insert_backlinks(bls)

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", mode=MatchMode.ROOT_DOMAIN)

    assert svc.count(f) == 25

    p1 = svc.page(f, page=1, page_size=10)

    p2 = svc.page(f, page=2, page_size=10)

    p3 = svc.page(f, page=3, page_size=10)

    assert len(p1) == 10 and len(p2) == 10 and len(p3) == 5

def test_search_root_domain_vs_false_positive(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://www.amazon.com/x"),

        _mk("https://b.example/2", "https://notamazon.com/x"),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", mode=MatchMode.ROOT_DOMAIN)

    assert svc.count(f) == 1

def test_link_type_filter(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://amazon.com/x", rel_original="nofollow"),

        _mk("https://b.example/2", "https://amazon.com/y", rel_original=""),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", link_types=[LinkType.NOFOLLOW])

    assert svc.count(f) == 1

def test_exclude_blank_anchor(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://amazon.com/x", anchor_text="hi"),

        _mk("https://b.example/2", "https://amazon.com/y", anchor_text=""),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", exclude_blank_anchor=True)

    assert svc.count(f) == 1

def test_unique_source_domain(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://amazon.com/x"),

        _mk("https://a.example/2", "https://amazon.com/y"),

        _mk("https://b.example/3", "https://amazon.com/z"),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", unique_source_domain=True)

    assert svc.count(f) == 2

def test_streamed_csv_export(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://amazon.com/x", anchor_text="a"),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com")

    path = export_csv(svc, f)

    data = read_and_cleanup(path)

    assert b"source_url" in data

    assert b"amazon.com" in data

def test_streamed_json_export_is_valid(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://amazon.com/x"),

        _mk("https://b.example/2", "https://amazon.com/y"),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com")

    path = export_json(svc, f)

    data = read_and_cleanup(path)

    parsed = json.loads(data.decode("utf-8"))

    assert isinstance(parsed, list)

    assert len(parsed) == 2

def test_export_unique_source_urls(db):

    db.insert_backlinks([

        _mk("https://a.example/1", "https://amazon.com/x"),

        _mk("https://a.example/1", "https://amazon.com/y"),

    ])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com")

    path = export_source_urls(svc, f)

    data = read_and_cleanup(path).decode("utf-8").strip().splitlines()

    assert data.count("https://a.example/1") == 1

def test_export_source_target_pairs(db):

    db.insert_backlinks([_mk("https://a.example/1", "https://amazon.com/x")])

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com")

    path = export_source_target_pairs(svc, f)

    data = read_and_cleanup(path).decode("utf-8")

    assert "\t" in data

def test_delete_collection(db):

    db.insert_backlinks([_mk("https://a.example/1", "https://amazon.com/x")])

    assert db.total_backlinks() == 1

    db.delete_collection("test")

    assert db.total_backlinks() == 0

def test_integrity_check_ok(db):

    assert db.integrity_check() == "ok"

def test_empty_index_detected(db):

    assert db.is_empty()

    db.insert_backlinks([_mk("https://a.example/1", "https://amazon.com/x")])

    assert not db.is_empty()
