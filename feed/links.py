"""Validate and normalize article links before storing or displaying them."""

from urllib.parse import parse_qs, urlsplit


def publisher_article(url: str) -> tuple[str, str]:
    """Return the source and stable permalink for supported article URLs."""
    if not public_link(url):
        raise ValueError("긱뉴스 또는 커피팟의 기사 주소를 입력해 주세요.")
    link = urlsplit(url)
    query = parse_qs(link.query)
    host = link.netloc.lower()
    if host == "news.hada.io" and link.path == "/topic":
        article_id = query.get("id", [""])[0]
        if article_id.isascii() and article_id.isdecimal():
            return "GeekNews", f"https://news.hada.io/topic?id={article_id}"
    if host in {"coffeepot.me", "www.coffeepot.me"} and link.path.rstrip("/") == "/library":
        article_id = query.get("idx", [""])[0]
        if query.get("bmode") == ["view"] and article_id.isascii() and article_id.isdecimal():
            return "COFFEEPOT", f"https://coffeepot.me/library/?bmode=view&idx={article_id}"
    raise ValueError("긱뉴스 게시글 또는 커피팟 라이브러리의 기사 주소를 입력해 주세요.")


def public_link(url: str) -> str | None:
    try:
        link = urlsplit(url)
        if link.scheme not in {"http", "https"} or not link.hostname or link.username is not None:
            return None
        if any(char.isspace() or ord(char) < 32 for char in url):
            return None
    except ValueError:
        return None
    if link.hostname == "news.hada.io" and link.path == "/topic":
        item_id = parse_qs(link.query).get("id", [""])[0]
        if item_id.isascii() and item_id.isdecimal():
            return f"https://news.hada.io/topic?id={item_id}"
    return url
