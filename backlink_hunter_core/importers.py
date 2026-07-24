"""User-supplied dataset importers and record builders."""

from __future__ import annotations

import csv

import gzip

import hashlib

import json

import os

from typing import Iterator, Optional

from .htmlparse import classify_rel, parse_html_links, parse_title

from .logging_setup import get_logger

from .models import Backlink, DatasetType, LinkType, VerificationStatus, utcnow_iso

from .normalize import (

    extract_hostname,

    normalize_url,

    registrable_domain,

    resolve_url,

)
from .wat import iter_wat_file, WatPage

from .warc import iter_warc_file, WarcRecord

log = get_logger("importers")

class ImportError_(Exception):

    """Raised for unsupported or malformed imports."""

REQUIRED_CSV_COLUMNS = {"source_url", "target_url"}

def _evidence_hash(*parts: str) -> str:

    joined = "|".join(p or "" for p in parts)

    return hashlib.sha256(joined.encode("utf-8")).hexdigest()

def build_backlink(source_url: str, target_url: str, *,

                   anchor_text: str = "", image_alt: str = "",

                   rel_original: str = "", source_title: str = "",

                   collection: str = "", dataset_type: str = "",

                   record_filename: str = "", record_offset: Optional[int] = None,

                   record_length: Optional[int] = None,

                   source_http_status: Optional[int] = None,

                   content_type: str = "",

                   verification_status: str = VerificationStatus.ARCHIVED_ONLY

                   ) -> Optional[Backlink]:

    if not source_url or not target_url:

        return None

    n_source = normalize_url(source_url)

    n_target = normalize_url(target_url)

    src_host = extract_hostname(n_source)

    tgt_host = extract_hostname(n_target)

    if not src_host or not tgt_host:

        return None

    link_type = classify_rel(rel_original) if rel_original else LinkType.UNKNOWN

    now = utcnow_iso()

    return Backlink(

        normalized_target_domain=registrable_domain(tgt_host),

        normalized_target_hostname=tgt_host,

        normalized_target_url=n_target,

        normalized_source_url=n_source,

        source_url=source_url,

        source_domain=registrable_domain(src_host),

        source_hostname=src_host,

        source_title=source_title,

        target_url=target_url,

        target_hostname=tgt_host,

        anchor_text=anchor_text or "",

        image_alt=image_alt or "",

        rel_original=rel_original or "",

        link_type=link_type,

        source_http_status=source_http_status,

        content_type=content_type,

        verification_status=verification_status,

        live_backlink_present=None,

        first_discovered_at=now,

        last_seen_at=now,

        collection=collection,

        dataset_type=dataset_type,

        record_filename=record_filename,

        record_offset=record_offset,

        record_length=record_length,

        redirect_chain="",

        evidence_hash=_evidence_hash(n_source, n_target, collection,

                                     record_filename, str(record_offset)),

    )

def backlinks_from_wat_page(page: WatPage, *, collection: str = "",

                            record_filename: str = "",

                            dataset_type: str = DatasetType.WAT

                            ) -> Iterator[Backlink]:

    source_url = page.source_url

    if not source_url:

        return

    for wl in page.links:

        resolved = resolve_url(source_url, wl.url)

        if not resolved:

            continue

        anchor = wl.text or ""

        image_alt = wl.alt or ""

        bl = build_backlink(

            source_url=source_url,

            target_url=resolved,

            anchor_text=anchor if anchor else "",

            image_alt=image_alt,

            rel_original=wl.rel,

            source_title=page.title,

            collection=collection,

            dataset_type=dataset_type,

            record_filename=record_filename,

        )

        if bl:

            yield bl

def backlinks_from_warc_record(rec: WarcRecord, *, collection: str = "",

                               record_filename: str = "",

                               dataset_type: str = DatasetType.WARC

                               ) -> Iterator[Backlink]:

    if rec.record_type != "response" or not rec.target_uri:

        return

    ctype = rec.http_headers.get("content-type", rec.content_type)

    if "html" not in (ctype or "").lower():

        return

    html = rec.html

    if not html:

        return

    title = parse_title(html)

    for link in parse_html_links(html, rec.target_uri):

        bl = build_backlink(

            source_url=rec.target_uri,

            target_url=link.resolved_url,

            anchor_text=link.anchor_text,

            image_alt=link.image_alt,

            rel_original=link.rel_original,

            source_title=title,

            source_http_status=rec.http_status,

            content_type=ctype,

            collection=collection,

            dataset_type=dataset_type,

            record_filename=record_filename,

        )

        if bl:

            yield bl

def _open_maybe_gzip(path: str):

    if path.lower().endswith(".gz"):

        return gzip.open(path, "rt", encoding="utf-8", errors="replace")

    return open(path, "r", encoding="utf-8", errors="replace")

def import_csv(path: str, *, collection: str = "",

               dataset_type: str = DatasetType.CSV) -> Iterator[Backlink]:

    with _open_maybe_gzip(path) as fh:

        reader = csv.DictReader(fh)

        if reader.fieldnames is None:

            raise ImportError_("CSV has no header row")

        cols = {c.strip().lower() for c in reader.fieldnames}

        if not REQUIRED_CSV_COLUMNS.issubset(cols):

            missing = REQUIRED_CSV_COLUMNS - cols

            raise ImportError_(f"CSV missing required columns: {missing}")

        for row in reader:

            row = {(k or "").strip().lower(): (v or "").strip()

                   for k, v in row.items()}

            bl = build_backlink(

                source_url=row.get("source_url", ""),

                target_url=row.get("target_url", ""),

                anchor_text=row.get("anchor_text", ""),

                image_alt=row.get("image_alt", ""),

                rel_original=row.get("rel", row.get("rel_original", "")),

                source_title=row.get("source_title", ""),

                collection=row.get("collection", collection),

                dataset_type=dataset_type,

            )

            if bl:

                yield bl

def import_jsonl(path: str, *, collection: str = "",

                 dataset_type: str = DatasetType.JSONL) -> Iterator[Backlink]:

    with _open_maybe_gzip(path) as fh:

        for line in fh:

            line = line.strip()

            if not line:

                continue

            try:

                obj = json.loads(line)

            except json.JSONDecodeError:

                continue

            if not isinstance(obj, dict):

                continue

            bl = build_backlink(

                source_url=obj.get("source_url", ""),

                target_url=obj.get("target_url", ""),

                anchor_text=obj.get("anchor_text", ""),

                image_alt=obj.get("image_alt", ""),

                rel_original=obj.get("rel", obj.get("rel_original", "")),

                source_title=obj.get("source_title", ""),

                collection=obj.get("collection", collection),

                dataset_type=dataset_type,

            )

            if bl:

                yield bl

def import_json_array(path: str, *, collection: str = "",

                      dataset_type: str = DatasetType.JSONL) -> Iterator[Backlink]:

    with _open_maybe_gzip(path) as fh:

        try:

            data = json.load(fh)

        except json.JSONDecodeError as exc:

            raise ImportError_(f"Invalid JSON: {exc}")

    if not isinstance(data, list):

        raise ImportError_("JSON import expects an array of objects")

    for obj in data:

        if not isinstance(obj, dict):

            continue

        bl = build_backlink(

            source_url=obj.get("source_url", ""),

            target_url=obj.get("target_url", ""),

            anchor_text=obj.get("anchor_text", ""),

            image_alt=obj.get("image_alt", ""),

            rel_original=obj.get("rel", obj.get("rel_original", "")),

            source_title=obj.get("source_title", ""),

            collection=obj.get("collection", collection),

            dataset_type=dataset_type,

        )

        if bl:

            yield bl

def import_parquet(path: str, *, collection: str = "",

                   dataset_type: str = DatasetType.PARQUET) -> Iterator[Backlink]:

    try:

        import pyarrow.parquet as pq  # type: ignore

    except Exception:

        raise ImportError_(

            "Parquet import requires the optional dependency 'pyarrow'. "

            "Install with: pip install pyarrow"

        )

    pf = pq.ParquetFile(path)

    for batch in pf.iter_batches(batch_size=1000):

        table = batch.to_pydict()

        cols = {k.lower(): v for k, v in table.items()}

        if "source_url" not in cols or "target_url" not in cols:

            raise ImportError_("Parquet missing source_url/target_url columns")

        n = len(cols["source_url"])

        for i in range(n):

            def get(col: str) -> str:

                seq = cols.get(col)

                return str(seq[i]) if seq is not None and seq[i] is not None else ""

            bl = build_backlink(

                source_url=get("source_url"),

                target_url=get("target_url"),

                anchor_text=get("anchor_text"),

                image_alt=get("image_alt"),

                rel_original=get("rel") or get("rel_original"),

                source_title=get("source_title"),

                collection=get("collection") or collection,

                dataset_type=dataset_type,

            )

            if bl:

                yield bl

def import_warc(path: str, *, collection: str = "") -> Iterator[Backlink]:

    fname = os.path.basename(path)

    for rec in iter_warc_file(path, only_responses=True):

        yield from backlinks_from_warc_record(

            rec, collection=collection, record_filename=fname)

def import_wat(path: str, *, collection: str = "") -> Iterator[Backlink]:

    fname = os.path.basename(path)

    for page in iter_wat_file(path):

        yield from backlinks_from_wat_page(

            page, collection=collection, record_filename=fname)

def import_file(path: str, *, collection: str = "") -> Iterator[Backlink]:

    lower = path.lower()

    if lower.endswith((".warc", ".warc.gz")):

        yield from import_warc(path, collection=collection)

    elif lower.endswith((".wat", ".wat.gz")):

        yield from import_wat(path, collection=collection)

    elif lower.endswith((".csv", ".csv.gz")):

        yield from import_csv(path, collection=collection)

    elif lower.endswith((".jsonl", ".jsonl.gz", ".ndjson")):

        yield from import_jsonl(path, collection=collection)

    elif lower.endswith((".json", ".json.gz")):

        yield from import_json_array(path, collection=collection)

    elif lower.endswith(".parquet"):

        yield from import_parquet(path, collection=collection)

    else:

        raise ImportError_(f"Unsupported file format: {os.path.basename(path)}")
