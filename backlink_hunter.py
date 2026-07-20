"""Backlink Hunter — entry point.
UI:        streamlit run backlink_hunter.py
Selftest:  python backlink_hunter.py --selftest
Index:     python backlink_hunter.py --index --collection CC-MAIN-2024-33 --seed example.org
Query:     python backlink_hunter.py --query example.com --index-db linkindex.db
"""
from __future__ import annotations
import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from backlink_hunter_core.config import Settings
from backlink_hunter_core.db import Database
from backlink_hunter_core.export import to_csv, to_json, to_txt
from backlink_hunter_core.htmlparse import extract_links
from backlink_hunter_core.hunter import Engine
from backlink_hunter_core.matching import MatchMode, matches_target
from backlink_hunter_core.models import utcnow_iso
from backlink_hunter_core.normalize import normalize_domain_input, registrable_domain
NO_RESULTS_MSG = "No verified backlinks were found from the selected data sources."
def build_match(raw_target: str, mode: MatchMode) -> tuple[str, dict]:
    norm = normalize_domain_input(raw_target)
    full = raw_target if "://" in raw_target else "http://" + raw_target
    parts = urlsplit(full)
    host = parts.hostname or norm
    return norm, {
        "target_host": host,
        "target_root": norm,
        "target_url": full,
        "target_path_prefix": parts.path or "/",
    }
# --------------------------------------------------------------------------- #
# CLI: local fixture self-test (no network, no fabricated data)
# --------------------------------------------------------------------------- #
def selftest() -> int:
    fixture = Path("tests/fixtures/sample.html")
    if not fixture.exists():
        print("Missing tests/fixtures/sample.html — run: python tests/build_fixtures.py")
        return 1
    html = fixture.read_text(encoding="utf-8")
    target, mk = build_match("example.com", MatchMode.ROOT_AND_SUBDOMAINS)
    title, links = extract_links(html, "https://blog.test/post")
    hits = [
        l for l in links
        if matches_target(l.resolved, mode=MatchMode.ROOT_AND_SUBDOMAINS, **mk)
    ]
    print(f"Parsed title={title!r}, links={len(links)}, backlinks to {target}={len(hits)}")
    if not hits:
        print(NO_RESULTS_MSG)
        return 1
    for h in hits:
        print(f"  -> {h.resolved}  [{h.link_type}]  anchor={h.anchor_text!r}")
    print("SELFTEST OK: real backlink detected from fixture (no fabricated data).")
    return 0
def cli_index(args: argparse.Namespace) -> int:
    from backlink_hunter_core.linkindex import (
        LinkIndex, build_index_sync, estimate_storage_bytes,
    )
    settings = Settings.load()
    idx = LinkIndex(args.index_db)
    est = estimate_storage_bytes(args.max)
    print(f"Estimated storage for ~{args.max} pages: ~{est / 1_048_576:.1f} MiB")
    print("WARNING: indexing large web datasets can require substantial storage, "
          "bandwidth and time.")
    stats = build_index_sync(
        settings, idx, args.collection, [args.seed], max_records=args.max
    )
    print(f"Done. queried={stats.records_queried} downloaded={stats.records_downloaded} "
          f"pages={stats.pages_parsed} links_indexed={stats.links_indexed} "
          f"skipped={stats.skipped_checkpointed} failed={stats.failed}")
    return 0
def cli_query(args: argparse.Namespace) -> int:
    from backlink_hunter_core.linkindex import LinkIndex
    idx = LinkIndex(args.index_db)
    rows = idx.query_backlinks(args.query)
    if not rows:
        print(NO_RESULTS_MSG)
        return 0
    print(f"{len(rows)} indexed backlinks to {registrable_domain(args.query)}:")
    for r in rows[:200]:
        print(f"  {r['source_url']}  ->  {r['target_url']}  [{r['link_type']}]")
    return 0
# --------------------------------------------------------------------------- #
# Streamlit UI with threaded engine (real stop/pause/resume)
# --------------------------------------------------------------------------- #
def _start_thread(engine: Engine, coro_factory) -> threading.Thread:
    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro_factory())
        except Exception as exc:  # noqa: BLE001 - surface into log, keep UI alive
            from backlink_hunter_core.logging_setup import get_logger
            get_logger().exception("engine crashed: %s", exc)
        finally:
            loop.close()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
def run_ui() -> None:
    import pandas as pd
    import streamlit as st
    st.set_page_config(page_title="Backlink Hunter", layout="wide")
    settings = Settings.load()
    db = Database(settings.database_path)
    ss = st.session_state
    st.title("🔗 Backlink Hunter")
    st.caption(
        "Only verified backlinks from real downloaded pages / WARC records are shown. "
        "No fabricated data, no fake authority scores."
    )
    with st.sidebar:
        st.header("Search settings")
        raw_target = st.text_input("Target domain / URL", "example.com")
        mode_val = st.selectbox(
            "Match mode", [m.value for m in MatchMode], index=1
        )
        source_mode = st.selectbox(
            "Data source",
            ["URL list", "Common Crawl (seed domains)", "Direct site crawl (seeds)"],
        )
        max_records = int(st.number_input("Maximum records / pages", 10, 200_000, 500))
        concurrency = int(
            st.number_input("Concurrency", 1, 200, settings.default_concurrency)
        )
        timeout = int(
            st.number_input("Timeout (s)", 1, 120, int(settings.request_timeout_seconds))
        )
        live_verify = st.toggle("Live verification (CC mode)", value=True)
        st.checkbox("Include subdomains (use root_and_subdomains mode)", value=True,
                    disabled=True,
                    help="Choose the 'root_and_subdomains' match mode above.")
        collection = st.text_input("Common Crawl collection", "CC-MAIN-2024-33")
    if not raw_target.strip():
        st.warning("Enter a target domain.")
        st.stop()
    mode = MatchMode(mode_val)
    target, mk = build_match(raw_target, mode)
    st.info(f"Normalized target (registrable domain): **{target}**  ·  match mode: `{mode.value}`")
    if source_mode == "URL list":
        urls_text = st.text_area("Candidate source URLs (one per line)", height=140)
        uploaded = st.file_uploader("...or upload a .txt/.csv of URLs", type=["txt", "csv"])
    elif source_mode == "Common Crawl (seed domains)":
        seeds_text = st.text_area(
            "Seed domains to scan in Common Crawl (one per line)",
            "blog.example.org", height=100,
        )
        uploaded = None
    else:
        seeds_text = st.text_area(
            "Seed sites to crawl live (robots.txt respected)",
            "https://blog.example.org/", height=100,
        )
        uploaded = None
    c1, c2, c3, c4, c5 = st.columns(5)
    start = c1.button("▶ Search", type="primary")
    stop = c2.button("■ Stop")
    pause = c3.button("⏸ Pause")
    resume = c4.button("⏵ Resume")
    clear = c5.button("🗑 Clear results")
    if clear:
        ss.pop("search_id", None)
        ss.pop("engine", None)
        ss.pop("thread", None)
    # ---- react to control buttons ----
    engine: Engine | None = ss.get("engine")
    if engine is not None:
        if stop:
            engine.stop()
        if pause:
            engine.pause()
        if resume:
            engine.resume()
    # ---- start a new run ----
    if start:
        settings.default_concurrency = concurrency
        settings.request_timeout_seconds = float(timeout)
        engine = Engine(settings)
        search_id = db.create_search(target, f"{source_mode}:{mode.value}", utcnow_iso())
        ss["engine"] = engine
        ss["search_id"] = search_id
        def on_found(bl) -> None:
            db.insert_backlink(search_id, bl)
        if source_mode == "URL list":
            urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
            if uploaded is not None:
                content = uploaded.read().decode("utf-8", "replace")
                urls += [
                    c.strip()
                    for c in content.replace(",", "\n").splitlines()
                    if c.strip().lower().startswith("http")
                ]
            def factory():
                return engine.run_url_list(
                    urls, mode=mode, match_kwargs=mk,
                    target_host=mk["target_host"], on_found=on_found,
                )
        elif source_mode == "Common Crawl (seed domains)":
            seeds = [s.strip() for s in seeds_text.splitlines() if s.strip()]
            def factory():
                return engine.run_common_crawl(
                    seeds, collection, mode=mode, match_kwargs=mk,
                    target_host=mk["target_host"], max_records=max_records,
                    on_found=on_found, live_verify=live_verify,
                )
        else:
            seeds = [s.strip() for s in seeds_text.splitlines() if s.strip()]
            def factory():
                return engine.run_seed_crawl(
                    seeds, mode=mode, match_kwargs=mk,
                    target_host=mk["target_host"], max_pages=max_records,
                    on_found=on_found,
                )
        ss["thread"] = _start_thread(engine, factory)
    # ---- live status / counters ----
    engine = ss.get("engine")
    search_id = ss.get("search_id")
    thread: threading.Thread | None = ss.get("thread")
    if engine is not None:
        s = engine.stats
        state = "PAUSED" if engine.paused else (
            "RUNNING" if thread and thread.is_alive() else "DONE"
        )
        st.subheader(f"Status: {state}")
        cols = st.columns(7)
        cols[0].metric("Records queried", s.records_queried)
        cols[1].metric("Downloaded", s.records_downloaded)
        cols[2].metric("Pages parsed", s.pages_parsed)
        cols[3].metric("Backlinks", s.backlinks_discovered)
        cols[4].metric("Verified", s.backlinks_verified)
        cols[5].metric("Duplicates removed", s.normalized_duplicates + s.exact_duplicates)
        cols[6].metric("Failed requests", s.failed_requests)
    # ---- results ----
    rows: list[dict] = db.fetch_backlinks(search_id) if search_id else []
    st.subheader("Results")
    if not rows:
        st.warning(NO_RESULTS_MSG)
    else:
        # UI-side filters
        fcol1, fcol2, fcol3 = st.columns(3)
        vstatus = fcol1.multiselect(
            "Verification status",
            sorted({r["verification_status"] for r in rows}),
        )
        ltype = fcol2.multiselect(
            "Link type", sorted({r["link_type"] for r in rows})
        )
        hide_blank = fcol3.checkbox("Exclude blank anchors", value=False)
        view = rows
        if vstatus:
            view = [r for r in view if r["verification_status"] in vstatus]
        if ltype:
            view = [r for r in view if r["link_type"] in ltype]
        if hide_blank:
            view = [r for r in view if (r.get("anchor_text") or "").strip()]
        st.dataframe(pd.DataFrame(view), use_container_width=True)
        st.subheader("Local statistics (factual — NOT authority scores)")
        st.write({
            "unique_referring_pages": len({r["source_url"] for r in view}),
            "unique_referring_domains": len({r["source_domain"] for r in view}),
            "follow_links": sum(1 for r in view if r["link_type"] == "FOLLOW"),
            "nofollow_links": sum(1 for r in view if r["link_type"] == "NOFOLLOW"),
            "sponsored": sum(1 for r in view if r["link_type"] == "SPONSORED"),
            "ugc": sum(1 for r in view if r["link_type"] == "UGC"),
            "live_confirmed": sum(
                1 for r in view if r["verification_status"] == "LIVE_CONFIRMED"
            ),
            "archived_confirmed": sum(
                1 for r in view if r["verification_status"] == "ARCHIVED_CONFIRMED"
            ),
            "archived_only": sum(
                1 for r in view if r["verification_status"] == "ARCHIVED_ONLY"
            ),
        })
        e1, e2, e3, e4 = st.columns(4)
        e1.download_button("Export CSV", to_csv(view), "backlinks.csv", "text/csv")
        e2.download_button(
            "Export JSON", to_json(view), "backlinks.json", "application/json"
        )
        e3.download_button(
            "TXT: source URLs", to_txt(view, "source_urls"),
            "source_urls.txt", "text/plain",
        )
        e4.download_button(
            "TXT: pairs", to_txt(view, "pairs"), "pairs.txt", "text/plain"
        )
    # ---- search history + error log ----
    with st.expander("Search history"):
        st.dataframe(pd.DataFrame(db.list_searches()), use_container_width=True)
    with st.expander("Failed-request / error log"):
        st.dataframe(pd.DataFrame(db.fetch_errors(search_id)), use_container_width=True)
    # ---- auto-refresh while running (keeps counters live, stays responsive) ----
    if thread is not None and thread.is_alive():
        time.sleep(0.8)
        st.rerun()
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Backlink Hunter")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("--collection", type=str, default="CC-MAIN-2024-33")
    parser.add_argument("--seed", type=str, default="")
    parser.add_argument("--max", type=int, default=1000)
    parser.add_argument("--index-db", type=str, default="linkindex.db")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.index:
        if not args.seed:
            print("--index requires --seed DOMAIN")
            return 2
        return cli_index(args)
    if args.query:
        return cli_query(args)
    print("Run the UI with:  streamlit run backlink_hunter.py")
    print("Other modes:  --selftest | --index --seed DOMAIN | --query DOMAIN")
    return 0
def _is_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


if _is_streamlit():
    run_ui()
elif __name__ == "__main__":
    raise SystemExit(main())
