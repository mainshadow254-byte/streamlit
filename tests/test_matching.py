from backlink_hunter_core.matching import MatchMode, matches_target
MK = dict(
    target_host="example.com", target_root="example.com",
    target_url="https://example.com/", target_path_prefix="/",
)
def test_true_positive_subdomain():
    assert matches_target(
        "https://blog.example.com/x", mode=MatchMode.ROOT_AND_SUBDOMAINS, **MK
    )
def test_reject_notexample():
    assert not matches_target(
        "https://notexample.com/", mode=MatchMode.ROOT_AND_SUBDOMAINS, **MK
    )
def test_reject_suffix_trick():
    assert not matches_target(
        "https://example.com.evil.org/", mode=MatchMode.ROOT_AND_SUBDOMAINS, **MK
    )
def test_reject_query_mention():
    assert not matches_target(
        "https://other.org/?q=example.com", mode=MatchMode.ROOT_AND_SUBDOMAINS, **MK
    )
def test_exact_host():
    assert matches_target("https://example.com/a", mode=MatchMode.EXACT_HOST, **MK)
    assert not matches_target(
        "https://www.example.com/a", mode=MatchMode.EXACT_HOST, **MK
    )
def test_path_prefix():
    mk = dict(MK, target_path_prefix="/blog")
    assert matches_target("https://example.com/blog/post", mode=MatchMode.PATH_PREFIX, **mk)
    assert not matches_target("https://example.com/shop", mode=MatchMode.PATH_PREFIX, **mk)
