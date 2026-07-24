"""Tests: HTML link extraction, rel classification, images, malformed HTML."""

from __future__ import annotations

from backlink_hunter_core.htmlparse import classify_rel, parse_html_links, parse_title

from backlink_hunter_core.models import LinkType

BASE = "https://blog.example/post"

def test_extracts_only_real_links_not_plaintext():

    html = """

    <a href="https://amazon.com/x">buy</a>

    <p>I mention amazon.com in text but do not link it.</p>

    """

    links = parse_html_links(html, BASE)

    hosts = [l.hostname for l in links]

    assert hosts.count("amazon.com") == 1

def test_ignores_mailto_js_empty():

    html = """

    <a href="mailto:a@b.com">m</a>

    <a href="javascript:void(0)">j</a>

    <a href="">empty</a>

    <a href="https://ok.com">ok</a>

    """

    links = parse_html_links(html, BASE)

    assert len(links) == 1

    assert links[0].hostname == "ok.com"

def test_relative_and_protocol_relative():

    html = '<a href="/rel">r</a><a href="//cdn.example.net/x">p</a>'

    links = parse_html_links(html, BASE)

    hosts = {l.hostname for l in links}

    assert "blog.example" in hosts

    assert "cdn.example.net" in hosts

def test_image_link_uses_alt_when_no_text():

    html = '<a href="https://amazon.com/x"><img src="a.png" alt="Amazon logo"></a>'

    links = parse_html_links(html, BASE)

    assert len(links) == 1

    assert links[0].image_alt == "Amazon logo"

    assert links[0].anchor_text == ""

def test_rel_classification():

    assert classify_rel("") == LinkType.FOLLOW

    assert classify_rel("nofollow") == LinkType.NOFOLLOW

    assert classify_rel("sponsored") == LinkType.SPONSORED

    assert classify_rel("ugc") == LinkType.UGC

    assert classify_rel("nofollow sponsored") == LinkType.MULTIPLE_REL_VALUES

    assert classify_rel("ugc nofollow") == LinkType.MULTIPLE_REL_VALUES

def test_malformed_html_does_not_crash():

    html = '<a href="https://amazon.com/x">unclosed <b>bold'

    links = parse_html_links(html, BASE)

    assert any(l.hostname == "amazon.com" for l in links)

def test_commented_out_links_ignored():

    html = '<!-- <a href="https://amazon.com/c">c</a> --><a href="https://ok.com">o</a>'

    links = parse_html_links(html, BASE)

    hosts = {l.hostname for l in links}

    assert "ok.com" in hosts

    assert "amazon.com" not in hosts

def test_title_extraction():

    assert parse_title("<html><head><title>Hi</title></head></html>") == "Hi"
