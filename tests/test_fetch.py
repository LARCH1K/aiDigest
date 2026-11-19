from unittest.mock import MagicMock, Mock

from aidigest.cache import DiskCache
from aidigest.fetch import fetch_article_text


def test_article_fetch_pins_address_and_revalidates_redirect(tmp_path, monkeypatch):
    def resolve(host, *args, **kwargs):
        address = "93.184.216.34" if host == "example.org" else "127.0.0.1"
        return [(None, None, None, None, (address, 443))]

    monkeypatch.setattr("aidigest.fetch.getaddrinfo", resolve)
    pool = MagicMock()
    pool.return_value.request.return_value = Mock(
        status=302, headers={"Location": "https://www.example.org/private"},
    )
    monkeypatch.setattr("urllib3.HTTPSConnectionPool", pool)
    assert fetch_article_text("https://example.org/news", DiskCache(tmp_path)) == ""
    pool.assert_called_once()
    assert pool.call_args.args[0] == "93.184.216.34"
    assert pool.call_args.kwargs["server_hostname"] == "example.org"
    assert pool.call_args.kwargs["assert_hostname"] == "example.org"
