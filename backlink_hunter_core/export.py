"""Streamed exporters for search results.

All exporters stream rows from the database (via SearchService.iter_all) and
write to a secure temporary file, so exports of hundreds of thousands of rows
never load everything into memory. No artificial row cap is imposed anywhere.
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Callable, Dict, Iterator, List, Optional

from .search import SearchFilters, SearchService
from .security import secure_tempfile
from .logging_setup import get_logger

log = get_logger("export")

EXPORT_COLUMNS = [
    "source_url", "source_domain", "source_title", "target_url",
    "target_hostname", "anchor_text", "image_alt", "link_type",
    "rel_original", "source_http_status", "verification_status",
    "live_backlink_present", "first_discovered_at", "last_seen_at",
    "last_checked_at", "collection", "dataset_type", "record_filename",
    "record_offset", "record_length", "redirect_chain", "evidence_hash",
]

HEADER_ALIASES = {"rel_original": "rel"}
ProgressCB = Optional[Callable[[int], None]]


def _rows(service: SearchService, filters: SearchFilters,
          rows_override: Optional[List[Dict[str, Any]]]) -> Iterator[Dict[str, Any]]:
    """Yield either explicitly-provided rows (selected/current page) or all matches."""
    if rows_override is not None:
        for row in rows_override:
            yield row
    else:
        yield from service.iter_all(filters)


def _header_row() -> List[str]:
    return [HEADER_ALIASES.get(column, column) for column in EXPORT_COLUMNS]


def _row_values(row: Dict[str, Any]) -> List[Any]:
    return [row.get(column, "") for column in EXPORT_COLUMNS]


def export_csv(service: SearchService, filters: SearchFilters,
               rows_override: Optional[List[Dict[str, Any]]] = None,
               delimiter: str = ",", progress: ProgressCB = None) -> str:
    suffix = ".tsv" if delimiter == "\t" else ".csv"
    path = secure_tempfile(suffix=suffix)
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(_header_row())
        for row in _rows(service, filters, rows_override):
            writer.writerow(_row_values(row))
            count += 1
            if progress and count % 1000 == 0:
                progress(count)
    if progress:
        progress(count)
    log.info("Exported %d rows to %s", count, path)
    return path


def export_tsv(service: SearchService, filters: SearchFilters,
               rows_override: Optional[List[Dict[str, Any]]] = None,
               progress: ProgressCB = None) -> str:
    return export_csv(service, filters, rows_override, delimiter="\t", progress=progress)


def export_json(service: SearchService, filters: SearchFilters,
                rows_override: Optional[List[Dict[str, Any]]] = None,
                progress: ProgressCB = None) -> str:
    """Stream a JSON array to disk without holding all rows in memory."""
    path = secure_tempfile(suffix=".json")
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("[")
        first = True
        for row in _rows(service, filters, rows_override):
            record = {column: row.get(column, "") for column in EXPORT_COLUMNS}
            if not first:
                fh.write(",")
            fh.write("\n")
            fh.write(json.dumps(record, ensure_ascii=False))
            first = False
            count += 1
            if progress and count % 1000 == 0:
                progress(count)
        fh.write("\n]" if not first else "]")
    if progress:
        progress(count)
    log.info("Exported %d rows to %s", count, path)
    return path


def export_txt_field(service: SearchService, filters: SearchFilters,
                     field: str, unique: bool = True,
                     rows_override: Optional[List[Dict[str, Any]]] = None,
                     progress: ProgressCB = None) -> str:
    """One value per line (e.g. source_url, target_url, source_domain)."""
    path = secure_tempfile(suffix=".txt")
    seen = set()
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in _rows(service, filters, rows_override):
            value = str(row.get(field, "") or "").strip()
            if not value:
                continue
            if unique:
                if value in seen:
                    continue
                seen.add(value)
            fh.write(value + "\n")
            count += 1
            if progress and count % 1000 == 0:
                progress(count)
    if progress:
        progress(count)
    return path


def export_source_urls(service, filters, rows_override=None, progress=None) -> str:
    return export_txt_field(service, filters, "source_url", True, rows_override, progress)


def export_target_urls(service, filters, rows_override=None, progress=None) -> str:
    return export_txt_field(service, filters, "target_url", True, rows_override, progress)


def export_referring_domains(service, filters, rows_override=None, progress=None) -> str:
    return export_txt_field(service, filters, "source_domain", True, rows_override, progress)


def export_source_target_pairs(service: SearchService, filters: SearchFilters,
                               rows_override: Optional[List[Dict[str, Any]]] = None,
                               progress: ProgressCB = None) -> str:
    """TSV of unique (source_url, target_url) pairs."""
    path = secure_tempfile(suffix=".txt")
    seen = set()
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in _rows(service, filters, rows_override):
            src = str(row.get("source_url", "") or "").strip()
            tgt = str(row.get("target_url", "") or "").strip()
            if not src or not tgt:
                continue
            key = (src, tgt)
            if key in seen:
                continue
            seen.add(key)
            fh.write(f"{src}\t{tgt}\n")
            count += 1
            if progress and count % 1000 == 0:
                progress(count)
    if progress:
        progress(count)
    return path


EXPORTERS: Dict[str, Callable] = {
    "csv": export_csv,
    "tsv": export_tsv,
    "json": export_json,
    "source_urls": export_source_urls,
    "target_urls": export_target_urls,
    "referring_domains": export_referring_domains,
    "source_target_pairs": export_source_target_pairs,
}


def export(format_name: str, service: SearchService, filters: SearchFilters,
           rows_override: Optional[List[Dict[str, Any]]] = None,
           progress: ProgressCB = None) -> str:
    fn = EXPORTERS.get(format_name)
    if not fn:
        raise ValueError(f"Unknown export format: {format_name!r}")
    return fn(service, filters, rows_override=rows_override, progress=progress)


def read_and_cleanup(path: str) -> bytes:
    """Read an exported temp file into bytes then delete it (for Streamlit download)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        return data
    finally:
        try:
            os.remove(path)
        except OSError:
            log.warning("Could not remove export temp file %s", path)
