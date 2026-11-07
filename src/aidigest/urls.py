"""Нормализация URL: одна и та же страница должна давать одну и ту же строку."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "yclid", "gclid"}


def _decode_host(host: str) -> str:
    parts = []
    for label in host.lower().split("."):
        if label.startswith("xn--"):
            try:
                label = label.encode("ascii").decode("idna")
            except UnicodeError:
                pass
        parts.append(label)
    return ".".join(parts)


def normalize_url(url: str) -> str:
    s = urlsplit(url.strip())
    host = _decode_host(s.hostname or "")
    netloc = f"{host}:{s.port}" if s.port else host
    query = urlencode([
        (k, v) for k, v in parse_qsl(s.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ])
    path = s.path.rstrip("/")
    return urlunsplit((s.scheme.lower() or "https", netloc, path, query, ""))


def domain_of(url: str) -> str:
    host = _decode_host(urlsplit(url.strip()).hostname or "")
    return host.removeprefix("www.")
