import pytest  
  
from backlink_hunter_core.ssrf import BlockedTargetError, assert_safe_url  
  
  
@pytest.mark.parametrize("url", [  
    "http://127.0.0.1/",  
    "http://localhost/",  
    "http://169.254.169.254/latest/meta-data/",  
    "file:///etc/passwd",  
    "ftp://example.com/",  
    "gopher://example.com/",  
    "http://10.0.0.5/",  
    "http://192.168.1.1/",  
])  
def test_blocked(url):  
    with pytest.raises(BlockedTargetError):  
        assert_safe_url(url)
