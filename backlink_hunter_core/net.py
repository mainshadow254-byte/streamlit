"""Async HTTP layer: pooling, per-host + global rate limiting, retries/backoff."""
from __future__ import annotations
import asyncio
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit
import aiohttp
from .config import Settings
from .ssrf import BlockedTargetError, assert_safe_url
@dataclass
class FetchResult:
    url: str
    status: Optional[int]
    body: bytes
    content_type: str
    redirect_chain: list[str] = field(default_factory=list)
    error: str = ""
class RateLimiter:
    def __init__(self, settings: Settings):
        self._global = asyncio.Semaphore(settings.default_concurrency)
        self._per_host: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(settings.per_host_concurrency)
        )
    def host_sem(self, url: str) -> asyncio.Semaphore:
        return self._per_host[urlsplit(url).hostname or ""]
    @property
    def global_sem(self) -> asyncio.Semaphore:
        return self._global
def make_session(settings: Settings) -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=settings.request_timeout_seconds)
    connector = aiohttp.TCPConnector(
        limit=settings.default_concurrency,
        ssl=None if settings.verify_tls else False,  # never silently disable when configured on
    )
    return aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={"User-Agent": settings.user_agent},
    )
async def fetch_live(
    session: aiohttp.ClientSession,
    limiter: RateLimiter,
    settings: Settings,
    url: str,
    *,
    retries: int = 3,
) -> FetchResult:
    """SSRF-guarded live GET: retries, backoff, Retry-After, redirect + size caps."""
    try:
        assert_safe_url(url)
    except BlockedTargetError as exc:
        return FetchResult(url, None, b"", "", [], error=f"blocked: {exc}")
    attempt = 0
    while True:
        attempt += 1
        try:
            async with limiter.global_sem, limiter.host_sem(url):
                async with session.get(
                    url,
                    allow_redirects=True,
                    max_redirects=settings.maximum_redirects,
                ) as resp:
                    chain = [str(h.url) for h in resp.history] + [str(resp.url)]
                    assert_safe_url(str(resp.url))  # re-check final destination
                    if resp.status == 429 and attempt <= retries:
                        wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                        await asyncio.sleep(min(wait, 30))
                        continue
                    body = await resp.content.read(settings.maximum_response_bytes)
                    return FetchResult(
                        url=url,
                        status=resp.status,
                        body=body,
                        content_type=resp.headers.get("Content-Type", ""),
                        redirect_chain=chain,
                    )
        except (aiohttp.ClientError, asyncio.TimeoutError, BlockedTargetError) as exc:
            if attempt > retries:
                return FetchResult(url, None, b"", "", [], error=str(exc))
            await asyncio.sleep((2 ** attempt) + random.random())
