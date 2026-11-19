"""Скачивание и кеширование текста статьи."""
from __future__ import annotations

import sys
from ipaddress import ip_address
from pathlib import Path
from socket import SOCK_STREAM, getaddrinfo
from urllib.parse import urljoin, urlsplit

from aidigest.cache import DiskCache
from aidigest.urls import domain_of

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def fetch_text(url: str, cache: DiskCache, manual_dir: Path, ref_id: str, index: int,
               allow_network: bool = True) -> str:
    manual = Path(manual_dir) / f"{ref_id}-{index}.txt"
    if manual.exists():
        return manual.read_text(encoding="utf-8")
    return fetch_article_text(url, cache, allow_network)


def _public_address(host: str, port: int) -> str | None:
    addresses = [ip_address(row[4][0]) for row in getaddrinfo(host, port, type=SOCK_STREAM)]
    if not addresses or any(not address.is_global or address.is_multicast for address in addresses):
        return None
    return str(addresses[0])


def fetch_article_text(url: str, cache: DiskCache, allow_network: bool = True) -> str:
    cached = cache.get("fetch", url)
    if cached is not None:
        return cached
    if not allow_network:
        return ""
    try:
        import requests
        import trafilatura
        import urllib3

        target = url
        source_domain = domain_of(url)
        for _ in range(5):
            parsed = urlsplit(target)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or domain_of(target) != source_domain):
                return ""
            https = parsed.scheme == "https"
            port = parsed.port or (443 if https else 80)
            if port not in (80, 443):
                return ""
            host = parsed.hostname.encode("idna").decode("ascii")
            address = _public_address(host, port)
            if address is None:
                return ""
            # Подключаемся к проверенному IP, сохраняя имя для Host, SNI и проверки сертификата.
            if https:
                pool = urllib3.HTTPSConnectionPool(address, port, server_hostname=host, assert_hostname=host,
                                                   cert_reqs="CERT_REQUIRED", ca_certs=requests.certs.where())
            else:
                pool = urllib3.HTTPConnectionPool(address, port)
            path = requests.Request("GET", target).prepare().path_url
            authority = f"[{host}]" if ":" in host else host
            if parsed.port is not None:
                authority += f":{parsed.port}"
            with pool:
                resp = pool.request("GET", path, timeout=urllib3.Timeout(connect=5, read=10),
                                    headers={"Host": authority, "User-Agent": _UA},
                                    retries=False, redirect=False, preload_content=False)
                if 300 <= resp.status < 400 and resp.headers.get("Location"):
                    target = urljoin(target, resp.headers["Location"])
                    resp.close()
                    continue
                if resp.status != 200:
                    resp.close()
                    return ""
                body = bytearray()
                with resp:
                    for chunk in resp.stream(65536, decode_content=True):
                        body.extend(chunk)
                        if len(body) > 4 * 1024 * 1024:
                            return ""
                text = trafilatura.extract(bytes(body), include_comments=False, include_tables=True) or ""
                break
        else:
            return ""
    except Exception as e:
        print(f"Не удалось скачать {url}: {e}", file=sys.stderr)
        return ""
    if text:
        cache.put("fetch", url, text)
    return text
