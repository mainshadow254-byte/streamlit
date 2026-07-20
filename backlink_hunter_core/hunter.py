"""Async orchestration engine: real counters, thread-safe stop/pause/resume."""
from __future__ import annotations
import asyncio
import json
import threading
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import aiohttp
from .commoncrawl import fetch_warc_bytes, query_cdx
from .config import Settings
from .htmlparse import extract_links
from .matching import MatchMode, matches_target
from .models import Backlink, SearchStats, utcnow_iso
from .net import RateLimiter, fetch_live, make_session
from .normalize import hostname_of, normalize_url, registrable_domain
from .verify import verify_live
OnFound = Callable[[Backlink], None]
class Engine:
    """Owns one search run. Controlled from any thread via threading.Events."""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stats = SearchStats()
        self._stop = threading.Event()
        self._paused = threading.Event()  # set() == paused
        self._seen: set[tuple[str, str]] = set()
        self._robots_cache: dict[str, Optional[RobotFileParser]] = {}
    # ---- control ----
    def stop(self) -> None:
        self._stop.set()
    def pause(self) -> None:
        self._paused.set()
    def resume(self) -> None:
        self._paused.clear()
    @property
    def stopped(self) -> bool:
        return self._stop.is_set()
    @property
    def paused(self) -> bool:
        return self._paused.is_set()
    async def _gate(self) -> None:
        while self._paused.is_set() and not self._stop.is_set():
            await asyncio.sleep(0.2)
    # ---- helpers ----
    def _dedup(self, src: str, tgt: str) -> bool:
        key = (normalize_url(src), normalize_url(tgt))
        if key in self._seen:
            self.stats.normalized_duplicates += 1
            return True
        self._seen.add(key)
        return False
    def _build(
        self,
        page_url: str,
        title: str,
        link,
        target_host: str,
        collection: str,
        *,
        rec=None,
        verification: str,
        status: Optional[int],
        content_type: str = "",
    ) -> Backlink:
        return Backlink(
            source_url=page_url,
            source_domain=registrable_domain(hostname_of(page_url)),
            target_url=link.resolved,
            target_hostname=hostname_of(link.resolved),
            anchor_text=link.anchor_text,
            image_alt=link.image_alt,
            link_type=link.link_type,
            rel=link.rel,
            source_title=title,
            source_http_status=status,
            content_type=content_type,
            verification_status=verification,
            common_crawl_collection=collection,
            warc_filename=getattr(rec, "filename", "") if rec else "",
            warc_offset=getattr(rec, "offset", None) if rec else None,
            warc_length=getattr(rec, "length", None) if rec else None,
            norm_source_url=normalize_url(page_url),
            norm_target_url=normalize_url(link.resolved),
        )
    async def _robots_allowed(
        self, session: aiohttp.ClientSession, limiter: RateLimiter, url: str
    ) -> bool:
        if not self.settings.respect_robots_txt:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots_cache:
            robots_url = urljoin(base, "/robots.txt")
            res = await fetch_live(session, limiter, self.settings, robots_url)
            rp: Optional[RobotFileParser] = None
            if res.status == 200 and res.body:
                rp = RobotFileParser()
                rp.parse(res.body.decode("utf-8", "replace").splitlines())
            self._robots_cache[base] = rp
        rp = self._robots_cache[base]
        if rp is None:
            return True  # no robots.txt found -> allowed
        return rp.can_fetch(self.settings.user_agent, url)
    # ---- strategies ----
    async def run_url_list(
        self,
        urls: Iterable[str],
        *,
        mode: MatchMode,
        match_kwargs: dict,
        target_host: str,
        on_found: OnFound,
    ) -> None:
        """Fetch each candidate URL live; confirm a hyperlink to the target."""
        urls = list(urls)
        async with make_session(self.settings) as session:
            limiter = RateLimiter(self.settings)
            sem = asyncio.Semaphore(self.settings.default_concurrency)
            async def worker(url: str) -> None:
                await self._gate()
                if self._stop.is_set():
                    return
                async with sem:
                    self.stats.records_queried += 1
                    res = await fetch_live(session, limiter, self.settings, url)
                    if res.error or not res.body:
                        self.stats.failed_requests += 1
                        return
                    self.stats.records_downloaded += 1
                    self.stats.pages_parsed += 1
                    title, links = extract_links(
                        res.body.decode("utf-8", "replace"), url
                    )
                    for l in links:
                        if not matches_target(l.resolved, mode=mode, **match_kwargs):
                            continue
                        if self._dedup(url, l.resolved):
                            continue
                        self.stats.backlinks_discovered += 1
                        self.stats.backlinks_verified += 1
                        bl = self._build(
                            url, title, l, target_host, "",
                            verification="LIVE_CONFIRMED", status=res.status,
                            content_type=res.content_type,
                        )
                        bl.live_backlink_present = True
                        bl.redirect_chain = json.dumps(res.redirect_chain)
                        on_found(bl)
            await asyncio.gather(*(worker(u) for u in urls))
    async def run_seed_crawl(
        self,
        seeds: Iterable[str],
        *,
        mode: MatchMode,
        match_kwargs: dict,
        target_host: str,
        max_pages: int,
        on_found: OnFound,
    ) -> None:
        """Robots-respecting BFS crawl of supplied seed sites (same registrable domain)."""
        async with make_session(self.settings) as session:
            limiter = RateLimiter(self.settings)
            queue: asyncio.Queue[str] = asyncio.Queue()
            for s in seeds:
                if "://" not in s:
                    s = "http://" + s
                await queue.put(s)
            visited: set[str] = set()
            allowed_roots = {registrable_domain(hostname_of(u)) for u in list(queue._queue)}  # type: ignore
            processed = 0
            while not queue.empty() and processed < max_pages and not self._stop.is_set():
                await self._gate()
                url = await queue.get()
                nurl = normalize_url(url)
                if nurl in visited:
                    continue
                visited.add(nurl)
                if registrable_domain(hostname_of(url)) not in allowed_roots:
                    continue
                if not await self._robots_allowed(session, limiter, url):
                    continue
                self.stats.records_queried += 1
                res = await fetch_live(session, limiter, self.settings, url)
                if res.error or not res.body:
                    self.stats.failed_requests += 1
                    continue
                processed += 1
                self.stats.records_downloaded += 1
                self.stats.pages_parsed += 1
                title, links = extract_links(res.body.decode("utf-8", "replace"), url)
                for l in links:
                    lhost_root = registrable_domain(hostname_of(l.resolved))
                    # enqueue same-site links for further crawling
                    if lhost_root in allowed_roots and normalize_url(l.resolved) not in visited:
                        if queue.qsize() + processed < max_pages * 4:
                            await queue.put(l.resolved)
                    if matches_target(l.resolved, mode=mode, **match_kwargs):
                        if self._dedup(url, l.resolved):
                            continue
                        self.stats.backlinks_discovered += 1
                        self.stats.backlinks_verified += 1
                        bl = self._build(
                            url, title, l, target_host, "",
                            verification="LIVE_CONFIRMED", status=res.status,
                            content_type=res.content_type,
                        )
                        bl.live_backlink_present = True
                        bl.redirect_chain = json.dumps(res.redirect_chain)
                        on_found(bl)
    async def run_common_crawl(
        self,
        seed_domains: Iterable[str],
        collection: str,
        *,
        mode: MatchMode,
        match_kwargs: dict,
        target_host: str,
        max_records: int,
        on_found: OnFound,
        live_verify: bool = False,
    ) -> None:
        """Pull archived pages of seed domains from CC, parse outbound links to target."""
        seed_domains = list(seed_domains)
        async with make_session(self.settings) as session:
            limiter = RateLimiter(self.settings)
            queue: asyncio.Queue = asyncio.Queue(
                maxsize=self.settings.default_concurrency * 4
            )
            async def producer() -> None:
                for seed in seed_domains:
                    count = 0
                    try:
                        async for rec in query_cdx(
                            session, collection, seed, limit=max_records
                        ):
                            if self._stop.is_set() or count >= max_records:
                                break
                            await self._gate()
                            self.stats.records_queried += 1
                            await queue.put(rec)
                            count += 1
                    except aiohttp.ClientError:
                        self.stats.failed_requests += 1
                for _ in range(self.settings.default_concurrency):
                    await queue.put(None)
            async def consumer() -> None:
                while True:
                    rec = await queue.get()
                    try:
                        if rec is None:
                            return
                        await self._gate()
                        if self._stop.is_set():
                            continue
                        raw = await fetch_warc_bytes(
                            session, rec, max_bytes=self.settings.maximum_response_bytes
                        )
                        if raw is None:
                            self.stats.failed_requests += 1
                            continue
                        self.stats.records_downloaded += 1
                        from .warc import parse_warc_record
                        parsed = parse_warc_record(
                            raw, max_html_bytes=self.settings.maximum_response_bytes
                        )
                        if not parsed or "html" not in parsed.content_type.lower():
                            continue
                        self.stats.pages_parsed += 1
                        page_url = parsed.target_uri or rec.url
                        title, links = extract_links(parsed.html, page_url)
                        for l in links:
                            if not matches_target(l.resolved, mode=mode, **match_kwargs):
                                continue
                            if self._dedup(page_url, l.resolved):
                                continue
                            self.stats.backlinks_discovered += 1
                            bl = self._build(
                                page_url, title, l, target_host, collection,
                                rec=rec, verification="ARCHIVED_CONFIRMED",
                                status=parsed.http_status,
                                content_type=parsed.content_type,
                            )
                            if live_verify:
                                bl = await verify_live(
                                    session, limiter, self.settings, bl,
                                    mode=mode, match_kwargs=match_kwargs,
                                )
                            if bl.verification_status in (
                                "LIVE_CONFIRMED",
                                "ARCHIVED_CONFIRMED",
                            ):
                                self.stats.backlinks_verified += 1
                            on_found(bl)
                    finally:
                        queue.task_done()
            await asyncio.gather(
                producer(),
                *(consumer() for _ in range(self.settings.default_concurrency)),
            )
