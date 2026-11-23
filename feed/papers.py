"""Search academic metadata from Crossref and the DataCite arXiv index."""

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from .links import public_link
from .settings import KST
from .sources import PlainText


PAGE_SIZE = 12
MAX_PAGE = 100
MAX_RESPONSE = 4_000_000
DATACITE_URL = "https://api.datacite.org/dois"
CROSSREF_URL = "https://api.crossref.org/works"
OPENALEX_URL = "https://api.openalex.org/works"
SUBFIELDS_URL = "https://api.openalex.org/subfields"
OPENALEX_SEARCH_FIELDS = (
    "id,doi,display_name,publication_date,publication_year,type,authorships,abstract_inverted_index,"
    "primary_location,best_oa_location,primary_topic"
)
OPENALEX_DETAIL_FIELDS = "id,publication_date,primary_topic,referenced_works,best_oa_location,abstract_inverted_index"
ARXIV_DOI = re.compile(r"10\.48550/arxiv\.([a-z][a-z.-]*/\d{7}|\d{4}\.\d{4,5})(v\d+)?", re.I)
DOI = re.compile(r"10\.\d{4,9}/\S+")
OPENALEX_ID = re.compile(r"https://openalex\.org/W\d+")
QUERY_PUNCTUATION = re.compile(r'([+\-=!(){}\[\]^"~*?:\\/<>|&])')


def get_json(url: str, parameters: dict | None = None) -> dict:
    request = Request(f"{url}?{urlencode(parameters)}" if parameters else url, headers={
        "Accept": "application/json",
        "User-Agent": "ObsidianFeedReader/1.0 (academic paper search)",
    })
    with urlopen(request, timeout=15) as response:
        data = response.read(MAX_RESPONSE + 1)
    if len(data) > MAX_RESPONSE:
        raise ValueError("Paper response was too large")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("Unexpected paper search response")
    return payload


def abstract_text(value: str | None) -> str:
    if not value:
        return ""
    parser = PlainText()
    parser.feed(re.sub(r"(</?)jats:", r"\1", value))
    parser.close()
    return " ".join("".join(parser.parts).split())


def brief(text: str) -> str:
    if len(text) <= 900:
        return text
    return text[:900].rsplit(" ", 1)[0] + "…"


def doi_url(doi: str) -> str:
    return f"https://doi.org/{quote(doi, safe='/')}"


def arxiv_paper(attributes: dict) -> dict | None:
    doi = attributes.get("doi") or ""
    match = ARXIV_DOI.fullmatch(doi)
    titles = attributes.get("titles") or []
    if match is None or not titles:
        return None
    item_id = match[1] + (match[2] or "")
    summary = next((item["description"] for item in attributes.get("descriptions") or []
                    if item.get("descriptionType") == "Abstract" and item.get("description")), "")
    authors = [person["name"] for person in attributes.get("creators") or [] if person.get("name")]
    return {
        "title": abstract_text(titles[0]["title"]),
        "authors": authors,
        "year": attributes.get("publicationYear"),
        "venue": "arXiv",
        "kind": "프리프린트",
        "doi": doi,
        "summary": brief(abstract_text(summary)),
        "url": f"https://arxiv.org/abs/{item_id}",
        "pdf_url": f"https://arxiv.org/pdf/{item_id}",
    }


def crossref_paper(work: dict) -> dict | None:
    doi = work.get("DOI") or ""
    titles = work.get("title") or []
    if not DOI.fullmatch(doi) or not titles:
        return None
    groups = (work.get("published") or {}).get("date-parts") or []
    year = groups[0][0] if groups and groups[0] else None
    authors = [
        person.get("name") or " ".join(part for part in (person.get("given"), person.get("family")) if part)
        for person in work.get("author") or []
    ]
    venue = work.get("container-title") or [""]
    kind = "학술 출판물" if work.get("type") != "posted-content" else "프리프린트"
    return {
        "title": abstract_text(titles[0]),
        "authors": [name for name in authors if name],
        "year": year,
        "venue": abstract_text(venue[0]),
        "kind": kind,
        "doi": doi,
        "summary": brief(abstract_text(work.get("abstract"))),
        "url": doi_url(doi),
        "pdf_url": None,
    }


def search_papers(source: str, query: str, page: int, order: str) -> dict:
    if source == "arxiv":
        data = get_json(DATACITE_URL, {
            "prefix": "10.48550",
            "query": QUERY_PUNCTUATION.sub(r"\\\1", query),
            "page[number]": page,
            "page[size]": PAGE_SIZE,
            "sort": "-published" if order == "recent" else "relevance",
            "fields[dois]": "doi,titles,creators,descriptions,publicationYear",
        })
        total = data["meta"]["total"]
        papers = (arxiv_paper(record["attributes"]) for record in data["data"])
    else:
        data = get_json(CROSSREF_URL, {
            "query.bibliographic": query,
            "rows": PAGE_SIZE,
            "offset": (page - 1) * PAGE_SIZE,
            "sort": {"recent": "published", "cited": "is-referenced-by-count"}.get(order, "score"),
            "order": "desc",
            "select": "DOI,title,abstract,author,published,container-title,type",
        })["message"]
        total = data["total-results"]
        papers = (crossref_paper(work) for work in data["items"])
    return {
        "papers": [paper for paper in papers if paper is not None],
        "total": total,
        "page": page,
        "has_next": page < MAX_PAGE and page * PAGE_SIZE < total,
    }


def optional_json(url: str, parameters: dict) -> dict:
    try:
        return get_json(url, parameters)
    except (OSError, ValueError):
        return {}


def abstract_from_index(index: dict) -> str:
    words = {}
    for word, positions in index.items():
        for position in positions:
            if 0 <= position < 180:
                words[position] = word
    return brief(" ".join(words[position] for position in sorted(words)))


def topic_hierarchy(topic: dict, arxiv_subjects: list[dict]) -> list[str]:
    levels = [(topic.get(level) or {}).get("display_name") for level in ("domain", "field", "subfield")]
    if any(levels):
        return [level or "미분류" for level in levels]
    broad = next((item["subject"].removeprefix("FOS: ") for item in arxiv_subjects
                  if item.get("subject", "").startswith("FOS: ")), None)
    subfield = next((item["subject"] for item in arxiv_subjects if item.get("subjectScheme") == "arXiv"), None)
    return ["arXiv" if arxiv_subjects else "미분류", broad or "미분류", subfield or "미분류"]


def safe_https_url(url: str | None) -> str | None:
    if url and public_link(url) and urlsplit(url).scheme == "https" and "\\" not in url:
        return url
    return None


def openalex_paper(work: dict) -> dict | None:
    doi = (work.get("doi") or "").removeprefix("https://doi.org/").lower()
    title = work.get("display_name")
    if not DOI.fullmatch(doi) or not title:
        return None
    primary = work.get("primary_location") or {}
    venue = primary.get("source") or {}
    access = work.get("best_oa_location") or {}
    authors = [(item.get("author") or {}).get("display_name") for item in work.get("authorships") or []]
    return {
        "title": title,
        "authors": [name for name in authors if name],
        "year": work.get("publication_year"),
        "date": work.get("publication_date"),
        "venue": venue.get("display_name"),
        "kind": "프리프린트" if work.get("type") == "preprint" else "학술 출판물",
        "doi": doi,
        "summary": abstract_from_index(work.get("abstract_inverted_index") or {}),
        "groups": topic_hierarchy(work.get("primary_topic") or {}, []),
        "url": doi_url(doi),
        "pdf_url": safe_https_url(access.get("pdf_url")),
        "open_access_url": safe_https_url(access.get("landing_page_url")),
    }


@lru_cache(maxsize=1)
def paper_topics() -> list[dict]:
    params = {"per_page": 100, "select": "id,display_name,field,domain"}
    first = get_json(SUBFIELDS_URL, {**params, "page": 1})
    entries = first["results"]
    for page in range(2, (first["meta"]["count"] + 99) // 100 + 1):
        entries.extend(get_json(SUBFIELDS_URL, {**params, "page": page})["results"])
    topics = [
        {
            "id": entry["id"].rsplit("/", 1)[-1],
            "name": entry["display_name"],
            "field": entry["field"]["display_name"],
            "domain": entry["domain"]["display_name"],
        }
        for entry in entries
    ]
    return sorted(topics, key=lambda item: (item["domain"], item["field"], item["name"]))


def papers_in_topic(subfield: str, page: int, order: str) -> dict:
    result = get_json(OPENALEX_URL, {
        "filter": f"primary_topic.subfield.id:{subfield},has_doi:true,type:article|review|preprint",
        "select": OPENALEX_SEARCH_FIELDS,
        "sort": "cited_by_count:desc" if order == "cited" else "publication_date:desc",
        "per_page": PAGE_SIZE,
        "page": page,
    })
    total = result["meta"]["count"]
    if total == 0:
        try:
            topic = get_json(f"{SUBFIELDS_URL}/{subfield}", {"select": "display_name,field,domain"})
        except HTTPError as error:
            if error.code != 404:
                raise
        else:
            name = topic["display_name"]
            return {
                **search_papers("crossref", name, page, order),
                "source": "crossref",
                "topic_keyword": name,
                "topic_path": [topic["domain"]["display_name"], topic["field"]["display_name"], name],
            }
    papers = (openalex_paper(item) for item in result["results"])
    return {
        "papers": [paper for paper in papers if paper is not None],
        "total": total,
        "page": page,
        "has_next": page < MAX_PAGE and page * PAGE_SIZE < total,
    }


def paper_references(work: dict, crossref: dict) -> list[dict]:
    by_doi = {}
    for item in crossref.get("reference") or []:
        doi = (item.get("DOI") or "").lower()
        if DOI.fullmatch(doi):
            title = item.get("article-title") or item.get("volume-title") or ""
            by_doi[doi] = {"id": "", "title": abstract_text(title), "doi": doi, "url": doi_url(doi)}
    ids = list(dict.fromkeys(
        value for value in work.get("referenced_works") or [] if isinstance(value, str) and OPENALEX_ID.fullmatch(value)
    ))
    if not ids:
        return list(by_doi.values())
    related = optional_json(OPENALEX_URL, {
        "filter": "openalex:" + "|".join(identifier.rsplit("/", 1)[-1] for identifier in ids[:20]),
        "select": "id,display_name,doi",
        "per_page": 20,
    })
    known = {item["id"]: item for item in related.get("results", [])}
    refs = {}
    for identifier in ids:
        item = known.get(identifier, {})
        doi = (item.get("doi") or "").removeprefix("https://doi.org/").lower()
        doi = doi if DOI.fullmatch(doi) else ""
        previous = by_doi.get(doi, {})
        refs[doi or identifier] = {
            "id": identifier, "doi": doi, "title": item.get("display_name") or previous.get("title", ""),
            "url": doi_url(doi) if doi else identifier,
        }
    return list(refs.values())


def fetch_paper(source: str, doi: str) -> dict | None:
    identifier = quote(doi, safe="/")
    crossref = {}
    subjects = []
    published = None
    openalex_endpoint = f"{OPENALEX_URL}/{doi_url(doi)}"
    if source == "arxiv":
        attributes = get_json(f"{DATACITE_URL}/{identifier}")["data"]["attributes"]
        paper = arxiv_paper(attributes)
        subjects = attributes.get("subjects") or []
        published = next((item["date"][:10] for item in attributes.get("dates") or []
                          if item.get("dateType") == "Submitted" and item.get("date")), None)
    elif source == "crossref":
        crossref = get_json(f"{CROSSREF_URL}/{identifier}")["message"]
        paper = crossref_paper(crossref)
        parts = (crossref.get("published") or {}).get("date-parts") or []
        if parts and parts[0]:
            formats = ("{:04d}", "{:02d}", "{:02d}")
            published = "-".join(form.format(value) for form, value in zip(formats, parts[0]))
    else:
        work = get_json(openalex_endpoint, {"select": OPENALEX_SEARCH_FIELDS + ",referenced_works"})
        paper = openalex_paper(work)
    if paper is None:
        return None
    if source != "openalex":
        work = optional_json(openalex_endpoint, {"select": OPENALEX_DETAIL_FIELDS})
    location = work.get("best_oa_location") or {}
    paper.update(
        source=source,
        doi=doi,
        openalex_id=work.get("id"),
        date=published or work.get("publication_date") or (str(paper["year"]) if paper["year"] else None),
        groups=topic_hierarchy(work.get("primary_topic") or {}, subjects),
        summary=paper["summary"] or abstract_from_index(work.get("abstract_inverted_index") or {}),
        pdf_url=paper["pdf_url"] or safe_https_url(location.get("pdf_url")),
        open_access_url=safe_https_url(location.get("landing_page_url")),
        references=paper_references(work, crossref),
    )
    return paper


class PaperLibrary:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("CREATE TABLE IF NOT EXISTS papers (doi TEXT PRIMARY KEY, saved_at TEXT NOT NULL, data TEXT NOT NULL)")
        except Exception:
            db.close()
            raise
        return db

    def list(self) -> list[dict]:
        with closing(self.connect()) as db:
            papers = [json.loads(row[0]) for row in db.execute("SELECT data FROM papers ORDER BY saved_at DESC")]
        return sorted(papers, key=lambda paper: paper["date"] or "", reverse=True)

    def save(self, source: str, doi: str) -> tuple[dict | None, bool]:
        with closing(self.connect()) as db:
            existing = db.execute("SELECT data FROM papers WHERE doi = ?", (doi,)).fetchone()
        if existing:
            return json.loads(existing[0]), False
        try:
            paper = fetch_paper(source, doi)
        except HTTPError as error:
            if error.code == 404:
                return None, False
            raise
        if paper is None:
            return None, False
        paper["saved_at"] = datetime.now(KST).isoformat(timespec="seconds")
        with closing(self.connect()) as db, db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO papers VALUES (?, ?, ?)",
                (doi, paper["saved_at"], json.dumps(paper, ensure_ascii=False)),
            )
            if inserted.rowcount == 0:
                existing = db.execute("SELECT data FROM papers WHERE doi = ?", (doi,)).fetchone()
                return json.loads(existing[0]), False
        return paper, True
