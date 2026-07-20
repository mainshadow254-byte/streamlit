"""Live verification: confirm the archived backlink still exists on the live page."""
from __future__ import annotations
import json
import aiohttp
from .config import Settings
from .htmlparse import extract_links
from .matching import MatchMode, matches_target
from .models import Backlink, utcnow_iso
from .net import RateLimiter, fetch_live
async def verify_live(
    session: aiohttp.ClientSession,
    limiter: RateLimiter,
    settings: Settings,
    bl: Backlink,
    *,
    mode: MatchMode,
    match_kwargs: dict,
) -> Backlink:
    """Fetch the live source page and confirm the hyperlink is still present.
    Never labels an unreachable page as live."""
    result = await fetch_live(session, limiter, settings, bl.source_url)
    bl.last_checked_at = utcnow_iso()
    bl.redirect_chain = json.dumps(result.redirect_chain)
    bl.source_http_status = result.status
    reachable = (
        not result.error
        and result.status is not None
        and result.status < 400
        and bool(result.body)
    )
    if not reachable:
        bl.live_backlink_present = False
        bl.verification_status = "ARCHIVED_ONLY"
        return bl
    _title, links = extract_links(result.body.decode("utf-8", "replace"), bl.source_url)
    present = any(matches_target(l.resolved, mode=mode, **match_kwargs) for l in links)
    bl.live_backlink_present = present
    bl.verification_status = "LIVE_CONFIRMED" if present else "ARCHIVED_ONLY"
    return bl
