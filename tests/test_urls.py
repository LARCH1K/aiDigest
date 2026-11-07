from aidigest.urls import domain_of, normalize_url


def test_normalize_url_drops_tracking():
    a = normalize_url("https://digitalservice.bund.de/en/projects/agentic-ai-hub?utm_source=chatgpt.com#top")
    assert a == "https://digitalservice.bund.de/en/projects/agentic-ai-hub"
    assert normalize_url("https://WWW.Example.com/a/?id=5&utm_medium=x") == "https://www.example.com/a?id=5"


def test_normalize_url_decodes_punycode_host():
    assert normalize_url("https://xn--80akpjgfht4a0d.xn--p1ai/news/") == "https://нацпроекты.рф/news"


def test_domain_of_decodes_punycode():
    assert domain_of("https://xn--80akpjgfht4a0d.xn--p1ai/news/1") == "нацпроекты.рф"
    assert domain_of("https://www.chel.kp.ru/x") == "chel.kp.ru"
