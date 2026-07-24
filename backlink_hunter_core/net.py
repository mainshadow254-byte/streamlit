"""Safe HTTP client: SSRF-guarded, rate-limited, size-capped, retry/backoff."""

from __future__ import annotations

import threading

import time

from dataclasses import dataclass, field

from typing import Dict, List, Optional

from urllib import robotparser

from urllib.parse import urlsplit, urljoin

from .config import Config, get_config

from .logging_setup import get_logger

from .security import (

    SecurityError,

    assert_safe_url,

)

log = get_logger("net")

try:

    import requests  # type: ignore

    _HAVE_REQUESTS = True

except Exception:  # pragma: no cover

    requests = None  # type: ignore

    _HAVE_REQUESTS = False

class FetchError(Exception):

    pass

@dataclass

class FetchResult:

    url: str

    final_url: str

    status: int

    content_type: str

    body: bytes

    redirect_chain: List[str] = field(default_factory=list)

    from_cache: bool = False

    @property

    def text(self) -> str:

        try:

            return self.body.decode("utf-8", errors="replace")

        except Exception:

            return ""

class RateLimiter:

    def __init__(self, global_rate: float, per_host_rate: float):

        self._global_interval = 1.0 / global_rate if global_rate > 0 else 0.0

        self._host_interval = 1.0 / per_host_rate if per_host_rate > 0 else 0.0

        self._lock = threading.Lock()

        self._last_global = 0.0

        self._last_host: Dict[str, float] = {}

    def acquire(self, host: str) -> None:

        with self._lock:

            now = time.monotonic()

            wait = 0.0

            if self._global_interval:

                wait = max(wait, self._last_global + self._global_interval - now)

            if self._host_interval:

                last = self._last_host.get(host, 0.0)

                wait = max(wait, last + self._host_interval - now)

            if wait > 0:

                time.sleep(wait)

            now = time.monotonic()

            self._last_global = now

            self._last_host[host] = now

class RobotsCache:

    def __init__(self, user_agent: str, fetcher: "SafeHTTPClient"):

        self.user_agent = user_agent

        self.fetcher = fetcher

        self._cache: Dict[str, Optional[robotparser.RobotFileParser]] = {}

        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:

        parts = urlsplit(url)

        base = f"{parts.scheme}://{parts.netloc}"

        with self._lock:

            rp = self._cache.get(base, "missing")

        if rp == "missing":

            rp = self._load(base)

            with self._lock:

                self._cache[base] = rp

        if rp is None:

            return True

        try:

            return rp.can_fetch(self.user_agent, url)

        except Exception:

            return True

    def _load(self, base: str) -> Optional[robotparser.RobotFileParser]:

        robots_url = urljoin(base, "/robots.txt")

        try:

            res = self.fetcher.fetch(robots_url, respect_robots=False,

                                     max_bytes=512 * 1024)

        except Exception:

            return None

        if res.status >= 400 or not res.body:

            return None

        rp = robotparser.RobotFileParser()

        try:

            rp.parse(res.text.splitlines())

        except Exception:

            return None

        return rp

class SafeHTTPClient:

    def __init__(self, cfg: Optional[Config] = None):

        self.cfg = cfg or get_config()

        self.rate = RateLimiter(self.cfg.global_rate, self.cfg.per_host_rate)

        self.robots = RobotsCache(self.cfg.user_agent, self)

        if _HAVE_REQUESTS:

            self._session = requests.Session()

            self._session.headers.update({"User-Agent": self.cfg.user_agent})

        else:  # pragma: no cover

            self._session = None

    def fetch(self, url: str, method: str = "GET",

              respect_robots: Optional[bool] = None,

              max_bytes: Optional[int] = None,

              max_retries: int = 3) -> FetchResult:

        respect = self.cfg.respect_robots if respect_robots is None else respect_robots

        cap = max_bytes if max_bytes is not None else self.cfg.max_response_bytes

        assert_safe_url(url)

        if respect and not self.robots.allowed(url):

            raise FetchError(f"Blocked by robots.txt: {url}")

        attempt = 0

        backoff = 1.0

        last_exc: Optional[Exception] = None

        while attempt <= max_retries:

            attempt += 1

            try:

                return self._do_fetch(url, method, cap)

            except _RetryableStatus as rs:

                last_exc = rs

                if rs.retry_after is not None:

                    time.sleep(min(rs.retry_after, 60))

                else:

                    time.sleep(backoff)

                    backoff = min(backoff * 2, 30)

            except (SecurityError, FetchError):

                raise

            except Exception as exc:

                last_exc = exc

                time.sleep(backoff)

                backoff = min(backoff * 2, 30)

        raise FetchError(f"Failed after {max_retries} retries: {url} ({last_exc})")

    def _do_fetch(self, url: str, method: str, cap: int) -> FetchResult:

        parts = urlsplit(url)

        host = (parts.hostname or "").lower()

        self.rate.acquire(host)

        redirect_chain: List[str] = []

        current = url

        for _ in range(self.cfg.max_redirects + 1):

            assert_safe_url(current)

            resp = self._request_once(current, method, cap)

            if resp["status"] in (301, 302, 303, 307, 308) and resp["location"]:

                nxt = urljoin(current, resp["location"])

                redirect_chain.append(current)

                current = nxt

                continue

            if resp["status"] in (429, 503):

                raise _RetryableStatus(resp["status"], resp["retry_after"])

            return FetchResult(

                url=url, final_url=current, status=resp["status"],

                content_type=resp["content_type"], body=resp["body"],

                redirect_chain=redirect_chain,

            )

        raise FetchError(f"Too many redirects: {url}")

    def _request_once(self, url: str, method: str, cap: int) -> Dict:

        if _HAVE_REQUESTS:

            return self._request_requests(url, method, cap)

        return self._request_urllib(url, method, cap)  # pragma: no cover

    def _request_requests(self, url: str, method: str, cap: int) -> Dict:

        assert self._session is not None

        with self._session.request(

            method, url, stream=True, allow_redirects=False,

            timeout=self.cfg.timeout, verify=self.cfg.verify_tls,

        ) as r:

            status = r.status_code

            location = r.headers.get("Location", "")

            content_type = r.headers.get("Content-Type", "")

            retry_after = _parse_retry_after(r.headers.get("Retry-After"))

            body = b""

            if not (300 <= status < 400):

                body = self._read_capped(r, cap)

            return {

                "status": status, "location": location,

                "content_type": content_type, "body": body,

                "retry_after": retry_after,

            }

    def _read_capped(self, r, cap: int) -> bytes:

        buf = bytearray()

        for chunk in r.iter_content(chunk_size=65536):

            if not chunk:

                continue

            buf.extend(chunk)

            if len(buf) > cap:

                raise FetchError(f"Response exceeds max size ({cap} bytes)")

        return bytes(buf)

    def _request_urllib(self, url: str, method: str, cap: int) -> Dict:  # pragma: no cover

        import urllib.request

        req = urllib.request.Request(

            url, method=method,

            headers={"User-Agent": self.cfg.user_agent},

        )

        try:

            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:

                status = resp.status

                content_type = resp.headers.get("Content-Type", "")

                body = resp.read(cap + 1)

                if len(body) > cap:

                    raise FetchError("Response exceeds max size")

                return {

                    "status": status, "location": "",

                    "content_type": content_type, "body": body,

                    "retry_after": None,

                }

        except Exception as exc:

            raise FetchError(str(exc))

    def get_range(self, url: str, offset: int, length: int) -> bytes:

        assert_safe_url(url)

        host = (urlsplit(url).hostname or "").lower()

        self.rate.acquire(host)

        end = offset + length - 1

        headers = {"Range": f"bytes={offset}-{end}",

                   "User-Agent": self.cfg.user_agent}

        if _HAVE_REQUESTS:

            assert self._session is not None

            with self._session.get(

                url, headers=headers, stream=True, timeout=self.cfg.timeout,

                verify=self.cfg.verify_tls, allow_redirects=False,

            ) as r:

                if r.status_code not in (200, 206):

                    raise FetchError(f"Range request failed: {r.status_code}")

                buf = bytearray()

                cap = length + 65536

                for chunk in r.iter_content(chunk_size=65536):

                    buf.extend(chunk)

                    if len(buf) > cap:

                        break

                return bytes(buf)

        raise FetchError("Range requests require the 'requests' package")

class _RetryableStatus(Exception):

    def __init__(self, status: int, retry_after: Optional[float]):

        super().__init__(f"retryable status {status}")

        self.status = status

        self.retry_after = retry_after

def _parse_retry_after(value: Optional[str]) -> Optional[float]:

    if not value:

        return None

    try:

        return float(value)

    except ValueError:

        return 5.0
