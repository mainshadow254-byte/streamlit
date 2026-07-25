"""HTML parsing and hyperlink extraction using the stdlib html.parser."""

from __future__ import annotations

from html.parser import HTMLParser

from typing import List

from .models import ExtractedLink, LinkType

from .normalize import resolve_url, extract_hostname

def classify_rel(rel_value: str) -> str:

    if rel_value is None:

        return LinkType.FOLLOW

    tokens = [t.strip().lower() for t in rel_value.replace(",", " ").split() if t.strip()]

    flags = {t for t in tokens if t in {"nofollow", "sponsored", "ugc"}}

    if not flags:

        return LinkType.FOLLOW

    if len(flags) > 1:

        return LinkType.MULTIPLE_REL_VALUES

    only = next(iter(flags))

    return {

        "nofollow": LinkType.NOFOLLOW,

        "sponsored": LinkType.SPONSORED,

        "ugc": LinkType.UGC,

    }[only]

class _LinkParser(HTMLParser):

    def __init__(self, base_url: str):

        super().__init__(convert_charrefs=True)

        self.base_url = base_url

        self.links: List[ExtractedLink] = []

        self.title: str = ""

        self._in_title = False

        self._a_stack: List[dict] = []

    def handle_starttag(self, tag, attrs):

        attrs_d = {k.lower(): (v or "") for k, v in attrs}

        if tag == "title":

            self._in_title = True

        elif tag == "a":

            href = attrs_d.get("href", "")

            self._a_stack.append({

                "href": href,

                "rel": attrs_d.get("rel", ""),

                "text": [],

                "image_alt": "",

                "is_image": False,

            })

        elif tag == "img" and self._a_stack:

            alt = attrs_d.get("alt", "")

            self._a_stack[-1]["is_image"] = True

            if alt and not self._a_stack[-1]["image_alt"]:

                self._a_stack[-1]["image_alt"] = alt

    def handle_startendtag(self, tag, attrs):

        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):

        if tag == "title":

            self._in_title = False

        elif tag == "a" and self._a_stack:

            ctx = self._a_stack.pop()

            self._finish_anchor(ctx)

    def handle_data(self, data):

        if self._in_title:

            self.title += data

        if self._a_stack and data.strip():

            self._a_stack[-1]["text"].append(data.strip())

    def flush_open_anchors(self):

        """Emit any anchors whose closing tag never arrived (malformed HTML)."""

        while self._a_stack:

            ctx = self._a_stack.pop()

            self._finish_anchor(ctx)

    def _finish_anchor(self, ctx: dict):

        href = ctx["href"]

        resolved = resolve_url(self.base_url, href)

        if not resolved:

            return

        host = extract_hostname(resolved)

        if not host:

            return

        anchor_text = " ".join(ctx["text"]).strip()

        image_alt = ctx["image_alt"].strip()

        self.links.append(ExtractedLink(

            href=href,

            resolved_url=resolved,

            hostname=host,

            anchor_text=anchor_text if anchor_text else "",

            image_alt=image_alt,

            rel_original=ctx["rel"],

            link_type=classify_rel(ctx["rel"]),

            is_image=ctx["is_image"] and not anchor_text,

        ))

def parse_html_links(html: str, base_url: str) -> List[ExtractedLink]:

    parser = _LinkParser(base_url)

    try:

        parser.feed(html)

        parser.close()

    except Exception:

        pass

    parser.flush_open_anchors()

    return parser.links

def parse_title(html: str) -> str:

    parser = _LinkParser("")

    try:

        parser.feed(html)

        parser.close()

    except Exception:

        pass

    return parser.title.strip()
