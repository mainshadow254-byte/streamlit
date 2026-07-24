"""Tests: checkpoints, pause/resume/cancel flags, empty-index message, proof mode."""

from __future__ import annotations

import os

from backlink_hunter_core.importers import import_wat

from backlink_hunter_core.index_jobs import JobManager

from backlink_hunter_core.models import JobStatus, MatchMode

from backlink_hunter_core.search import SearchFilters, SearchService

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

EMPTY_INDEX_MESSAGE = (

    "No backlink index is available yet. Open Index Manager and build or "

    "import a real backlink index first."

)

def test_create_and_update_job(db):

    jm = JobManager(db)

    handle = jm.create("index", {"collection": "test"})

    handle.bump("backlinks_inserted", 5)

    handle.flush(stage="running")

    row = db.get_job(handle.job_id)

    assert row["stats"]["backlinks_inserted"] == 5

    assert row["stage"] == "running"

def test_pause_resume_flags(db):

    jm = JobManager(db)

    handle = jm.create("index", {})

    jm.pause(handle.job_id)

    assert handle.is_paused() is True

    jm.resume(handle.job_id)

    assert handle.is_paused() is False

def test_cancel_flag(db):

    jm = JobManager(db)

    handle = jm.create("index", {})

    jm.stop(handle.job_id)

    assert handle.is_cancelled() is True

    assert db.get_job(handle.job_id)["status"] == JobStatus.STOPPING

def test_checkpoint_save_load(db):

    jm = JobManager(db)

    handle = jm.create("index", {})

    handle.save_checkpoint("wat", {"file_index": 3, "records_read": 100})

    state = handle.load_checkpoint("wat")

    assert state["file_index"] == 3

    assert state["records_read"] == 100

def test_checkpoint_overwrite(db):

    jm = JobManager(db)

    handle = jm.create("index", {})

    handle.save_checkpoint("wat", {"file_index": 1})

    handle.save_checkpoint("wat", {"file_index": 9})

    assert handle.load_checkpoint("wat")["file_index"] == 9

def test_empty_index_message_condition(db):

    assert db.is_empty()

    assert EMPTY_INDEX_MESSAGE.startswith("No backlink index is available yet.")

def test_proof_mode_full_pipeline(db):

    path = os.path.join(FIX, "sample.wat")

    bls = list(import_wat(path, collection="proof-fixture"))

    inserted, _ = db.insert_backlinks(bls)

    assert inserted >= 1

    svc = SearchService(db)

    f = SearchFilters(target="amazon.com", mode=MatchMode.ROOT_DOMAIN)

    total = svc.count(f)

    assert total >= 1

    rows = svc.page(f, page=1, page_size=50)

    assert any(r["source_url"].startswith("https://reviewblog.example")

               for r in rows)

    from backlink_hunter_core.export import export_csv, read_and_cleanup

    data = read_and_cleanup(export_csv(svc, f))

    assert b"amazon.com" in data

    for r in rows:

        assert r["target_url"]

        assert r["normalized_target_domain"]

def test_proof_mode_false_positive_excluded(db):

    path = os.path.join(FIX, "sample.wat")

    db.insert_backlinks(list(import_wat(path, collection="proof-fixture")))

    svc = SearchService(db)

    amazon_rows = svc.page(

        SearchFilters(target="amazon.com", mode=MatchMode.ROOT_DOMAIN),

        page=1, page_size=100)

    for r in amazon_rows:

        assert "notamazon.com" not in r["target_hostname"]
