"""Validate and normalize article links before storing or displaying them."""

from urllib.parse import parse_qs, urlsplit


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
