"""Backlink Hunter — Streamlit interface.

Nine pages, selected from the sidebar:

  1. Backlink Search   (default; Automatic Backlink Discovery is the default mode)

  2. Index Manager

  3. Dataset Import

  4. URL Verification

  5. Seed Crawler

  6. Search History

  7. Errors

  8. Settings

  9. System Status

Automatic Backlink Discovery requires ONLY a target domain — no candidate URL

list and no seed sites. It queries the local reverse index. If the index is

empty it shows the exact required empty-index message.

Launch:  streamlit run streamlit_app.py

"""

from __future__ import annotations

import html

import os

import shutil

from typing import List

import streamlit as st

from backlink_hunter_core.config import Config, get_config, set_config

from backlink_hunter_core.db import Database

from backlink_hunter_core.export import EXPORTERS, export as run_export, read_and_cleanup

from backlink_hunter_core.index_jobs import JobManager

from backlink_hunter_core.index_worker import IndexWorker, check_disk_space

from backlink_hunter_core.importers import import_file, ImportError_

from backlink_hunter_core.logging_setup import setup_logging

from backlink_hunter_core.models import (

    DatasetType, LinkType, MatchMode, VerificationStatus,

)
from backlink_hunter_core.search import SearchFilters, SearchService, SORTABLE

from backlink_hunter_core.security import is_allowed_upload, secure_tempfile

from backlink_hunter_core.verification import Verifier

EMPTY_INDEX_MESSAGE = (

    "No backlink index is available yet. Open Index Manager and build or "

    "import a real backlink index first."

)

PAGES = [

    "Backlink Search",

    "Index Manager",

    "Dataset Import",

    "URL Verification",

    "Seed Crawler",

    "Search History",

    "Errors",

    "Settings",

    "System Status",

]

# --------------------------------------------------------------------------- #

# Shared resources

# --------------------------------------------------------------------------- #

@st.cache_resource

def get_db() -> Database:

    cfg = get_config()

    setup_logging(cfg.log_dir, cfg.log_level)

    return Database(cfg)

def human_bytes(n: int) -> str:

    step = 1024.0

    for unit in ["B", "KB", "MB", "GB", "TB"]:

        if n < step:

            return f"{n:.1f} {unit}"

        n /= step

    return f"{n:.1f} PB"

def _download_button(label: str, fmt: str, service: SearchService,

                     filters: SearchFilters, key: str) -> None:

    if st.button(label, key=key):

        with st.spinner(f"Generating {fmt} export ..."):

            tmp = run_export(fmt, service, filters)

            data = read_and_cleanup(tmp)

        ext = {"csv": "csv", "tsv": "tsv", "json": "json"}.get(fmt, "txt")

        st.download_button(

            f"Save {fmt}", data=data,

            file_name=f"backlinks_{filters.target or 'export'}.{ext}",

            key=f"dl_{key}")

# --------------------------------------------------------------------------- #

# Page: Backlink Search

# --------------------------------------------------------------------------- #

def page_backlink_search(db: Database) -> None:

    st.header("🔎 Backlink Search")

    mode_label = st.radio(

        "Search mode",

        ["Automatic Backlink Discovery", "Search Local Reverse Index"],

        horizontal=True, index=0,

        help="Automatic mode requires only a target domain. It queries the "

             "local reverse index — no candidate URLs or seed sites needed.",

    )

    service = SearchService(db)

    collections = service.available_collections()

    st.subheader("Target")

    target = st.text_input("Target domain or URL", placeholder="amazon.com")

    match_mode = st.selectbox(

        "Match mode",

        [MatchMode.ROOT_DOMAIN, MatchMode.EXACT_HOSTNAME,

         MatchMode.EXACT_URL, MatchMode.PATH_PREFIX],

        format_func=lambda m: {

            MatchMode.ROOT_DOMAIN: "Root domain + subdomains",

            MatchMode.EXACT_HOSTNAME: "Exact hostname",

            MatchMode.EXACT_URL: "Exact target URL",

            MatchMode.PATH_PREFIX: "Target path prefix",

        }[m],

    )

    with st.expander("Filters", expanded=False):

        c1, c2, c3 = st.columns(3)

        with c1:

            follow = st.checkbox("Follow", value=False)

            nofollow = st.checkbox("Nofollow", value=False)

            sponsored = st.checkbox("Sponsored", value=False)

            ugc = st.checkbox("UGC", value=False)

        with c2:

            live_only = st.checkbox("Live backlinks only", value=False)

            archived_only = st.checkbox("Archived only", value=False)

            no_blank = st.checkbox("Exclude blank anchors", value=False)

            unique_page = st.checkbox("Unique source pages", value=False)

            unique_dom = st.checkbox("Unique referring domains", value=False)

        with c3:

            collection = st.selectbox("Collection", ["(any)"] + collections)

            source_domain = st.text_input("Source domain filter", "")

            anchor = st.text_input("Anchor text contains", "")

            status_code = st.text_input("Source status code", "")

        vstatus = st.selectbox(

            "Verification status", ["(any)"] + sorted(VerificationStatus.ALL))

        d1, d2 = st.columns(2)

        with d1:

            first_from = st.text_input("First seen from (ISO date)", "")

        with d2:

            last_to = st.text_input("Last seen to (ISO date)", "")

    live_verify = st.checkbox(

        "Live-verify results on this page", value=False,

        help="Re-fetches the source pages shown on the current page to confirm "

             "the link is still present. Slower; respects robots.txt.")

    c4, c5 = st.columns(2)

    with c4:

        page_size = st.selectbox("Page size", [25, 50, 100, 250, 500], index=2)

    with c5:

        sort_by = st.selectbox("Sort by", sorted(SORTABLE),

                               index=sorted(SORTABLE).index("last_seen_at"))

    sort_desc = st.checkbox("Descending", value=True)

    if "search_page" not in st.session_state:

        st.session_state.search_page = 1

    search_clicked = st.button("Search", type="primary")

    # Empty-index guard — the exact required message.

    if search_clicked or st.session_state.get("did_search"):

        if db.is_empty():

            st.warning(EMPTY_INDEX_MESSAGE)

            return

    if search_clicked:

        st.session_state.did_search = True

        st.session_state.search_page = 1

    if not st.session_state.get("did_search"):

        st.info("Enter a target domain and click **Search**.")

        if collections:

            st.caption("Available index collections: " + ", ".join(collections))

        else:

            st.caption("No collections indexed yet.")

        return

    # Build filters

    link_types: List[str] = []

    if follow:

        link_types.append(LinkType.FOLLOW)

    if nofollow:

        link_types.append(LinkType.NOFOLLOW)

    if sponsored:

        link_types.append(LinkType.SPONSORED)

    if ugc:

        link_types.append(LinkType.UGC)

    filters = SearchFilters(

        target=target, mode=match_mode,

        verification_status=None if vstatus == "(any)" else vstatus,

        live_only=True if live_only else (False if archived_only else None),

        link_types=link_types,

        source_http_status=int(status_code) if status_code.strip().isdigit() else None,

        source_domain=source_domain.strip() or None,

        anchor_contains=anchor.strip() or None,

        collection=None if collection == "(any)" else collection,

        first_seen_from=first_from.strip() or None,

        last_seen_to=last_to.strip() or None,

        exclude_blank_anchor=no_blank,

        unique_source_page=unique_page,

        unique_source_domain=unique_dom,

        sort_by=sort_by, sort_desc=sort_desc,

    )

    total = service.count(filters)

    db.add_history(target, match_mode, total)

    if total == 0:

        st.info("No verified backlinks were found for this target with the "

                "current filters. (The index is not empty.)")

        return

    st.success(f"**{total:,}** matching backlinks.")

    total_pages = max(1, (total + page_size - 1) // page_size)

    pc1, pc2, pc3 = st.columns([1, 2, 1])

    with pc1:

        if st.button("◀ Prev") and st.session_state.search_page > 1:

            st.session_state.search_page -= 1

    with pc2:

        st.session_state.search_page = st.number_input(

            "Page", min_value=1, max_value=total_pages,

            value=min(st.session_state.search_page, total_pages), step=1)

    with pc3:

        if st.button("Next ▶") and st.session_state.search_page < total_pages:

            st.session_state.search_page += 1

    rows = service.page(filters, page=int(st.session_state.search_page),

                        page_size=page_size)

    # Optional live verification for the visible page only.

    if live_verify and rows:

        verifier = Verifier(db)

        prog = st.progress(0.0)

        for i, r in enumerate(rows):

            res = verifier.verify_and_store(

                r["id"], r["source_url"], target, mode=match_mode,

                had_archive=r.get("dataset_type") not in ("", DatasetType.LIVE))

            r["verification_status"] = res.status

            r["live_backlink_present"] = (

                None if res.live_present is None else int(res.live_present))

            r["source_http_status"] = res.http_status

            prog.progress((i + 1) / len(rows))

        prog.empty()

    # Results table

    display_cols = [

        "source_url", "source_domain", "target_url", "anchor_text",

        "link_type", "verification_status", "source_http_status",

        "collection", "last_seen_at",

    ]

    table = [{c: r.get(c, "") for c in display_cols} for r in rows]

    st.dataframe(table, use_container_width=True, hide_index=True)

    # Evidence viewer

    with st.expander("🔬 Evidence (provenance for a selected row)"):

        idx = st.number_input("Row on this page", min_value=1,

                              max_value=len(rows), value=1) - 1

        row = rows[int(idx)]

        st.json({

            "source_url": row.get("source_url"),

            "target_url": row.get("target_url"),

            "collection": row.get("collection"),

            "dataset_type": row.get("dataset_type"),

            "record_filename": row.get("record_filename"),

            "record_offset": row.get("record_offset"),

            "record_length": row.get("record_length"),

            "verification_status": row.get("verification_status"),

            "redirect_chain": row.get("redirect_chain"),

            "evidence_hash": row.get("evidence_hash"),

            "first_discovered_at": row.get("first_discovered_at"),

            "last_seen_at": row.get("last_seen_at"),

            "last_checked_at": row.get("last_checked_at"),

        })

        st.caption("Anchor text (escaped): " +

                   html.escape(str(row.get("anchor_text", ""))))

    # Exports (all filtered matches, streamed — no row cap)

    st.subheader("Export (all filtered matches)")

    e1, e2, e3, e4 = st.columns(4)

    with e1:

        _download_button("CSV", "csv", service, filters, "exp_csv")

        _download_button("TSV", "tsv", service, filters, "exp_tsv")

    with e2:

        _download_button("JSON", "json", service, filters, "exp_json")

        _download_button("Source URLs", "source_urls", service, filters, "exp_su")

    with e3:

        _download_button("Target URLs", "target_urls", service, filters, "exp_tu")

        _download_button("Referring domains", "referring_domains",

                         service, filters, "exp_rd")

    with e4:

        _download_button("Source-target pairs", "source_target_pairs",

                         service, filters, "exp_pairs")

# --------------------------------------------------------------------------- #

# Page: Index Manager

# --------------------------------------------------------------------------- #

def page_index_manager(db: Database) -> None:

    st.header("🗂️ Index Manager")

    stats = db.stats()

    jm = JobManager(db)

    c1, c2, c3 = st.columns(3)

    c1.metric("Total backlinks", f"{stats['total_backlinks']:,}")

    c2.metric("Unique source pages", f"{stats['unique_source_pages']:,}")

    c3.metric("Target domains", f"{stats['unique_target_domains']:,}")

    c4, c5, c6 = st.columns(3)

    c4.metric("Source domains", f"{stats['unique_source_domains']:,}")

    c5.metric("DB size", human_bytes(stats["db_size_bytes"]))

    c6.metric("Failed records", stats["failed_records"])

    st.caption(f"Database path: `{stats['db_path']}`  •  "

               f"exists: {stats['db_exists']}  •  "

               f"checkpoints: {stats['checkpoints']}")

    try:

        free = shutil.disk_usage(os.path.dirname(stats["db_path"]) or ".").free

        st.caption(f"Free disk space: {human_bytes(free)}")

    except OSError:

        pass

    st.subheader("Collections")

    if stats["collections"]:

        st.table(stats["collections"])

    else:

        st.info("No collections indexed yet.")

    st.subheader("Start indexing")

    src = st.selectbox("Source", ["commoncrawl", "file"])

    if src == "commoncrawl":

        dataset = st.selectbox("Dataset", [DatasetType.WAT, DatasetType.WARC])

        collection = st.text_input("Collection id", "CC-MAIN-2024-10")

        max_records = st.number_input("Max records", min_value=0, value=10000)

        url_pattern = ""

        if dataset == DatasetType.WARC:

            url_pattern = st.text_input("URL pattern (CDX query)", "example.com")

        if st.button("Start indexing", type="primary"):

            worker = IndexWorker(db)

            params = {

                "source": "commoncrawl", "dataset": dataset,

                "collection": collection,

                "max_records": int(max_records) or None,

                "url_pattern": url_pattern or None,

            }

            job_id = worker.start(params, background=True)

            st.success(f"Started background job #{job_id}. "

                       "Progress persists across browser refreshes.")

    else:

        st.caption("Use the Dataset Import page to upload files, or point to "

                   "server-side paths here.")

        paths_raw = st.text_area("Server-side file/dir paths (one per line)", "")

        collection = st.text_input("Collection label", "user-import")

        if st.button("Start file indexing", type="primary"):

            paths = [p.strip() for p in paths_raw.splitlines() if p.strip()]

            worker = IndexWorker(db)

            job_id = worker.start(

                {"source": "file", "paths": paths, "collection": collection},

                background=True)

            st.success(f"Started background job #{job_id}.")

    st.subheader("Active & recent jobs")

    jobs = db.list_jobs(limit=20)

    for j in jobs:

        with st.expander(f"#{j['id']} {j['job_type']} — {j['status']} "

                         f"(stage: {j.get('stage','')})"):

            st.json(j.get("stats", {}))

            if j.get("current_file"):

                st.caption(f"Current file: {j['current_file']}")

            if j.get("error"):

                st.error(j["error"])

            b1, b2, b3, b4 = st.columns(4)

            if b1.button("Pause", key=f"pause_{j['id']}"):

                jm.pause(j["id"]); st.rerun()

            if b2.button("Resume", key=f"resume_{j['id']}"):

                IndexWorker(db).resume_job(j["id"], background=True); st.rerun()

            if b3.button("Stop", key=f"stop_{j['id']}"):

                jm.stop(j["id"]); st.rerun()

    st.subheader("Maintenance")

    m1, m2, m3 = st.columns(3)

    with m1:

        del_coll = st.selectbox("Delete collection",

                                ["(select)"] + service_collections(db))

        if st.button("Delete selected collection"):

            if del_coll != "(select)":

                n = db.delete_collection(del_coll)

                st.success(f"Deleted {n} rows from {del_coll}")

    with m2:

        if st.button("Integrity check"):

            st.info(f"Integrity: {db.integrity_check()}")

    with m3:

        if st.button("Compact database (VACUUM)"):

            db.compact()

            st.success("Database compacted.")

def service_collections(db: Database) -> List[str]:

    return SearchService(db).available_collections()

# --------------------------------------------------------------------------- #

# Page: Dataset Import

# --------------------------------------------------------------------------- #

def page_dataset_import(db: Database) -> None:

    st.header("📥 Dataset Import")

    st.write("Import real reverse-link data from supported files. "

             "Supported: CSV, JSONL/JSON, Parquet (optional), WARC, WAT, and "

             "gzip-compressed variants.")

    st.caption("Required CSV columns: source_url, target_url. Optional: "

               "anchor_text, image_alt, rel, source_title, collection.")

    collection = st.text_input("Collection label for this import", "user-import")

    uploaded = st.file_uploader(

        "Upload dataset file",

        type=["csv", "jsonl", "json", "parquet", "warc", "wat", "gz"],

        accept_multiple_files=False)

    if uploaded is not None:

        if not is_allowed_upload(uploaded.name):

            st.error("File type not allowed.")

            return

        if st.button("Import file", type="primary"):

            tmp = secure_tempfile(suffix="_" + uploaded.name)

            with open(tmp, "wb") as fh:

                fh.write(uploaded.getbuffer())

            inserted = 0

            dupes = 0

            batch = []

            prog = st.progress(0.0)

            try:

                for i, bl in enumerate(import_file(tmp, collection=collection)):

                    batch.append(bl)

                    if len(batch) >= 500:

                        ins, dup = db.insert_backlinks(batch)

                        inserted += ins; dupes += dup; batch = []

                        prog.progress(min(1.0, (i % 5000) / 5000))

                if batch:

                    ins, dup = db.insert_backlinks(batch)

                    inserted += ins; dupes += dup

                st.success(f"Imported {inserted} backlinks "

                           f"({dupes} duplicates skipped).")

            except ImportError_ as exc:

                st.error(f"Import rejected: {exc}")

            except Exception as exc:

                st.error(f"Import failed: {exc}")

            finally:

                prog.empty()

                try:

                    os.remove(tmp)

                except OSError:

                    pass

# --------------------------------------------------------------------------- #

# Page: URL Verification

# --------------------------------------------------------------------------- #

def page_url_verification(db: Database) -> None:

    st.header("✅ URL Verification")

    st.write("Verify whether a supplied list of source pages currently links "

             "to a target. This does not require an index.")

    target = st.text_input("Target domain or URL", placeholder="amazon.com")

    mode = st.selectbox("Match mode", sorted(MatchMode.ALL), index=0)

    sources_raw = st.text_area("Source URLs (one per line)")

    uploaded = st.file_uploader("...or upload a .txt list", type=["txt"])

    if st.button("Verify", type="primary"):

        sources = [s.strip() for s in sources_raw.splitlines() if s.strip()]

        if uploaded is not None:

            content = uploaded.getvalue().decode("utf-8", errors="replace")

            sources += [s.strip() for s in content.splitlines() if s.strip()]

        if not target or not sources:

            st.warning("Provide a target and at least one source URL.")

            return

        verifier = Verifier(db)

        prog = st.progress(0.0)

        results = []

        for i, src in enumerate(sources):

            results.append(verifier.verify(src, target, mode, had_archive=False))

            prog.progress((i + 1) / len(sources))

        prog.empty()

        live = sum(1 for r in results if r.live_present)

        st.success(f"{live}/{len(results)} source pages currently link to {target}.")

        st.dataframe([{

            "source_url": r.source_url,

            "status": r.status,

            "http": r.http_status,

            "live_present": r.live_present,

            "detail": r.detail,

        } for r in results], use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- #

# Page: Seed Crawler

# --------------------------------------------------------------------------- #

def page_seed_crawler(db: Database) -> None:

    st.header("🕷️ Seed Crawler")

    st.write("Crawl a small set of seed pages, extract their outbound links, "

             "and add any that point to your target into the reverse index. "

             "This is the classic seed workflow — optional and separate from "

             "Automatic Backlink Discovery.")

    seeds_raw = st.text_area("Seed page URLs (one per line)")

    target = st.text_input("Only keep links to this target (optional)", "")

    collection = st.text_input("Collection label", "seed-crawl")

    max_pages = st.number_input("Max pages", min_value=1, value=25)

    if st.button("Crawl seeds", type="primary"):

        from backlink_hunter_core.htmlparse import parse_html_links, parse_title

        from backlink_hunter_core.importers import build_backlink

        from backlink_hunter_core.matching import TargetSpec, link_matches_target

        from backlink_hunter_core.net import SafeHTTPClient, FetchError

        seeds = [s.strip() for s in seeds_raw.splitlines() if s.strip()][:int(max_pages)]

        if not seeds:

            st.warning("Provide at least one seed URL.")

            return

        client = SafeHTTPClient()

        spec = TargetSpec.parse(target, MatchMode.ROOT_DOMAIN) if target else None

        inserted = 0

        batch = []

        prog = st.progress(0.0)

        for i, url in enumerate(seeds):

            try:

                res = client.fetch(url)

                title = parse_title(res.text)

                for link in parse_html_links(res.text, res.final_url):

                    if spec and not link_matches_target(link.resolved_url, spec):

                        continue

                    bl = build_backlink(

                        source_url=res.final_url, target_url=link.resolved_url,

                        anchor_text=link.anchor_text, image_alt=link.image_alt,

                        rel_original=link.rel_original, source_title=title,

                        source_http_status=res.status,

                        collection=collection, dataset_type=DatasetType.LIVE,

                        verification_status=VerificationStatus.LIVE_CONFIRMED,

                    )

                    if bl:

                        bl.live_backlink_present = 1

                        batch.append(bl)

            except (FetchError, Exception) as exc:

                db.record_error("seed_crawl", str(exc), detail=url)

            prog.progress((i + 1) / len(seeds))

        if batch:

            ins, _ = db.insert_backlinks(batch)

            inserted += ins

        prog.empty()

        st.success(f"Crawled {len(seeds)} seeds; inserted {inserted} backlinks.")

# --------------------------------------------------------------------------- #

# Page: Search History

# --------------------------------------------------------------------------- #

def page_search_history(db: Database) -> None:

    st.header("🕘 Search History")

    history = db.list_history(limit=200)

    if not history:

        st.info("No searches yet.")

        return

    st.dataframe([{

        "when": h["created_at"], "target": h["target"],

        "mode": h["mode"], "results": h["result_count"],

    } for h in history], use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- #

# Page: Errors

# --------------------------------------------------------------------------- #

def page_errors(db: Database) -> None:

    st.header("⚠️ Failed Requests & Errors")

    errors = db.list_errors(limit=300)

    if not errors:

        st.success("No errors recorded.")

        return

    if st.button("Clear errors"):

        db.clear_errors(); st.rerun()

    st.dataframe([{

        "when": e["created_at"], "context": e["context"],

        "message": e["message"], "detail": e["detail"],

    } for e in errors], use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- #

# Page: Settings

# --------------------------------------------------------------------------- #

def page_settings(db: Database) -> None:

    st.header("⚙️ Settings")

    cfg = get_config()

    st.caption("TLS verification is always enabled and cannot be disabled.")

    with st.form("settings"):

        db_path = st.text_input("Database path", cfg.db_path)

        timeout = st.number_input("Request timeout (s)", value=float(cfg.timeout))

        max_redirects = st.number_input("Max redirects", value=int(cfg.max_redirects))

        global_rate = st.number_input("Global rate (req/s)", value=float(cfg.global_rate))

        per_host_rate = st.number_input("Per-host rate (req/s)", value=float(cfg.per_host_rate))

        respect_robots = st.checkbox("Respect robots.txt", value=cfg.respect_robots)

        batch_size = st.number_input("Insert batch size", value=int(cfg.batch_size))

        submitted = st.form_submit_button("Save settings")

    if submitted:

        cfg.db_path = db_path

        cfg.timeout = float(timeout)

        cfg.max_redirects = int(max_redirects)

        cfg.global_rate = float(global_rate)

        cfg.per_host_rate = float(per_host_rate)

        cfg.respect_robots = bool(respect_robots)

        cfg.batch_size = int(batch_size)

        cfg.verify_tls = True

        set_config(cfg)

        st.success("Settings updated for this session. "

                   "Persist them in config.json for future runs.")

# --------------------------------------------------------------------------- #

# Page: System Status

# --------------------------------------------------------------------------- #

def page_system_status(db: Database) -> None:

    st.header("📊 System Status")

    cfg = get_config()

    stats = db.stats()

    st.subheader("Index")

    st.json({

        "db_path": stats["db_path"],

        "db_exists": stats["db_exists"],

        "db_size": human_bytes(stats["db_size_bytes"]),

        "total_backlinks": stats["total_backlinks"],

        "collections": [c["collection"] for c in stats["collections"]],

        "active_jobs": stats["active_jobs"],

    })

    st.subheader("Configuration")

    st.json({

        "db_backend": cfg.db_backend,

        "sqlite_wal": cfg.sqlite_wal,

        "verify_tls": cfg.verify_tls,

        "respect_robots": cfg.respect_robots,

        "global_rate": cfg.global_rate,

        "per_host_rate": cfg.per_host_rate,

        "max_response_bytes": cfg.max_response_bytes,

    })

    st.subheader("Dependencies")

    deps = {}

    for name in ["requests", "tldextract", "pyarrow", "streamlit"]:

        try:

            __import__(name)

            deps[name] = "installed"

        except Exception:

            deps[name] = "not installed"

    st.json(deps)

    st.caption("Backlink Hunter does not claim full-internet, Ahrefs-, Semrush- "

               "or Google-level coverage. Coverage equals the real data you "

               "import into the local reverse index.")

# --------------------------------------------------------------------------- #

# Main

# --------------------------------------------------------------------------- #

def main() -> None:

    st.set_page_config(page_title="Backlink Hunter", page_icon="🔗",

                       layout="wide")

    st.sidebar.title("🔗 Backlink Hunter")

    page = st.sidebar.radio("Navigation", PAGES, index=0)

    db = get_db()

    if page == "Backlink Search":

        page_backlink_search(db)

    elif page == "Index Manager":

        page_index_manager(db)

    elif page == "Dataset Import":

        page_dataset_import(db)

    elif page == "URL Verification":

        page_url_verification(db)

    elif page == "Seed Crawler":

        page_seed_crawler(db)

    elif page == "Search History":

        page_search_history(db)

    elif page == "Errors":

        page_errors(db)

    elif page == "Settings":

        page_settings(db)

    elif page == "System Status":

        page_system_status(db)

if __name__ == "__main__":

    main()✅ Part complete — streamlit_app.py is whole (all 9 pages, Automatic Backlink Discovery default, empty-index message wired in, streamed exports, evidence viewer, persisted jobs).Say next for the test suite + fixture builder (tests/build_fixtures.py and the offline pytest tests).
