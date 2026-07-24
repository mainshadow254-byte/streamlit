# Backlink Hunter

A local, **truthful**, domain-only reverse-backlink discovery and verification

tool. Enter a target domain (e.g. `amazon.com`), click **Search**, and get real

source pages that link to it — filtered, paginated, and exportable.

Backlink Hunter is the practical successor to the old "Backlink Shitter"

workflow, rebuilt around a real reverse-link index with strict data integrity.

---

## What it does

- **Automatic Backlink Discovery** — search the local reverse index using only a

  target domain. No candidate URL list and no seed sites are required.

- Builds a reverse-link index from **real** data:

  - Common Crawl **WAT** metadata (page + extracted links)

  - Common Crawl **WARC** archived HTML (byte-range fetched via CDX)

  - User-supplied datasets (CSV, JSONL/JSON, Parquet, WARC, WAT, gzip)

- **Live verification** of indexed backlinks (is the link still there
