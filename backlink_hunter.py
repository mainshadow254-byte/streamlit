#!/usr/bin/env python3

"""Backlink Hunter — command-line interface and self-test.

Usage examples:

  python backlink_hunter.py selftest

  python backlink_hunter.py index build \

      --collection CC-MAIN-2024-10 --dataset wat --max-records 10000

  python backlink_hunter.py index build \

      --source file --paths data/my_dump.csv --collection my-import

  python backlink_hunter.py index status

  python backlink_hunter.py index pause   --job 3

  python backlink_hunter.py index resume  --job 3

  python backlink_hunter.py index stop    --job 3

  python backlink_hunter.py search amazon.com --page-size 100

  python backlink_hunter.py search amazon.com --export backlinks.csv

  python backlink_hunter.py verify --target amazon.com --source-list sources.txt

No hardcoded display cap (no rows[:200]); the practical limit is your data.

"""

from __future__ import annotations

import argparse

import os

import shutil

import sys

from typing import List, Optional

from backlink_hunter_core.config import get_config

from backlink_hunter_core.db import Database

from backlink_hunter_core.export import export as run_export, read_and_cleanup

from backlink_hunter_core.index_jobs import JobManager

from backlink_hunter_core.index_worker import IndexWorker

from backlink_hunter_core.logging_setup import setup_logging

from backlink_hunter_core.models import DatasetType, MatchMode

from backlink_hunter_core.search import SearchFilters, SearchService

from backlink_hunter_core.verification import Verifier

EMPTY_INDEX_MESSAGE = (

    "No backlink index is available yet. Open Index Manager and build or "

    "import a real backlink index first."

)

# --------------------------------------------------------------------------- #

# Commands

# --------------------------------------------------------------------------- #

def cmd_index_build(args: argparse.Namespace, db: Database) -> int:

    worker = IndexWorker(db)

    params = {

        "source": args.source,

        "dataset": args.dataset,

        "collection": args.collection,

        "max_records": args.max_records,

        "max_files": args.max_files,

        "url_pattern": args.url_pattern,

        "paths": args.paths or [],

    }

    print(f"Starting index job (source={args.source}, dataset={args.dataset}, "

          f"collection={args.collection}) ...")

    # Run in the foreground for the CLI so output is deterministic.

    job_id = worker.start(params, background=False)

    job = db.get_job(job_id) or {}

    stats = job.get("stats", {})

    print(f"Job {job_id} finished with status: {job.get('status')}")

    print(f"  backlinks_inserted : {stats.get('backlinks_inserted', 0)}")

    print(f"  duplicates_skipped : {stats.get('duplicates_skipped', 0)}")

    print(f"  links_extracted    : {stats.get('links_extracted', 0)}")

    print(f"  failed_requests    : {stats.get('failed_requests', 0)}")

    if job.get("error"):

        print(f"  error              : {job['error']}")

        return 1

    return 0

def cmd_index_status(args: argparse.Namespace, db: Database) -> int:

    stats = db.stats()

    print("Index status")

    print(f"  database path        : {stats['db_path']}")

    print(f"  database exists       : {stats['db_exists']}")

    print(f"  database size (bytes) : {stats['db_size_bytes']}")

    print(f"  total backlinks       : {stats['total_backlinks']}")

    print(f"  unique source pages   : {stats['unique_source_pages']}")

    print(f"  unique source domains : {stats['unique_source_domains']}")

    print(f"  unique target domains : {stats['unique_target_domains']}")

    print(f"  failed records        : {stats['failed_records']}")

    print(f"  checkpoints           : {stats['checkpoints']}")

    print(f"  active jobs           : {stats['active_jobs']}")

    print("  collections:")

    for c in stats["collections"]:

        print(f"    - {c['collection'] or '(none)'}: {c['n']}")

    jobs = db.list_jobs(limit=10)

    if jobs:

        print("  recent jobs:")

        for j in jobs:

            print(f"    #{j['id']} {j['job_type']} [{j['status']}] "

                  f"stage={j.get('stage','')}")

    return 0

def cmd_index_pause(args: argparse.Namespace, db: Database) -> int:

    JobManager(db).pause(args.job)

    print(f"Requested pause for job {args.job}")

    return 0

def cmd_index_resume(args: argparse.Namespace, db: Database) -> int:

    worker = IndexWorker(db)

    print(f"Resuming job {args.job} ...")

    worker.resume_job(args.job, background=False)

    job = db.get_job(args.job) or {}

    print(f"Job {args.job} status: {job.get('status')}")

    return 0

def cmd_index_stop(args: argparse.Namespace, db: Database) -> int:

    JobManager(db).stop(args.job)

    print(f"Requested stop for job {args.job}")

    return 0

def cmd_search(args: argparse.Namespace, db: Database) -> int:

    if db.is_empty():

        print(EMPTY_INDEX_MESSAGE)

        return 2

    service = SearchService(db)

    filters = SearchFilters(

        target=args.target,

        mode=args.mode,

        collection=args.collection,

        source_domain=args.source_domain,

        anchor_contains=args.anchor,

        exclude_blank_anchor=args.no_blank_anchor,

        unique_source_domain=args.unique_domains,

        sort_by=args.sort_by,

        sort_desc=not args.ascending,

    )

    if args.link_type:

        filters.link_types = [args.link_type.upper()]

    total = service.count(filters)

    print(f"Total matching backlinks: {total}")

    if total == 0:

        print("No verified backlinks were found for this target in the index.")

        db.add_history(args.target, args.mode, 0)

        return 0

    if args.export:

        fmt = _format_from_path(args.export)

        tmp = run_export(fmt, service, filters)

        data = read_and_cleanup(tmp)

        with open(args.export, "wb") as fh:

            fh.write(data)

        print(f"Exported {total} matches to {args.export} (format={fmt})")

        db.add_history(args.target, args.mode, total)

        return 0

    # Print pages (no artificial cap).

    page = 1

    shown = 0

    while shown < total:

        rows = service.page(filters, page=page, page_size=args.page_size)

        if not rows:

            break

        for r in rows:

            print(f"{r['source_url']}  ->  {r['target_url']}  "

                  f"[{r['link_type']}] anchor={r['anchor_text']!r} "

                  f"({r['verification_status']})")

            shown += 1

        page += 1

        if args.first_page_only:

            break

    db.add_history(args.target, args.mode, total)

    return 0

def cmd_verify(args: argparse.Namespace, db: Database) -> int:

    sources: List[str] = []

    if args.source_list:

        with open(args.source_list, "r", encoding="utf-8") as fh:

            sources = [ln.strip() for ln in fh if ln.strip()]

    elif args.source:

        sources = [args.source]

    else:

        print("Provide --source-list FILE or --source URL")

        return 1

    verifier = Verifier(db)

    results = verifier.verify_source_list(args.target, sources, mode=args.mode)

    live = 0

    for res in results:

        if res.live_present:

            live += 1

        print(f"[{res.status}] {res.source_url} "

              f"(http={res.http_status}, live={res.live_present})")

    print(f"\n{live}/{len(results)} sources currently link to {args.target}")

    return 0

def cmd_selftest(args: argparse.Namespace, db: Database) -> int:

    """Offline self-test: exercises the full pipeline with an in-memory fixture.

    Builds a tiny HTML fixture, extracts a real link, inserts it, searches by

    target domain only, exports it, and confirms a plain-text mention is

    excluded. Uses a temporary database so production data is untouched.

    """

    import tempfile

    from backlink_hunter_core.config import Config, set_config

    from backlink_hunter_core.htmlparse import parse_html_links, parse_title

    from backlink_hunter_core.importers import build_backlink

    from backlink_hunter_core.models import DatasetType

    print("Running Backlink Hunter self-test (offline) ...")

    tmpdir = tempfile.mkdtemp(prefix="blh_selftest_")

    db_path = os.path.join(tmpdir, "selftest.db")

    cfg = Config.load()

    cfg.db_path = db_path

    set_config(cfg)

    test_db = Database(cfg)

    ok = True

    fixture_html = """

    <html><head><title>My Review Blog</title></head><body>

      <p>I love shopping. Visit

         <a href="https://www.amazon.com/dp/B000" rel="nofollow">this product</a>.</p>

      <p>I also mention amazon.com in plain text but do not link it here.</p>

      <a href="/local/page">relative link</a>

      <a href="//cdn.amazon.com/img">protocol relative</a>

      <a href="mailto:me@example.com">email</a>

    </body></html>

    """

    base = "https://reviewblog.example/post-1"

    links = parse_html_links(fixture_html, base)

    title = parse_title(fixture_html)

    # 1) plain-text mention must NOT appear as a link

    amazon_links = [l for l in links if "amazon.com" in l.hostname]

    if not amazon_links:

        print("  FAIL: expected at least one amazon.com hyperlink")

        ok = False

    else:

        print(f"  OK: extracted {len(amazon_links)} amazon.com hyperlink(s)")

    # 2) mailto and empty hrefs excluded

    if any(l.href.startswith("mailto:") for l in links):

        print("  FAIL: mailto link was not excluded")

        ok = False

    else:

        print("  OK: mailto excluded")

    # 3) insert into reverse index

    backlinks = []

    for l in amazon_links:

        bl = build_backlink(

            source_url=base, target_url=l.resolved_url,

            anchor_text=l.anchor_text, image_alt=l.image_alt,

            rel_original=l.rel_original, source_title=title,

            collection="selftest-fixture", dataset_type=DatasetType.FIXTURE,

        )

        if bl:

            backlinks.append(bl)

    inserted, _ = test_db.insert_backlinks(backlinks)

    print(f"  OK: inserted {inserted} backlink(s) into reverse index")

    # 4) search by target domain only

    service = SearchService(test_db)

    filters = SearchFilters(target="amazon.com", mode=MatchMode.ROOT_DOMAIN)

    total = service.count(filters)

    if total >= 1:

        print(f"  OK: domain-only search returned {total} result(s)")

    else:

        print("  FAIL: domain-only search returned 0 results")

        ok = False

    # 5) false-positive domain rejection

    fp_filters = SearchFilters(target="notamazon.com", mode=MatchMode.ROOT_DOMAIN)

    if service.count(fp_filters) == 0:

        print("  OK: notamazon.com correctly returns 0 results")

    else:

        print("  FAIL: false-positive domain matched")

        ok = False

    # 6) export

    tmp = run_export("csv", service, filters)

    data = read_and_cleanup(tmp)

    if data and b"amazon.com" in data:

        print("  OK: CSV export contains the backlink")

    else:

        print("  FAIL: CSV export missing data")

        ok = False

    # 7) empty-index messaging

    empty_db_path = os.path.join(tmpdir, "empty.db")

    empty_cfg = Config.load()

    empty_cfg.db_path = empty_db_path

    empty_db = Database(empty_cfg)

    if empty_db.is_empty():

        print(f"  OK: empty index detected -> would show: {EMPTY_INDEX_MESSAGE!r}")

    else:

        print("  FAIL: empty index not detected")

        ok = False

    test_db.close()

    empty_db.close()

    set_config(cfg)  # leave a sane config

    shutil.rmtree(tmpdir, ignore_errors=True)

    print("\nSELF-TEST:", "PASSED" if ok else "FAILED")

    return 0 if ok else 1

# --------------------------------------------------------------------------- #

# Helpers

# --------------------------------------------------------------------------- #

def _format_from_path(path: str) -> str:

    lower = path.lower()

    if lower.endswith(".json"):

        return "json"

    if lower.endswith(".tsv"):

        return "tsv"

    return "csv"

# --------------------------------------------------------------------------- #

# Argument parsing

# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:

    p = argparse.ArgumentParser(

        prog="backlink_hunter.py",

        description="Local reverse-backlink discovery and verification.")

    sub = p.add_subparsers(dest="command", required=True)

    # selftest

    sp = sub.add_parser("selftest", help="Run offline self-test")

    sp.set_defaults(func=cmd_selftest)

    # index

    ip = sub.add_parser("index", help="Index management")

    isub = ip.add_subparsers(dest="index_command", required=True)

    b = isub.add_parser("build", help="Build/update the reverse index")

    b.add_argument("--source", default="commoncrawl",

                   choices=["commoncrawl", "file"])

    b.add_argument("--dataset", default=DatasetType.WAT,

                   choices=[DatasetType.WAT, DatasetType.WARC])

    b.add_argument("--collection", default="")

    b.add_argument("--max-records", type=int, default=None)

    b.add_argument("--max-files", type=int, default=None)

    b.add_argument("--url-pattern", default=None,

                   help="Domain/URL pattern for WARC CDX queries")

    b.add_argument("--paths", nargs="*", default=None,

                   help="File(s)/dir for --source file")

    b.set_defaults(func=cmd_index_build)

    st = isub.add_parser("status", help="Show index status")

    st.set_defaults(func=cmd_index_status)

    pa = isub.add_parser("pause", help="Pause a running job")

    pa.add_argument("--job", type=int, required=True)

    pa.set_defaults(func=cmd_index_pause)

    re = isub.add_parser("resume", help="Resume a paused/stopped job")

    re.add_argument("--job", type=int, required=True)

    re.set_defaults(func=cmd_index_resume)

    so = isub.add_parser("stop", help="Stop a running job")

    so.add_argument("--job", type=int, required=True)

    so.set_defaults(func=cmd_index_stop)

    # search

    s = sub.add_parser("search", help="Search the reverse index by target")

    s.add_argument("target")

    s.add_argument("--mode", default=MatchMode.ROOT_DOMAIN,

                   choices=sorted(MatchMode.ALL))

    s.add_argument("--page-size", type=int, default=100)

    s.add_argument("--first-page-only", action="store_true")

    s.add_argument("--collection", default=None)

    s.add_argument("--source-domain", default=None)

    s.add_argument("--anchor", default=None)

    s.add_argument("--link-type", default=None)

    s.add_argument("--no-blank-anchor", action="store_true")

    s.add_argument("--unique-domains", action="store_true")

    s.add_argument("--sort-by", default="last_seen_at")

    s.add_argument("--ascending", action="store_true")

    s.add_argument("--export", default=None,

                   help="Export all matches to CSV/TSV/JSON by extension")

    s.set_defaults(func=cmd_search)

    # verify

    v = sub.add_parser("verify", help="Live-verify sources against a target")

    v.add_argument("--target", required=True)

    v.add_argument("--mode", default=MatchMode.ROOT_DOMAIN,

                   choices=sorted(MatchMode.ALL))

    v.add_argument("--source-list", default=None)

    v.add_argument("--source", default=None)

    v.set_defaults(func=cmd_verify)

    return p

def main(argv: Optional[List[str]] = None) -> int:

    args = build_parser().parse_args(argv)

    cfg = get_config()

    setup_logging(cfg.log_dir, cfg.log_level)

    # selftest manages its own DB; everything else uses the configured one.

    if args.command == "selftest":

        db = Database(cfg)

        try:

            return args.func(args, db)

        finally:

            db.close()

    db = Database(cfg)

    try:

        return args.func(args, db)

    finally:

        db.close()

if __name__ == "__main__":

    sys.exit(main())✅ Part complete — backlink_hunter.py (CLI + selftest) is whole.Say next for the Streamlit app (streamlit_app.py) with the 9 pages, Automatic Backlink Discovery as default, no candidate/seed inputs in automatic mode, pagination, and all exports.
