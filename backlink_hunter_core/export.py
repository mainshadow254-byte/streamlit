"""Exporters. Emit ONLY real database rows; never inject example data."""
from __future__ import annotations
import csv
import io
import json
CSV_COLUMNS = [
    "source_url", "source_domain", "source_title", "target_url", "target_hostname",
    "anchor_text", "image_alt", "link_type", "rel", "source_http_status",
    "verification_status", "live_backlink_present", "first_discovered_at",
    "last_checked_at", "common_crawl_collection", "warc_filename",
    "warc_offset", "warc_length", "redirect_chain",
]
def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
    return buf.getvalue()
def to_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2, ensure_ascii=False)
def to_txt(rows: list[dict], kind: str = "source_urls") -> str:
    if kind == "source_urls":
        return "\n".join(sorted({r["source_url"] for r in rows}))
    if kind == "target_urls":
        return "\n".join(sorted({r["target_url"] for r in rows}))
    if kind == "source_domains":
        return "\n".join(sorted({r["source_domain"] for r in rows if r.get("source_domain")}))
    if kind == "pairs":
        return "\n".join(f"{r['source_url']}\t{r['target_url']}" for r in rows)
    if kind == "full":
        header = "\t".join(CSV_COLUMNS)
        body = "\n".join(
            "\t".join(str(r.get(c, "")) for c in CSV_COLUMNS) for r in rows
        )
        return header + "\n" + body
    raise ValueError(f"Unknown txt kind: {kind}")
