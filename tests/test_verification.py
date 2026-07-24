"""Tests: live verification statuses using a mocked HTTP client (no network)."""

from __future__ import annotations

from backlink_hunter_core.net import FetchResult, FetchError

from backlink_hunter_core.models import MatchMode, VerificationStatus

from backlink_hunter_core.verification import Verifier

class FakeClient:

    def __init__(self, result=None, exc=None):

        self._result = result

        self._exc = exc

    def fetch(self, url, method="GET", **kw):

        if self._exc:

            raise self._exc

        return self._result

def _html_with_link():

    return (

        "<html><body>"

        "<a href='https://www.amazon.com/dp/1'>buy</a>"

        "</body></html>"

    )

def _result(body: str, status: int = 200, final=None):

    b = body.encode("utf-8")

    return FetchResult(

        url="https://src.example/p",

        final_url=final or "https://src.example/p",

        status=status, content_type="text/html", body=b,

        redirect_chain=[],

    )

def test_live_confirmed_when_link_present():

    client = FakeClient(result=_result(_html_with_link()))

    v = Verifier(db=None, client=client)

    res = v.verify("https://src.example/p", "amazon.com",

                   MatchMode.ROOT_DOMAIN, had_archive=False)

    assert res.status == VerificationStatus.LIVE_CONFIRMED

    assert res.live_present is True

def test_removed_when_link_absent():

    client = FakeClient(result=_result("<html><body>no links</body></html>"))

    v = Verifier(db=None, client=client)

    res = v.verify("https://src.example/p", "amazon.com",

                   MatchMode.ROOT_DOMAIN, had_archive=True)

    assert res.status == VerificationStatus.REMOVED

    assert res.live_present is False

def test_archived_confirmed_when_present_and_had_archive():

    client = FakeClient(result=_result(_html_with_link()))

    v = Verifier(db=None, client=client)

    res = v.verify("https://src.example/p", "amazon.com",

                   MatchMode.ROOT_DOMAIN, had_archive=True)

    assert res.status == VerificationStatus.ARCHIVED_CONFIRMED

    assert res.live_present is True

def test_source_unavailable_on_fetch_error_no_archive():

    client = FakeClient(exc=FetchError("boom"))

    v = Verifier(db=None, client=client)

    res = v.verify("https://src.example/p", "amazon.com",

                   MatchMode.ROOT_DOMAIN, had_archive=False)

    assert res.status == VerificationStatus.SOURCE_UNAVAILABLE

    assert res.live_present is None

def test_archived_only_on_fetch_error_with_archive():

    client = FakeClient(exc=FetchError("boom"))

    v = Verifier(db=None, client=client)

    res = v.verify("https://src.example/p", "amazon.com",

                   MatchMode.ROOT_DOMAIN, had_archive=True)

    assert res.status == VerificationStatus.ARCHIVED_ONLY

def test_never_marks_unavailable_as_live():

    client = FakeClient(result=_result("error page", status=503))

    v = Verifier(db=None, client=client)

    res = v.verify("https://src.example/p", "amazon.com",

                   MatchMode.ROOT_DOMAIN, had_archive=True)

    assert res.live_present is not True

    assert res.status in (

        VerificationStatus.ARCHIVED_ONLY,

        VerificationStatus.SOURCE_UNAVAILABLE,

    )

def test_verify_and_store_updates_db(db):

    from backlink_hunter_core.importers import build_backlink

    from backlink_hunter_core.models import DatasetType

    bl = build_backlink(

        source_url="https://src.example/p",

        target_url="https://www.amazon.com/dp/1",

        collection="test", dataset_type=DatasetType.FIXTURE)

    db.insert_backlinks([bl])

    row = db.conn.execute("SELECT id FROM reverse_links LIMIT 1").fetchone()

    client = FakeClient(result=_result(_html_with_link()))

    v = Verifier(db=db, client=client)

    v.verify_and_store(row["id"], "https://src.example/p", "amazon.com",

                       MatchMode.ROOT_DOMAIN, had_archive=True)

    updated = db.conn.execute(

        "SELECT verification_status, live_backlink_present "

        "FROM reverse_links WHERE id=?", (row["id"],)).fetchone()

    assert updated["live_backlink_present"] == 1

    assert updated["verification_status"] == VerificationStatus.ARCHIVED_CONFIRMED
