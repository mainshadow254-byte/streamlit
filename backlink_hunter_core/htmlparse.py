"""Hyperlink extraction + rel classification using BeautifulSoup + lxml."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


_BAD_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "file:", "ftp:", "gopher:")


@dataclass
class RawLink:
    href: str
    resolved: str
    anchor_text: str
    image_alt: str
    rel: str
    link_type: str


def _rel_to_str(rel_attr) -> str:
    """Normalize BeautifulSoup's multi-value ``rel`` attribute to text."""
    if rel_attr is None:
        return ""
    if isinstance(rel_attr, (list, tuple)):
        return " ".join(str(value) for value in rel_attr)
    return str(rel_attr)


def classify_rel(rel: str) -> str:
    tokens = {token.strip().lower() for token in rel.split() if token.strip()}
    flags = tokens & {"nofollow", "sponsored", "ugc"}
    if len(flags) > 1:
        return "MULTIPLE_REL_VALUES"
    if "sponsored" in flags:
        return "SPONSORED"
    if "ugc" in flags:
        return "UGC"
    if "nofollow" in flags:
        return "NOFOLLOW"
    return "FOLLOW"


def _base_url(soup: BeautifulSoup, page_url: str) -> str:
    node = soup.find("base", href=True)
    if node:
        href = (node.get("href") or "").strip()
        if href:
            return urljoin(page_url, href)
    return page_url


def extract_links(html: str, page_url: str) -> tuple[str, list[RawLink]]:
    """Return the page title and all valid, resolved hyperlinks."""
    soup = BeautifulSoup(html or "", "lxml")
    title_node = soup.find("title")
    title = title_node.get_text(strip=True) if title_node else ""
    base = _base_url(soup, page_url)

    links: list[RawLink] = []
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href or any(href.lower().startswith(scheme) for scheme in _BAD_SCHEMES):
            continue
        if href.startswith("//"):
            scheme = urlsplit(page_url).scheme or "https"
            resolved = f"{scheme}:{href}"
        else:
            resolved = urljoin(base, href)
        if not urlsplit(resolved).scheme.startswith("http"):
            continue

        image = anchor.find("img", alt=True)
        rel = _rel_to_str(anchor.get("rel"))
        links.append(
            RawLink(
                href=href,
                resolved=resolved,
                anchor_text=anchor.get_text(strip=True) or "",
                image_alt=(image.get("alt") or "") if image else "",
                rel=rel,
                link_type=classify_rel(rel),
            )
        )
    return title, links
