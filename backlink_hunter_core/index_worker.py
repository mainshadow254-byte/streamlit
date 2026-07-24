"""Background streaming indexer.

Runs an indexing job in a worker thread, honouring pause / resume / stop flags

that are persisted in SQLite (so control survives browser refreshes). Streams

records, batches inserts, checkpoints progress, and can resume from the last

checkpoint. Supports:

  - Common Crawl WAT ingestion (by collection)

  - Common Crawl WARC ingestion (by collection)

  - User-supplied file import (single file or directory)

"""

from __future__ import annotations

import os

import shutil

import threading

import time

from typing import Any, Dict, Iterator, List, Optional

from .config import Config, get_config

from .db import Database

from .commoncrawl import CommonCrawlClient

from .importers import (

    ImportError_,

    backlinks_from_wat_page,

    backlinks_from_warc_record,

    import_file,

)
from .index_jobs import JobHandle, JobManager

from .logging_setup import get_logger

from .models import Backlink, DatasetType, JobStatus

log = get_logger("index_worker")

class DiskSpaceError(Exception):

    pass

def check_disk_space(path: str, min_free: int) -> int:

    directory = os.path.dirname(os.path.abspath(path)) or "."

    usage = shutil.disk_usage(directory)

    if usage.free < min_free:

        raise DiskSpaceError(

            f"Only {usage.free} bytes free; need at least {min_free}."

        )

    return usage.free

class IndexWorker:

    def __init__(self, db: Database, cfg: Optional[Config] = None,

                 cc_client: Optional[CommonCrawlClient] = None):

        self.cfg = cfg or get_config()

        self.db = db

        self.jobs = JobManager(db)

        self.cc = cc_client or CommonCrawlClient(cfg=self.cfg)

        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #

    # Public entry points

    # ------------------------------------------------------------------ #

    def start(self, params: Dict[str, Any], background: bool = True) -> int:

        """Create a job and start indexing. Returns the job id."""

        handle = self.jobs.create("index", params)

        if background:

            self._thread = threading.Thread(

                target=self._run, args=(handle,), daemon=True,

                name=f"indexer-{handle.job_id}")

            self._thread.start()

        else:

            self._run(handle)

        return handle.job_id

    def resume_job(self, job_id: int, background: bool = True) -> None:

        handle = self.jobs.handle(job_id)

        self.db.set_job_control(job_id, pause=False, cancel=False)

        if background:

            self._thread = threading.Thread(

                target=self._run, args=(handle,), daemon=True,

                name=f"indexer-{job_id}")

            self._thread.start()

        else:

            self._run(handle)

    def join(self, timeout: Optional[float] = None) -> None:

        if self._thread:

            self._thread.join(timeout)

    # ------------------------------------------------------------------ #

    # Core run loop

    # ------------------------------------------------------------------ #

    def _run(self, handle: JobHandle) -> None:

        params = (self.db.get_job(handle.job_id) or {}).get("params", {})

        try:

            check_disk_space(self.cfg.db_path, self.cfg.min_free_disk_bytes)

            handle.mark_running()

            dataset = params.get("dataset", DatasetType.WAT)

            source = params.get("source", "commoncrawl")

            if source == "file":

                self._index_files(handle, params)

            elif dataset == DatasetType.WAT:

                self._index_commoncrawl_wat(handle, params)

            elif dataset == DatasetType.WARC:

                self._index_commoncrawl_warc(handle, params)

            else:

                raise ImportError_(f"Unsupported dataset/source: {source}/{dataset}")

            if handle.is_cancelled():

                handle.mark_stopped()

            else:

                handle.mark_completed()

        except DiskSpaceError as exc:

            handle.mark_failed(f"Disk space: {exc}")

        except Exception as exc:  # keep the worker alive; record failure

            log.exception("Indexing job %d failed", handle.job_id)

            handle.record_error("run", str(exc))

            handle.mark_failed(str(exc))

    # ------------------------------------------------------------------ #

    # Cooperative pause / cancel

    # ------------------------------------------------------------------ #

    def _should_stop(self, handle: JobHandle) -> bool:

        if handle.is_cancelled():

            return True

        # Block while paused, polling flags.

        while handle.is_paused():

            if handle.status() != JobStatus.PAUSED:

                handle.mark_paused()

            time.sleep(0.5)

            if handle.is_cancelled():

                return True

        if handle.status() == JobStatus.PAUSED:

            handle.mark_running()

        return False

    # ------------------------------------------------------------------ #

    # Batch flushing

    # ------------------------------------------------------------------ #

    def _flush_batch(self, handle: JobHandle, batch: List[Backlink]) -> None:

        if not batch:

            return

        inserted, dupes = self.db.insert_backlinks(batch)

        handle.bump("backlinks_inserted", inserted)

        handle.bump("duplicates_skipped", dupes)

        handle.flush()

    # ------------------------------------------------------------------ #

    # Common Crawl WAT

    # ------------------------------------------------------------------ #

    def _index_commoncrawl_wat(self, handle: JobHandle, params: Dict[str, Any]) -> None:

        collection = params["collection"]

        max_files = params.get("max_files")

        max_records = params.get("max_records")

        handle.flush(stage="listing WAT paths")

        paths = self.cc.list_wat_paths(collection, max_files=max_files)

        handle.set_stat("files_discovered", len(paths))

        handle.flush()

        ckpt = handle.load_checkpoint("wat") or {}

        start_idx = ckpt.get("file_index", 0)

        records_done = ckpt.get("records_read", 0)

        batch: List[Backlink] = []

        for fi in range(start_idx, len(paths)):

            if self._should_stop(handle):

                break

            rel = paths[fi]

            handle.flush(stage="streaming WAT", current_file=rel)

            try:

                for page in self.cc.stream_wat_file(rel):

                    if self._should_stop(handle):

                        break

                    handle.bump("records_read")

                    handle.bump("pages_parsed")

                    for bl in backlinks_from_wat_page(

                            page, collection=collection, record_filename=rel):

                        handle.bump("links_extracted")

                        batch.append(bl)

                        if len(batch) >= self.cfg.batch_size:

                            self._flush_batch(handle, batch)

                            batch = []

                    records_done += 1

                    if records_done % self.cfg.checkpoint_every == 0:

                        self._flush_batch(handle, batch)

                        batch = []

                        handle.save_checkpoint("wat", {

                            "file_index": fi, "records_read": records_done})

                    if max_records and records_done >= max_records:

                        break

                handle.bump("files_downloaded")

            except Exception as exc:

                handle.record_error("wat_file", str(exc), detail=rel)

            handle.save_checkpoint("wat", {

                "file_index": fi + 1, "records_read": records_done})

            if max_records and records_done >= max_records:

                break

        self._flush_batch(handle, batch)

    # ------------------------------------------------------------------ #

    # Common Crawl WARC

    # ------------------------------------------------------------------ #

    def _index_commoncrawl_warc(self, handle: JobHandle, params: Dict[str, Any]) -> None:

        collection = params["collection"]

        url_pattern = params.get("url_pattern")

        max_records = params.get("max_records", 1000)

        if not url_pattern:

            raise ImportError_(

                "WARC indexing requires a 'url_pattern' to query the CDX index."

            )

        handle.flush(stage="querying CDX")

        batch: List[Backlink] = []

        records_done = 0

        for cdx in self.cc.query_cdx(collection, url_pattern,

                                     limit=max_records, match_type="domain"):

            if self._should_stop(handle):

                break

            if cdx.status != "200":

                continue

            handle.flush(stage="fetching WARC record", current_file=cdx.filename)

            try:

                for rec in self.cc.iter_warc_from_record(

                        cdx.filename, cdx.offset, cdx.length):

                    handle.bump("records_read")

                    handle.bump("pages_parsed")

                    handle.bump("bytes_downloaded", cdx.length)

                    for bl in backlinks_from_warc_record(

                            rec, collection=collection,

                            record_filename=cdx.filename):

                        bl.record_offset = cdx.offset

                        bl.record_length = cdx.length

                        handle.bump("links_extracted")

                        batch.append(bl)

                        if len(batch) >= self.cfg.batch_size:

                            self._flush_batch(handle, batch)

                            batch = []

            except Exception as exc:

                handle.record_error("warc_record", str(exc), detail=cdx.filename)

            records_done += 1

            if records_done % self.cfg.checkpoint_every == 0:

                handle.save_checkpoint("warc", {"records_done": records_done})

            if max_records and records_done >= max_records:

                break

        self._flush_batch(handle, batch)

    # ------------------------------------------------------------------ #

    # User files

    # ------------------------------------------------------------------ #

    def _index_files(self, handle: JobHandle, params: Dict[str, Any]) -> None:

        paths: List[str] = params.get("paths", [])

        collection = params.get("collection", "user-import")

        files: List[str] = []

        for p in paths:

            if os.path.isdir(p):

                for name in sorted(os.listdir(p)):

                    files.append(os.path.join(p, name))

            else:

                files.append(p)

        handle.set_stat("files_discovered", len(files))

        handle.flush()

        batch: List[Backlink] = []

        for fi, path in enumerate(files):

            if self._should_stop(handle):

                break

            handle.flush(stage="importing file", current_file=path)

            try:

                for bl in import_file(path, collection=collection):

                    handle.bump("links_extracted")

                    batch.append(bl)

                    if len(batch) >= self.cfg.batch_size:

                        self._flush_batch(handle, batch)

                        batch = []

                handle.bump("files_downloaded")

            except ImportError_ as exc:

                handle.record_error("import", str(exc), detail=path)

            except Exception as exc:

                handle.record_error("import_unexpected", str(exc), detail=path)

            handle.save_checkpoint("files", {"file_index": fi + 1})

        self._flush_batch(handle, batch)✅ Part complete — index_jobs.py and index_worker.py are whole.Say next for backlink_hunter.py (the CLI entry point with selftest, index build/status/pause/resume/stop, search, verify).
