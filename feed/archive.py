"""Import an individual article from a supported publisher."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener

from .articles import article_list
from .links import publisher_article
from .sources import download, publication_time
from .vault import save_article


class ArticleMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attributes):
        if tag == "meta":
            attrs = dict(attributes)
            field = attrs.get("property")
            value = attrs.get("content")
            if field and value:
                self.fields[field] = value


class ArticleRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        try:
            original = publisher_article(request.full_url)
            redirected = publisher_article(newurl)
        except ValueError:
            return None
        if original == redirected:
            return super().redirect_request(request, fp, code, msg, headers, newurl)
        return None


def article_metadata(url: str) -> dict:
    document, _ = download(url, open_url=build_opener(ArticleRedirects()).open)
    parser = ArticleMetadata()
    parser.feed(document)
    parser.close()
    if parser.fields.get("og:type") == "article" or parser.fields.get("article:published_time"):
        return parser.fields
    return {}


def import_article(vault: Path, url: str, title: str) -> dict:
    source, canonical = publisher_article(url)
    if any(article["url"] == canonical for article in article_list(vault)["articles"]):
        return {"url": canonical, "already_saved": True}
    if not (vault / ".obsidian").is_dir():
        raise ValueError("옵시디언 벌트를 먼저 초기화해 주세요.")

    metadata = {}
    try:
        metadata = article_metadata(canonical)
    except HTTPError as error:
        if error.code in (404, 410):
            raise ValueError("출처에서 이 기사를 찾을 수 없습니다.") from None
    except (OSError, ValueError):
        pass
    automatic_title = metadata.get("og:title", "").removesuffix(" : 라이브러리").strip()
    title = (title or automatic_title)[:400].strip()
    if not title:
        raise ValueError("출처에서 제목을 읽을 수 없습니다. 기사 제목을 입력해 주세요.")
    excerpt = " ".join(metadata.get("og:description", "").split())[:400]
    save_article(
        vault, url=canonical, title=title, source=source, topics=[],
        summary=excerpt or "기사 내용은 원문 링크에서 확인할 수 있습니다.",
        content_basis="public-listing" if excerpt else None,
        published_at=publication_time(metadata.get("article:published_time", "")),
    )
    return {"url": canonical, "already_saved": False}
