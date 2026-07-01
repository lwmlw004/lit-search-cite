#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture literature metadata from web pages, saved HTML, or copied text.

The capture pipeline is intentionally standard-library only:
HTML meta tags / JSON-LD / DOI regex / PubMed and arXiv page cues ->
best-effort metadata enrichment -> BibTeX, RIS, CSV, Markdown, JSON.

Examples:
    python scripts/web-capture.py --url "https://example.com/article"
    python scripts/web-capture.py --html page.html --out references/captured
    python scripts/web-capture.py --text copied.txt --format bibtex,ris,csv,md
    python scripts/web-capture.py --url "https://pubmed.ncbi.nlm.nih.gov/123/" --pdf legal
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

USER_AGENT = "lit-search-cite-web-capture/1.0 (+https://github.com/luffysolution-svg/lit-search-cite)"
DEFAULT_TIMEOUT = 20
DEFAULT_FORMATS = ("bibtex", "ris", "csv", "md", "json")
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9%]+", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:\s*)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
CONFIG_FILE = Path.home() / ".lit-search-cite" / "config.json"

SCHEMA_FIELDS = [
    "title",
    "authors",
    "year",
    "journal",
    "volume",
    "issue",
    "pages",
    "doi",
    "url",
    "pdf_url",
    "pdf_path",
    "pdf_error",
    "oa_status",
    "license",
    "source_page",
    "metadata_source",
    "abstract",
    "keywords",
    "citation_count",
    "journal_rank",
    "confidence",
]


def log(message: str, verbose: bool = False) -> None:
    if verbose:
        print(message, file=sys.stderr)


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_filename(value: str, fallback: str = "paper") -> str:
    value = html.unescape(value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", "_", value)
    value = value.strip("._ ")
    return (value[:150] or fallback)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    out = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, dict):
            name = item.get("name") or " ".join(
                part for part in [item.get("givenName"), item.get("familyName")] if part
            )
            if name:
                out.append(clean_text(str(name)))
        else:
            text = clean_text(str(item))
            if text:
                out.append(text)
    return out


def first(value: Any, default: str = "") -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else default
    if value is None:
        return default
    return str(value).strip()


def extract_year(value: Any) -> str:
    text = first(value)
    match = re.search(r"(18|19|20|21)\d{2}", text)
    return match.group(0) if match else ""


def normalize_doi(doi: str) -> str:
    if not doi:
        return ""
    d = html.unescape(doi)
    d = urllib.parse.unquote(d)
    d = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", d, flags=re.IGNORECASE)
    d = re.sub(r"^doi:\s*", "", d, flags=re.IGNORECASE)
    d = d.strip().strip(" \t\r\n\"'<>")
    d = re.sub(r"[\]\[{}]+$", "", d)
    d = d.rstrip(".,;:")
    while d.endswith(")") and d.count("(") < d.count(")"):
        d = d[:-1]
    while d.endswith(".") or d.endswith(",") or d.endswith(";"):
        d = d[:-1]
    return d.lower()


def extract_dois(text: str, unique: bool = True) -> list[str]:
    seen = set()
    dois = []
    for match in DOI_RE.finditer(html.unescape(text or "")):
        doi = normalize_doi(match.group(0))
        if not doi:
            continue
        if unique and doi in seen:
            continue
        seen.add(doi)
        dois.append(doi)
    return dois


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def looks_like_pdf_url(url: str) -> bool:
    if not url:
        return False
    parsed = urllib.parse.urlparse(html.unescape(url).strip())
    path = parsed.path.lower()
    query = parsed.query.lower()
    return path.endswith(".pdf") or "/pdf" in path or "pdf" in query


def is_safe_pdf_url(url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlparse(html.unescape(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "unsupported URL scheme"
    host = parsed.netloc.lower()
    blocked = ("sci-hub", "libgen", "anna", "annas-archive", "z-lib", "zlibrary")
    if any(token in host for token in blocked):
        return False, "blocked non-authorized source"
    return True, ""


def relative_to_run(path: Path, run_dir: Path) -> str:
    try:
        return path.relative_to(run_dir).as_posix()
    except ValueError:
        return path.as_posix()


def short_journal(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    if not words:
        return "journal"
    return "".join(word[:8] for word in words[:3])


def pdf_filename(article: dict[str, Any]) -> str:
    first_author = "paper"
    if article.get("authors"):
        first_author = re.sub(r"[^A-Za-z0-9]+", "", article["authors"][0].split()[-1]) or "paper"
    year = re.sub(r"[^0-9]+", "", article.get("year") or "")[:4] or "noyear"
    journal = short_journal(article.get("journal") or "")
    doi_or_title = article.get("doi") or article.get("title") or article.get("arxiv_id") or "paper"
    if not (article.get("authors") and article.get("year") and article.get("journal")):
        digest = hashlib.sha1(doi_or_title.encode("utf-8", errors="ignore")).hexdigest()[:10]
        doi_safe = safe_filename(doi_or_title, digest)
        return f"{doi_safe}_{digest}.pdf"
    doi_safe = safe_filename(doi_or_title, "doi")
    return safe_filename(f"{first_author}_{year}_{journal}_{doi_safe}", "paper")[:180] + ".pdf"


def article_template(**overrides: Any) -> dict[str, Any]:
    article: dict[str, Any] = {
        "title": "",
        "authors": [],
        "year": "",
        "journal": "",
        "volume": "",
        "issue": "",
        "pages": "",
        "doi": "",
        "url": "",
        "pdf_url": "",
        "pdf_path": "",
        "pdf_error": "",
        "oa_status": "",
        "license": "",
        "source_page": "",
        "metadata_source": "",
        "abstract": "",
        "keywords": [],
        "citation_count": None,
        "journal_rank": {},
        "confidence": 0.0,
        "pmid": "",
        "arxiv_id": "",
        "pdf_status": "not_requested",
        "pdf_source": "",
        "pdf_file": "",
        "pdf_candidates": [],
        "notes": [],
    }
    article.update(overrides)
    for key in ("title", "year", "journal", "volume", "issue", "pages", "abstract", "metadata_source"):
        if isinstance(article.get(key), str):
            article[key] = clean_text(article[key])
    article["doi"] = normalize_doi(first(article.get("doi")))
    article["authors"] = as_list(article.get("authors"))
    article["keywords"] = as_list(article.get("keywords"))
    if not isinstance(article.get("notes"), list):
        article["notes"] = as_list(article.get("notes"))
    return article


class LiteratureHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.jsonld: list[str] = []
        self._capture_script = False
        self._script_chunks: list[str] = []
        self._capture_title = False
        self._title_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "meta":
            self.meta.append(attr)
        elif tag.lower() == "link":
            self.links.append(attr)
        elif tag.lower() == "script" and "ld+json" in attr.get("type", "").lower():
            self._capture_script = True
            self._script_chunks = []
        elif tag.lower() == "title":
            self._capture_title = True
            self._title_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capture_script:
            payload = "".join(self._script_chunks).strip()
            if payload:
                self.jsonld.append(payload)
            self._capture_script = False
        elif tag.lower() == "title" and self._capture_title:
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._capture_script:
            self._script_chunks.append(data)
        elif self._capture_title:
            self._title_chunks.append(data)

    @property
    def title(self) -> str:
        return clean_text(" ".join(self._title_chunks))


def parse_html(content: str) -> LiteratureHTMLParser:
    parser = LiteratureHTMLParser()
    parser.feed(content or "")
    return parser


def meta_values(parser: LiteratureHTMLParser) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for item in parser.meta:
        key = item.get("name") or item.get("property") or item.get("itemprop")
        content = item.get("content", "")
        if not key or not content:
            continue
        values.setdefault(key.lower(), []).append(content.strip())
    return values


def meta_article(parser: LiteratureHTMLParser, source_page: str) -> dict[str, Any] | None:
    values = meta_values(parser)

    def get(*names: str) -> str:
        for name in names:
            if values.get(name.lower()):
                return values[name.lower()][0]
        return ""

    def get_all(*names: str) -> list[str]:
        out: list[str] = []
        for name in names:
            out.extend(values.get(name.lower(), []))
        return out

    title = get("citation_title", "dc.title", "og:title") or parser.title
    doi = get("citation_doi", "prism.doi")
    if not doi:
        for value in get_all("dc.identifier", "citation_id"):
            found = extract_dois(value)
            if found:
                doi = found[0]
                break
    authors = get_all("citation_author", "dc.creator", "article:author")
    journal = get("citation_journal_title", "prism.publicationname", "dc.source")
    year = extract_year(get("citation_publication_date", "dc.date", "prism.publicationdate"))
    first_page = get("citation_firstpage", "prism.startingpage")
    last_page = get("citation_lastpage", "prism.endingpage")
    pages = ""
    if first_page and last_page:
        pages = f"{first_page}-{last_page}"
    elif first_page:
        pages = first_page
    url = get("citation_abstract_html_url", "citation_fulltext_html_url", "og:url") or source_page
    pdf_url = get("citation_pdf_url")
    pmid = get("citation_pmid")
    if not any([title, doi, authors, journal, pmid]):
        return None
    confidence = 0.75
    if doi:
        confidence = 0.88
    return article_template(
        title=title,
        authors=authors,
        year=year,
        journal=journal,
        volume=get("citation_volume", "prism.volume"),
        issue=get("citation_issue", "prism.number"),
        pages=pages,
        doi=doi,
        url=url,
        pdf_url=pdf_url,
        pdf_candidates=[
            {"url": pdf_url, "source": "citation_pdf_url", "license": "", "oa_status": ""}
        ] if pdf_url else [],
        source_page=source_page,
        metadata_source="html-meta",
        confidence=confidence,
        pmid=pmid,
    )


def publisher_pdf_link_candidates(parser: LiteratureHTMLParser, source_page: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for link in parser.links:
        href = link.get("href", "")
        if not href or not looks_like_pdf_url(href):
            continue
        url = urllib.parse.urljoin(source_page, href)
        candidates.append({"url": url, "source": "publisher PDF link", "license": "", "oa_status": ""})
    seen = set()
    deduped = []
    for item in candidates:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        deduped.append(item)
    return deduped


def walk_jsonld(value: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            nodes.extend(walk_jsonld(item))
    elif isinstance(value, dict):
        if "@graph" in value:
            nodes.extend(walk_jsonld(value["@graph"]))
        nodes.append(value)
    return nodes


def jsonld_type_matches(node: dict[str, Any]) -> bool:
    raw_type = node.get("@type") or node.get("type") or ""
    types = [raw_type] if isinstance(raw_type, str) else raw_type
    type_text = " ".join(str(t).lower() for t in types)
    return any(token in type_text for token in ("scholarlyarticle", "article", "creativework"))


def doi_from_identifier(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            doi = doi_from_identifier(item)
            if doi:
                return doi
    elif isinstance(value, dict):
        for key in ("value", "identifier", "@id", "url", "sameAs", "name"):
            doi = doi_from_identifier(value.get(key))
            if doi:
                return doi
    else:
        found = extract_dois(str(value))
        if found:
            return found[0]
    return ""


def jsonld_pdf_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, list):
        for item in value:
            urls.extend(jsonld_pdf_urls(item))
    elif isinstance(value, dict):
        for key in ("contentUrl", "url", "@id"):
            raw = value.get(key)
            if isinstance(raw, str) and looks_like_pdf_url(raw):
                urls.append(raw)
        for key in ("encoding", "associatedMedia", "hasPart", "mainEntity"):
            urls.extend(jsonld_pdf_urls(value.get(key)))
    elif isinstance(value, str) and looks_like_pdf_url(value):
        urls.append(value)
    return list(dict.fromkeys(urls))


def jsonld_articles(parser: LiteratureHTMLParser, source_page: str) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    for payload in parser.jsonld:
        try:
            data = json.loads(html.unescape(payload))
        except json.JSONDecodeError:
            continue
        for node in walk_jsonld(data):
            if not jsonld_type_matches(node):
                continue
            part_of = node.get("isPartOf") or node.get("partOf") or {}
            if isinstance(part_of, list):
                part_of = part_of[0] if part_of else {}
            journal = ""
            if isinstance(part_of, dict):
                journal = first(part_of.get("name")) or first(part_of.get("headline"))
            else:
                journal = first(part_of)
            identifiers = [
                node.get("identifier"),
                node.get("sameAs"),
                node.get("url"),
                node.get("@id"),
            ]
            doi = ""
            for item in identifiers:
                doi = doi_from_identifier(item)
                if doi:
                    break
            title = first(node.get("headline")) or first(node.get("name"))
            if not any([title, doi, node.get("author")]):
                continue
            pdf_urls = jsonld_pdf_urls(node)
            articles.append(
                article_template(
                    title=title,
                    authors=as_list(node.get("author")),
                    year=extract_year(node.get("datePublished") or node.get("dateCreated")),
                    journal=journal,
                    doi=doi,
                    url=first(node.get("url") or node.get("@id")) or source_page,
                    pdf_url=first(pdf_urls),
                    pdf_candidates=[
                        {"url": url, "source": "JSON-LD PDF", "license": "", "oa_status": ""}
                        for url in pdf_urls
                    ],
                    source_page=source_page,
                    metadata_source="json-ld",
                    abstract=clean_text(first(node.get("description") or node.get("abstract"))),
                    keywords=as_list(node.get("keywords")),
                    confidence=0.82 if doi else 0.68,
                )
            )
    return articles


def extract_pubmed_id(text: str, source_page: str) -> str:
    for candidate in [source_page, text]:
        match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", candidate or "", re.IGNORECASE)
        if match:
            return match.group(1)
    match = re.search(r"\bPMID\s*:?\s*(\d{5,12})\b", text or "", re.IGNORECASE)
    return match.group(1) if match else ""


def extract_arxiv_id(text: str, source_page: str) -> str:
    for candidate in [source_page, text]:
        match = ARXIV_RE.search(candidate or "")
        if match:
            return match.group(1)
    return ""


def build_initial_candidates(content: str, source_page: str, is_html: bool) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    text = clean_text(content) if is_html else html.unescape(content or "")
    parser = parse_html(content) if is_html else None

    if parser:
        meta = meta_article(parser, source_page)
        if meta:
            candidates.append(meta)
        candidates.extend(jsonld_articles(parser, source_page))
        publisher_pdfs = publisher_pdf_link_candidates(parser, source_page)
        if publisher_pdfs:
            if candidates:
                candidates[0]["pdf_candidates"] = list(candidates[0].get("pdf_candidates") or []) + publisher_pdfs
                if not candidates[0].get("pdf_url"):
                    candidates[0]["pdf_url"] = publisher_pdfs[0]["url"]
            else:
                candidates.append(
                    article_template(
                        pdf_url=publisher_pdfs[0]["url"],
                        pdf_candidates=publisher_pdfs,
                        source_page=source_page,
                        metadata_source="publisher-pdf-link",
                        confidence=0.3,
                    )
                )

    pmid = extract_pubmed_id(content, source_page)
    if pmid and not any(c.get("pmid") == pmid for c in candidates):
        candidates.append(
            article_template(
                pmid=pmid,
                source_page=source_page,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                metadata_source="pubmed-page",
                confidence=0.55,
            )
        )

    arxiv_id = extract_arxiv_id(content, source_page)
    if arxiv_id and not any(c.get("arxiv_id") == arxiv_id for c in candidates):
        arxiv_base = arxiv_id.split("v")[0]
        candidates.append(
            article_template(
                arxiv_id=arxiv_base,
                journal=f"arXiv ({arxiv_base})",
                url=f"https://arxiv.org/abs/{arxiv_base}",
                pdf_url=f"https://arxiv.org/pdf/{arxiv_base}",
                source_page=source_page,
                metadata_source="arxiv-page",
                confidence=0.65,
            )
        )

    for doi in extract_dois(content if is_html else text, unique=False):
        candidates.append(
            article_template(
                doi=doi,
                url=f"https://doi.org/{doi}",
                source_page=source_page,
                metadata_source="doi-regex",
                confidence=0.55,
            )
        )

    if not candidates and text:
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = first_line[:240]
        if title:
            candidates.append(
                article_template(
                    title=title,
                    source_page=source_page,
                    metadata_source="plain-text",
                    confidence=0.25,
                    notes=["No DOI found; title-based enrichment attempted."],
                )
            )
    return candidates


def request_bytes(url: str, timeout: int, retries: int = 2, verbose: bool = False) -> bytes | None:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - clear CLI diagnostics matter more here.
            last_error = str(exc)
            log(f"[request] {url} failed on attempt {attempt + 1}: {last_error}", verbose)
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
    return None


def request_text(url: str, timeout: int = DEFAULT_TIMEOUT, retries: int = 2, verbose: bool = False) -> str | None:
    payload = request_bytes(url, timeout=timeout, retries=retries, verbose=verbose)
    if payload is None:
        return None
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return payload.decode(enc)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def request_json(url: str, timeout: int = DEFAULT_TIMEOUT, retries: int = 2, verbose: bool = False) -> Any:
    text = request_text(url, timeout=timeout, retries=retries, verbose=verbose)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def crossref_to_article(item: dict[str, Any]) -> dict[str, Any]:
    titles = item.get("title") or []
    container = item.get("container-title") or []
    authors = []
    for author in item.get("author") or []:
        name = " ".join(part for part in [author.get("given"), author.get("family")] if part)
        if name:
            authors.append(name)
    date_parts = (
        item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or item.get("published", {}).get("date-parts")
        or [[None]]
    )
    year = str(date_parts[0][0]) if date_parts and date_parts[0] and date_parts[0][0] else ""
    return article_template(
        title=first(titles),
        authors=authors,
        year=year,
        journal=first(container),
        volume=first(item.get("volume")),
        issue=first(item.get("issue")),
        pages=first(item.get("page")),
        doi=item.get("DOI", ""),
        url=item.get("URL", ""),
        metadata_source="crossref",
        abstract=clean_text(first(item.get("abstract"))),
        keywords=as_list(item.get("subject")),
        citation_count=item.get("is-referenced-by-count"),
        confidence=0.95 if item.get("DOI") else 0.7,
    )


def query_crossref_by_doi(doi: str, verbose: bool = False) -> dict[str, Any] | None:
    encoded = urllib.parse.quote(doi, safe="")
    url = f"https://api.crossref.org/works/{encoded}?mailto=lit-search-cite@opencode.ai"
    data = request_json(url, verbose=verbose)
    item = (data or {}).get("message")
    if isinstance(item, dict) and item.get("title"):
        return crossref_to_article(item)
    return None


def query_crossref_by_title(title: str, verbose: bool = False) -> dict[str, Any] | None:
    if not title:
        return None
    query = urllib.parse.quote(title)
    url = (
        "https://api.crossref.org/works"
        f"?query.title={query}&rows=1&sort=relevance&mailto=lit-search-cite@opencode.ai"
    )
    data = request_json(url, verbose=verbose)
    items = ((data or {}).get("message") or {}).get("items") or []
    if items:
        article = crossref_to_article(items[0])
        article["metadata_source"] = "crossref-title"
        article["confidence"] = 0.72
        return article
    return None


def openalex_to_article(work: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for item in work.get("authorships") or []:
        name = ((item.get("author") or {}).get("display_name") or "").strip()
        if name:
            authors.append(name)
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    biblio = work.get("biblio") or {}
    open_access = work.get("open_access") or {}
    best_oa = work.get("best_oa_location") or {}
    pdf_url = best_oa.get("pdf_url") or primary.get("pdf_url") or ""
    if not pdf_url and str(open_access.get("oa_url", "")).lower().endswith(".pdf"):
        pdf_url = open_access.get("oa_url", "")
    license_value = best_oa.get("license") or primary.get("license") or ""
    oa_status = open_access.get("oa_status") or ("oa" if open_access.get("is_oa") else "")
    return article_template(
        title=work.get("title", ""),
        authors=authors,
        year=str(work.get("publication_year") or ""),
        journal=source.get("display_name", ""),
        volume=first(biblio.get("volume")),
        issue=first(biblio.get("issue")),
        pages=first(biblio.get("first_page"))
        + (f"-{biblio.get('last_page')}" if biblio.get("last_page") else ""),
        doi=work.get("doi", ""),
        url=work.get("doi") or work.get("id", ""),
        pdf_url=pdf_url,
        pdf_candidates=[
            {"url": pdf_url, "source": "OpenAlex OA location", "license": license_value, "oa_status": oa_status}
        ] if pdf_url else [],
        metadata_source="openalex",
        abstract=invert_openalex_abstract(work.get("abstract_inverted_index")),
        citation_count=work.get("cited_by_count"),
        oa_status=oa_status,
        license=license_value,
        confidence=0.9 if work.get("doi") else 0.68,
    )


def invert_openalex_abstract(index: Any) -> str:
    if not isinstance(index, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in index.items():
        for idx in indexes:
            positions[int(idx)] = word
    return " ".join(positions[i] for i in sorted(positions))


def query_openalex_by_doi(doi: str, verbose: bool = False) -> dict[str, Any] | None:
    doi_url = "https://doi.org/" + doi
    encoded = urllib.parse.quote(doi_url, safe=":/")
    url = (
        f"https://api.openalex.org/works/{encoded}"
        "?mailto=lit-search-cite@opencode.ai"
    )
    data = request_json(url, verbose=verbose)
    if isinstance(data, dict) and data.get("title"):
        return openalex_to_article(data)
    return None


def query_openalex_by_title(title: str, verbose: bool = False) -> dict[str, Any] | None:
    if not title:
        return None
    query = urllib.parse.quote(title)
    url = (
        "https://api.openalex.org/works"
        f"?search={query}&per-page=1&sort=cited_by_count:desc"
        "&select=id,doi,title,publication_year,cited_by_count,authorships,primary_location,"
        "open_access,best_oa_location,biblio,abstract_inverted_index"
        "&mailto=lit-search-cite@opencode.ai"
    )
    data = request_json(url, verbose=verbose)
    results = (data or {}).get("results") or []
    if results:
        article = openalex_to_article(results[0])
        article["metadata_source"] = "openalex-title"
        article["confidence"] = 0.68
        return article
    return None


def query_pubmed_by_pmid(pmid: str, verbose: bool = False) -> dict[str, Any] | None:
    if not pmid:
        return None
    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={urllib.parse.quote(pmid)}&retmode=xml"
    )
    text = request_text(url, verbose=verbose)
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    article_node = root.find(".//Article")
    if article_node is None:
        return None
    title = "".join(article_node.findtext("ArticleTitle", "") or "")
    journal = article_node.findtext("Journal/Title", "") or article_node.findtext("Journal/ISOAbbreviation", "")
    year = (
        article_node.findtext("ArticleDate/Year", "")
        or article_node.findtext("Journal/JournalIssue/PubDate/Year", "")
        or extract_year(article_node.findtext("Journal/JournalIssue/PubDate/MedlineDate", ""))
    )
    authors = []
    for author in article_node.findall(".//AuthorList/Author"):
        collective = author.findtext("CollectiveName")
        if collective:
            authors.append(collective)
            continue
        name = " ".join(
            part
            for part in [
                author.findtext("ForeName") or author.findtext("Initials"),
                author.findtext("LastName"),
            ]
            if part
        )
        if name:
            authors.append(name)
    doi = ""
    for aid in root.findall(".//ArticleIdList/ArticleId"):
        if (aid.attrib.get("IdType") or "").lower() == "doi":
            doi = aid.text or ""
            break
    abstract = " ".join(t.text or "" for t in article_node.findall(".//Abstract/AbstractText"))
    return article_template(
        title=clean_text(title),
        authors=authors,
        year=year,
        journal=journal,
        volume=article_node.findtext("Journal/JournalIssue/Volume", ""),
        issue=article_node.findtext("Journal/JournalIssue/Issue", ""),
        pages=article_node.findtext("Pagination/MedlinePgn", ""),
        doi=doi,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        metadata_source="pubmed",
        abstract=clean_text(abstract),
        confidence=0.9 if doi else 0.78,
        pmid=pmid,
    )


def query_arxiv_by_id(arxiv_id: str, verbose: bool = False) -> dict[str, Any] | None:
    if not arxiv_id:
        return None
    clean_id = arxiv_id.split("v")[0]
    url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(clean_id)}"
    text = request_text(url, verbose=verbose)
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    title = clean_text(entry.findtext("a:title", "", ns))
    authors = [clean_text(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)]
    year = extract_year(entry.findtext("a:published", "", ns))
    doi = ""
    for link in entry.findall("a:link", ns):
        if link.attrib.get("title") == "doi":
            doi = link.attrib.get("href", "")
    return article_template(
        title=title,
        authors=[a for a in authors if a],
        year=year,
        journal=f"arXiv ({clean_id})",
        doi=doi,
        url=f"https://arxiv.org/abs/{clean_id}",
        pdf_url=f"https://arxiv.org/pdf/{clean_id}",
        source_page=f"https://arxiv.org/abs/{clean_id}",
        metadata_source="arxiv",
        abstract=clean_text(entry.findtext("a:summary", "", ns)),
        confidence=0.86,
        arxiv_id=clean_id,
    )


def merge_article(base: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    if not extra:
        return base
    merged = dict(base)
    for key, value in extra.items():
        if key == "authors":
            if value and (not merged.get(key) or len(value) > len(merged.get(key, []))):
                merged[key] = value
        elif key == "keywords":
            merged[key] = list(dict.fromkeys(as_list(merged.get(key)) + as_list(value)))
        elif key == "notes":
            merged[key] = list(dict.fromkeys(as_list(merged.get(key)) + as_list(value)))
        elif key == "pdf_candidates":
            existing = merged.get(key) if isinstance(merged.get(key), list) else []
            incoming = value if isinstance(value, list) else []
            seen = set()
            candidates = []
            for item in existing + incoming:
                if not isinstance(item, dict):
                    continue
                url = item.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                candidates.append(item)
            merged[key] = candidates
        elif key == "confidence":
            merged[key] = max(float(merged.get(key) or 0), float(value or 0))
        elif key == "metadata_source":
            existing = merged.get(key, "")
            if value and value not in existing.split("+"):
                merged[key] = f"{existing}+{value}" if existing else value
        elif key == "source_page":
            if not merged.get(key):
                merged[key] = value
        elif value not in (None, "", [], {}):
            if not merged.get(key) or key in ("citation_count", "journal_rank"):
                merged[key] = value
    merged["doi"] = normalize_doi(merged.get("doi", ""))
    return merged


def enrich_one(article: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    result = article_template(**article)
    try:
        if result.get("doi"):
            crossref = query_crossref_by_doi(result["doi"], verbose=verbose)
            result = merge_article(result, crossref)
            openalex = query_openalex_by_doi(result["doi"], verbose=verbose)
            result = merge_article(result, openalex)
        if result.get("pmid"):
            result = merge_article(result, query_pubmed_by_pmid(result["pmid"], verbose=verbose))
        if result.get("arxiv_id"):
            result = merge_article(result, query_arxiv_by_id(result["arxiv_id"], verbose=verbose))
        if not result.get("doi") and result.get("title"):
            result = merge_article(result, query_crossref_by_title(result["title"], verbose=verbose))
            if not result.get("doi"):
                result = merge_article(result, query_openalex_by_title(result["title"], verbose=verbose))
    except Exception as exc:  # noqa: BLE001
        result.setdefault("notes", []).append(f"Metadata enrichment failed: {exc}")
    if result.get("doi") and not result.get("url"):
        result["url"] = f"https://doi.org/{result['doi']}"
    return result


def year_in_range(article: dict[str, Any], year_from: int, year_to: int) -> bool:
    year = int(article.get("year") or 0) if str(article.get("year") or "").isdigit() else 0
    if year_from and year and year < year_from:
        return False
    if year_to and year and year > year_to:
        return False
    return True


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def dedupe_articles(articles: list[dict[str, Any]], mode: str = "doi") -> tuple[list[dict[str, Any]], int]:
    seen: dict[str, int] = {}
    output: list[dict[str, Any]] = []
    duplicate_count = 0
    for article in articles:
        doi = normalize_doi(article.get("doi", ""))
        tkey = title_key(article.get("title", ""))
        if mode == "title":
            key = f"title:{tkey}" if tkey else (f"doi:{doi}" if doi else "")
        else:
            key = f"doi:{doi}" if doi else (f"title:{tkey}" if tkey else "")
        if key and key in seen:
            duplicate_count += 1
            idx = seen[key]
            if float(article.get("confidence") or 0) > float(output[idx].get("confidence") or 0):
                output[idx] = merge_article(output[idx], article)
            else:
                output[idx] = merge_article(article, output[idx])
            continue
        if key:
            seen[key] = len(output)
        output.append(article)
    return output, duplicate_count


def load_config() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def load_unpaywall_email() -> str:
    cfg = load_config()
    return (
        (cfg.get("api_keys") or {}).get("unpaywall_email")
        or os.environ.get("UNPAYWALL_EMAIL", "")
        or ""
    )


def load_offline_ranks() -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / "references" / "journal-ranks.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_offline_journal_rank(articles: list[dict[str, Any]]) -> None:
    ranks = load_offline_ranks()
    journals = ranks.get("journals") or {}
    aliases = ranks.get("_aliases") or {}
    for article in articles:
        journal = (article.get("journal") or "").strip().lower().lstrip("the ")
        if not journal:
            continue
        key = aliases.get(journal, journal)
        entry = journals.get(key)
        if entry:
            article["journal_rank"] = {
                "source": "offline",
                "tier": entry.get("tier", ""),
                "level": entry.get("level", ""),
                "impact_factor": entry.get("if", ""),
            }


def query_onescholar_rank(journals: list[str], verbose: bool = False) -> dict[str, dict[str, Any]]:
    cfg = load_config()
    key = (cfg.get("api_keys") or {}).get("onescholar") or os.environ.get("ONESCHOLAR_API_KEY", "")
    if not key or not key.startswith("sk_"):
        return {}
    results: dict[str, dict[str, Any]] = {}
    for start in range(0, len(journals), 5):
        batch = journals[start : start + 5]
        body = json.dumps([{"journal": [j]} for j in batch], ensure_ascii=False).encode("utf-8")
        try:
            req = urllib.request.Request(
                "https://api.scigreat.com/info/getrank",
                data=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            for item in data.get("results") or []:
                query = ((item.get("query") or {}).get("journal") or [""])[0]
                d = item.get("data") or {}
                if query and d:
                    results[query.strip().lower()] = {
                        "source": "onescholar",
                        "impact_factor": d.get("imf", ""),
                        "jcr": d.get("jcr", ""),
                        "cas": d.get("cas", ""),
                        "cas_top": d.get("cas_top", ""),
                        "citescore": d.get("citescore", ""),
                    }
        except Exception as exc:  # noqa: BLE001
            log(f"[OneScholar] ranking failed: {exc}", verbose)
    return results


def apply_online_journal_rank(articles: list[dict[str, Any]], verbose: bool = False) -> None:
    journals = sorted({a.get("journal", "") for a in articles if a.get("journal")})
    ranks = query_onescholar_rank(journals[:20], verbose=verbose)
    for article in articles:
        rank = ranks.get((article.get("journal") or "").strip().lower())
        if rank:
            article["journal_rank"] = rank


def unpaywall_pdf_candidates(doi: str, email: str, verbose: bool = False) -> list[dict[str, str]]:
    if not doi or not email:
        return []
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
    data = request_json(url, timeout=15, verbose=verbose)
    candidates: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return candidates
    oa_status = data.get("oa_status", "")
    for loc in [data.get("best_oa_location") or {}] + (data.get("oa_locations") or []):
        pdf = loc.get("url_for_pdf") or ""
        if pdf:
            candidates.append({
                "url": pdf,
                "source": "Unpaywall",
                "license": loc.get("license") or "",
                "oa_status": oa_status,
            })
    return dedupe_pdf_candidates(candidates)


def openalex_pdf_candidates(doi: str, verbose: bool = False) -> list[dict[str, str]]:
    work = query_openalex_by_doi(doi, verbose=verbose)
    if work and work.get("pdf_url"):
        return [{
            "url": work["pdf_url"],
            "source": "OpenAlex OA location",
            "license": work.get("license", ""),
            "oa_status": work.get("oa_status", ""),
        }]
    return []


def europepmc_pdf_candidates(doi: str, verbose: bool = False) -> list[dict[str, str]]:
    if not doi:
        return []
    query = urllib.parse.quote(f"DOI:{doi}")
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={query}&resultType=core&format=json&pageSize=3"
    )
    data = request_json(url, timeout=15, verbose=verbose)
    candidates: list[dict[str, str]] = []
    for item in (((data or {}).get("resultList") or {}).get("result") or []):
        if item.get("isOpenAccess") == "Y" and item.get("pmcid"):
            candidates.append({
                "url": f"https://europepmc.org/articles/{item['pmcid']}/pdf",
                "source": f"EuropePMC {item['pmcid']}",
                "license": item.get("license") or "",
                "oa_status": "oa",
            })
    return dedupe_pdf_candidates(candidates)


def dedupe_pdf_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped = []
    seen = set()
    for item in candidates:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return deduped


def legal_pdf_candidates(article: dict[str, Any], unpaywall_email: str, verbose: bool = False) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    candidates.extend(article.get("pdf_candidates") or [])
    if article.get("pdf_url"):
        source = "arXiv" if article.get("arxiv_id") else "publisher-provided PDF link"
        candidates.append({
            "url": article["pdf_url"],
            "source": source,
            "license": article.get("license", ""),
            "oa_status": article.get("oa_status", ""),
        })
    if article.get("arxiv_id"):
        candidates.append({
            "url": f"https://arxiv.org/pdf/{article['arxiv_id']}",
            "source": "arXiv",
            "license": article.get("license", ""),
            "oa_status": article.get("oa_status", "green"),
        })
    doi = article.get("doi", "")
    if doi:
        candidates.extend(europepmc_pdf_candidates(doi, verbose=verbose))
        candidates.extend(openalex_pdf_candidates(doi, verbose=verbose))
        candidates.extend(unpaywall_pdf_candidates(doi, unpaywall_email, verbose=verbose))
    return dedupe_pdf_candidates(candidates)


def pdf_candidate_priority(item: dict[str, str]) -> int:
    source = (item.get("source") or "").lower()
    if "citation_pdf_url" in source:
        return 10
    if "json-ld" in source:
        return 20
    if "arxiv" in source:
        return 30
    if "europepmc" in source or "pubmed central" in source:
        return 40
    if "openalex" in source:
        return 50
    if "unpaywall" in source:
        return 60
    if "publisher" in source:
        return 70
    return 90


def download_pdf(
    candidate: dict[str, str],
    article: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    verbose: bool = False,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    url = candidate.get("url", "")
    is_safe, reason = is_safe_pdf_url(url)
    if not is_safe:
        return {"status": "skipped_unsafe_url", "path": "", "error": reason}
    path = output_dir / pdf_filename(article)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            data = resp.read()
        is_pdf = "application/pdf" in content_type or data.startswith(b"%PDF")
        if not is_pdf and not (looks_like_pdf_url(url) and data.startswith(b"%PDF")):
            return {
                "status": "skipped_non_pdf",
                "path": "",
                "error": f"URL did not return PDF content ({content_type or 'unknown'})",
            }
        path.write_bytes(data)
        return {"status": "downloaded", "path": relative_to_run(path, run_dir), "error": ""}
    except Exception as exc:  # noqa: BLE001
        log(f"[PDF] download failed from {url}: {exc}", verbose)
        return {"status": "found_url_download_failed", "path": "", "error": str(exc)}


def fetch_legal_pdfs(articles: list[dict[str, Any]], run_dir: Path, verbose: bool = False) -> None:
    email = load_unpaywall_email()
    pdf_dir = run_dir / "pdfs"
    for article in articles:
        article["pdf_status"] = "not_found_or_paywalled"
        article["pdf_error"] = ""
        candidates = legal_pdf_candidates(article, email, verbose=verbose)
        candidates.sort(key=pdf_candidate_priority)
        if not candidates:
            article["pdf_url"] = article.get("pdf_url", "")
            continue
        for candidate in candidates:
            article["pdf_url"] = candidate.get("url", "")
            article["pdf_source"] = candidate.get("source", "")
            if candidate.get("license"):
                article["license"] = candidate["license"]
            if candidate.get("oa_status"):
                article["oa_status"] = candidate["oa_status"]
            result = download_pdf(candidate, article, pdf_dir, run_dir, verbose=verbose)
            article["pdf_status"] = result["status"]
            article["pdf_error"] = result["error"]
            if result["path"]:
                article["pdf_path"] = result["path"]
                article["pdf_file"] = str(run_dir / result["path"])
            if result["status"] == "downloaded":
                break


def parse_formats(value: str) -> set[str]:
    aliases = {
        "bib": "bibtex",
        "bibtex": "bibtex",
        "ris": "ris",
        "csv": "csv",
        "md": "md",
        "markdown": "md",
        "json": "json",
        "all": "all",
    }
    selected: set[str] = set()
    for raw in re.split(r"[,;\s]+", value or ""):
        if not raw:
            continue
        mapped = aliases.get(raw.strip().lower())
        if not mapped:
            raise ValueError(f"Unsupported format: {raw}")
        if mapped == "all":
            return set(DEFAULT_FORMATS)
        selected.add(mapped)
    return selected or set(DEFAULT_FORMATS)


def bibtex_escape(value: Any) -> str:
    text = first(value)
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def citation_key(article: dict[str, Any], index: int) -> str:
    author = "paper"
    if article.get("authors"):
        author = re.sub(r"[^A-Za-z0-9]+", "", article["authors"][0].split()[-1]) or "paper"
    year = article.get("year") or "noyear"
    title_word = ""
    if article.get("title"):
        words = re.findall(r"[A-Za-z0-9]+", article["title"])
        title_word = words[0] if words else ""
    return f"{author}{year}{title_word or index}".lower()


def write_bibtex(articles: list[dict[str, Any]], path: Path) -> None:
    entries = []
    for idx, article in enumerate(articles, 1):
        entry_type = "article" if article.get("journal") and "arxiv" not in article.get("journal", "").lower() else "misc"
        fields = {
            "title": article.get("title"),
            "author": " and ".join(article.get("authors") or []),
            "journal": article.get("journal"),
            "year": article.get("year"),
            "volume": article.get("volume"),
            "number": article.get("issue"),
            "pages": article.get("pages"),
            "doi": article.get("doi"),
            "url": article.get("url") or article.get("source_page"),
            "abstract": article.get("abstract"),
        }
        body = []
        for key, value in fields.items():
            if value not in (None, "", [], {}):
                body.append(f"  {key} = {{{bibtex_escape(value)}}}")
        entries.append(f"@{entry_type}{{{citation_key(article, idx)},\n" + ",\n".join(body) + "\n}")
    path.write_text("\n\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")


def write_ris(articles: list[dict[str, Any]], path: Path) -> None:
    lines: list[str] = []
    for article in articles:
        lines.append("TY  - JOUR" if article.get("journal") else "TY  - GEN")
        if article.get("title"):
            lines.append(f"T1  - {article['title']}")
        for author in article.get("authors") or []:
            lines.append(f"AU  - {author}")
        if article.get("journal"):
            lines.append(f"JO  - {article['journal']}")
        if article.get("year"):
            lines.append(f"PY  - {article['year']}")
        if article.get("volume"):
            lines.append(f"VL  - {article['volume']}")
        if article.get("issue"):
            lines.append(f"IS  - {article['issue']}")
        if article.get("pages"):
            lines.append(f"SP  - {article['pages']}")
        if article.get("doi"):
            lines.append(f"DO  - {article['doi']}")
        if article.get("url") or article.get("source_page"):
            lines.append(f"UR  - {article.get('url') or article.get('source_page')}")
        if article.get("abstract"):
            lines.append(f"AB  - {article['abstract']}")
        lines.append("ER  -")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(articles: list[dict[str, Any]], path: Path) -> None:
    extra_fields = ["pmid", "arxiv_id", "pdf_source", "pdf_file", "pdf_candidates", "notes"]
    fields = SCHEMA_FIELDS + extra_fields
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for article in articles:
            row = {}
            for field in fields:
                value = article.get(field)
                if isinstance(value, (list, dict)):
                    row[field] = json.dumps(value, ensure_ascii=False)
                else:
                    row[field] = value
            writer.writerow(row)


def write_markdown(articles: list[dict[str, Any]], path: Path) -> None:
    lines = ["# Captured Literature", ""]
    for idx, article in enumerate(articles, 1):
        lines.append(f"## {idx}. {article.get('title') or '(untitled)'}")
        lines.append(f"- Authors: {'; '.join(article.get('authors') or [])}")
        lines.append(f"- Journal: {article.get('journal') or ''}")
        lines.append(f"- Year: {article.get('year') or ''}")
        lines.append(f"- DOI: {article.get('doi') or ''}")
        lines.append(f"- URL: {article.get('url') or article.get('source_page') or ''}")
        lines.append(f"- PDF: {article.get('pdf_path') or article.get('pdf_url') or 'not found or paywalled'}")
        lines.append(f"- PDF status: {article.get('pdf_status') or ''}")
        lines.append(f"- PDF local path: {article.get('pdf_path') or ''}")
        lines.append(f"- PDF source: {article.get('pdf_source') or ''}")
        lines.append(f"- OA status: {article.get('oa_status') or ''}")
        lines.append(f"- License: {article.get('license') or ''}")
        lines.append(f"- Metadata source: {article.get('metadata_source') or ''}")
        notes = "; ".join(article.get("notes") or [])
        if float(article.get("confidence") or 0) < 0.6:
            notes = (notes + "; " if notes else "") + "Low confidence: manual verification recommended."
        lines.append(f"- Notes: {notes}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_json(articles: list[dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")


def write_pdf_manifest(articles: list[dict[str, Any]], run_dir: Path) -> None:
    items = []
    for article in articles:
        items.append({
            "title": article.get("title", ""),
            "doi": article.get("doi", ""),
            "pdf_status": article.get("pdf_status", ""),
            "pdf_source": article.get("pdf_source", ""),
            "pdf_url": article.get("pdf_url", ""),
            "pdf_path": article.get("pdf_path", ""),
            "license": article.get("license", ""),
            "oa_status": article.get("oa_status", ""),
        })
    manifest = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "total_articles": len(articles),
        "downloaded": sum(1 for item in items if item["pdf_status"] == "downloaded"),
        "failed": sum(1 for item in items if item["pdf_status"] != "downloaded"),
        "items": items,
    }
    (run_dir / "pdf_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_onefind_index(articles: list[dict[str, Any]], run_dir: Path) -> None:
    lines = ["# OneFind Literature Index", ""]
    for idx, article in enumerate(articles, 1):
        lines.append(f"## Article {idx}: {article.get('title') or '(untitled)'}")
        lines.append(f"- DOI: {article.get('doi') or ''}")
        lines.append(f"- Year: {article.get('year') or ''}")
        lines.append(f"- Journal: {article.get('journal') or ''}")
        lines.append(f"- Authors: {'; '.join(article.get('authors') or [])}")
        lines.append(f"- Local PDF: {article.get('pdf_path') or ''}")
        lines.append(f"- Source URL: {article.get('url') or article.get('source_page') or ''}")
        lines.append(f"- Abstract: {article.get('abstract') or ''}")
        lines.append(f"- Keywords: {'; '.join(article.get('keywords') or [])}")
        notes = "; ".join(article.get("notes") or [])
        if article.get("pdf_status") and article.get("pdf_status") != "downloaded":
            notes = (notes + "; " if notes else "") + f"PDF status: {article.get('pdf_status')}"
        lines.append(f"- Notes: {notes}")
        lines.append("")
    (run_dir / "onefind_index.md").write_text("\n".join(lines), encoding="utf-8")


def write_zotero_import_guide(run_dir: Path) -> None:
    lines = [
        "# Zotero / EndNote Import Guide",
        "",
        "## Import BibTeX Into Zotero",
        "",
        "1. Open Zotero.",
        "2. Choose `File` -> `Import...`.",
        "3. Select `captured.bib` from this capture run.",
        "4. Review imported metadata and merge duplicates if Zotero detects any.",
        "",
        "## Import RIS Into Zotero Or EndNote",
        "",
        "1. Choose the import command in Zotero or EndNote.",
        "2. Select `captured.ris`.",
        "3. Confirm that DOI, title, journal, year, and authors look correct.",
        "",
        "## Add Local PDFs",
        "",
        "Drag files from the `pdfs/` folder into Zotero, or attach each PDF to the matching item.",
        "If Zotero does not automatically associate a PDF, search within Zotero by DOI or title, then attach the file manually.",
        "",
        "## Access Boundary",
        "",
        "This project only attempts legal open-access PDFs. It does not bypass paywalls and does not use Sci-Hub, LibGen, Anna's Archive, or other unauthorized mirrors.",
    ]
    (run_dir / "zotero_import_guide.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_control_files(
    articles: list[dict[str, Any]],
    run_dir: Path,
    report: dict[str, Any],
) -> None:
    dois = [article.get("doi", "") for article in articles if article.get("doi")]
    (run_dir / "dois.txt").write_text("\n".join(dois) + ("\n" if dois else ""), encoding="utf-8")

    failed = []
    for article in articles:
        if article.get("notes"):
            failed.append(f"- {article.get('title') or article.get('doi') or '(untitled)'}: {'; '.join(article['notes'])}")
        elif float(article.get("confidence") or 0) < 0.5:
            failed.append(f"- {article.get('title') or article.get('doi') or '(untitled)'}: low confidence")
    (run_dir / "failed.txt").write_text("\n".join(failed) + ("\n" if failed else ""), encoding="utf-8")

    low_conf = [a for a in articles if float(a.get("confidence") or 0) < 0.6]
    lines = [
        "# Web Capture Run Report",
        "",
        f"- Input source: {report.get('input_source')}",
        f"- Captured records: {report.get('captured_count')}",
        f"- Successfully enriched records: {report.get('enriched_count')}",
        f"- DOI duplicates removed: {report.get('doi_duplicates_removed')}",
        f"- PDF successful records: {report.get('pdf_success_count')}",
        f"- PDF downloaded total: {report.get('pdf_downloaded_total')}",
        f"- Failed/flagged records: {len(failed)}",
        f"- Low-confidence records requiring manual check: {len(low_conf)}",
    ]
    if report.get("input_warning"):
        lines.append(f"- Input warning: {report.get('input_warning')}")
    pdf_status_counts: dict[str, int] = {}
    for article in articles:
        status = article.get("pdf_status") or "unknown"
        pdf_status_counts[status] = pdf_status_counts.get(status, 0) + 1
    if pdf_status_counts:
        lines.append(f"- PDF status counts: {json.dumps(pdf_status_counts, ensure_ascii=False)}")
    pdf_source_counts: dict[str, int] = {}
    pdf_error_counts: dict[str, int] = {}
    for article in articles:
        source = article.get("pdf_source") or "none"
        if article.get("pdf_status") == "downloaded":
            pdf_source_counts[source] = pdf_source_counts.get(source, 0) + 1
        error = article.get("pdf_error") or ""
        if error:
            pdf_error_counts[error] = pdf_error_counts.get(error, 0) + 1
    if pdf_source_counts:
        lines.append(f"- PDF source counts: {json.dumps(pdf_source_counts, ensure_ascii=False)}")
    if pdf_error_counts:
        lines.append(f"- PDF failure reason counts: {json.dumps(pdf_error_counts, ensure_ascii=False)}")
    if any("403" in (article.get("pdf_error") or "") for article in articles):
        lines.append("- 403 note: publisher pages may block command-line fetches; save the browser page as HTML and retry with `--html`.")
    lines.extend(["", "## Low-Confidence Records", ""])
    if low_conf:
        for article in low_conf:
            lines.append(f"- {article.get('title') or article.get('doi') or '(untitled)'}")
    else:
        lines.append("- None")
    manual_check = [
        article for article in articles
        if float(article.get("confidence") or 0) < 0.6
        or article.get("pdf_status") in {"found_url_download_failed", "skipped_non_pdf", "skipped_unsafe_url"}
        or article.get("notes")
    ]
    lines.extend(["", "## Needs Manual Check", ""])
    if manual_check:
        for article in manual_check:
            lines.append(f"- {article.get('title') or article.get('doi') or '(untitled)'} | PDF: {article.get('pdf_status')}")
    else:
        lines.append("- None")
    lines.extend(["", "## Failed or Flagged Records", ""])
    if failed:
        lines.extend(failed)
    else:
        lines.append("- None")
    (run_dir / "run_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(
    articles: list[dict[str, Any]],
    run_dir: Path,
    formats: set[str],
    report: dict[str, Any],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    # The CLI accepts --format for compatibility with user workflows, but each
    # capture run still emits the canonical handoff set requested by the skill.
    _ = formats
    write_json(articles, run_dir / "captured.json")
    write_csv(articles, run_dir / "captured.csv")
    write_bibtex(articles, run_dir / "captured.bib")
    write_ris(articles, run_dir / "captured.ris")
    write_markdown(articles, run_dir / "captured.md")
    write_pdf_manifest(articles, run_dir)
    write_onefind_index(articles, run_dir)
    write_zotero_import_guide(run_dir)
    write_control_files(articles, run_dir, report)


def read_input(args: argparse.Namespace) -> tuple[str, str, bool, str]:
    if args.url:
        content = request_text(args.url, verbose=args.verbose)
        if content is None:
            identifiers = extract_dois(args.url)
            pmid = extract_pubmed_id("", args.url)
            arxiv_id = extract_arxiv_id("", args.url)
            if identifiers or pmid or arxiv_id:
                warning = "URL fetch failed; fell back to DOI/PMID/arXiv identifier parsed from the URL."
                return args.url, args.url, False, warning
            raise RuntimeError(f"Could not fetch URL: {args.url}")
        return content, args.url, True, ""
    if args.html:
        path = Path(args.html)
        return path.read_text(encoding="utf-8", errors="replace"), str(path), True, ""
    if args.text:
        path = Path(args.text)
        return path.read_text(encoding="utf-8", errors="replace"), str(path), False, ""
    raise RuntimeError("Provide exactly one of --url, --html, or --text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture literature metadata from URL, saved HTML, or copied web text."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Input web page URL")
    group.add_argument("--html", help="Input local HTML file")
    group.add_argument("--text", help="Input local plain text file")
    parser.add_argument("--out", default="references/captured", help="Output root directory")
    parser.add_argument(
        "--format",
        default="bibtex,ris,csv,md,json",
        help="Requested formats: bibtex,ris,csv,md,json or all; canonical run files are always written",
    )
    parser.add_argument("--pdf", choices=["none", "legal"], default="none", help="Try legal OA PDF download")
    parser.add_argument("--limit", type=int, default=100, help="Maximum extracted records")
    parser.add_argument("--year-from", type=int, default=0, help="Minimum publication year")
    parser.add_argument("--year-to", type=int, default=0, help="Maximum publication year")
    parser.add_argument("--dedupe", choices=["doi", "title"], default="doi", help="Deduplication strategy")
    parser.add_argument("--domain", default="general", help="Domain hint such as chemistry/biomedicine/cs/materials")
    parser.add_argument("--online-rank", action="store_true", help="Use configured OneScholar ranking when available")
    parser.add_argument("--verbose", action="store_true", help="Print debug information")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        formats = parse_formats(args.format)
    except ValueError as exc:
        parser.error(str(exc))

    content, source_page, is_html, input_warning = read_input(args)
    input_source = args.url or args.html or args.text
    run_dir = Path(args.out) / now_stamp()
    log(f"[input] {input_source}", args.verbose)

    candidates = build_initial_candidates(content, source_page=source_page, is_html=is_html)
    if input_warning:
        for candidate in candidates:
            candidate.setdefault("notes", []).append(input_warning)
    candidates, pre_enrich_duplicates = dedupe_articles(candidates, args.dedupe)
    if args.limit > 0:
        candidates = candidates[: args.limit]
    log(f"[extract] {len(candidates)} candidate(s)", args.verbose)

    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        enriched_article = enrich_one(candidate, verbose=args.verbose)
        enriched.append(enriched_article)

    filtered = [a for a in enriched if year_in_range(a, args.year_from, args.year_to)]
    deduped, post_enrich_duplicates = dedupe_articles(filtered, args.dedupe)
    duplicates = pre_enrich_duplicates + post_enrich_duplicates
    apply_offline_journal_rank(deduped)
    if args.online_rank:
        apply_online_journal_rank(deduped, verbose=args.verbose)
    if args.pdf == "legal":
        fetch_legal_pdfs(deduped, run_dir, verbose=args.verbose)

    enriched_count = sum(1 for a in deduped if a.get("title") and float(a.get("confidence") or 0) >= 0.65)
    pdf_success_count = sum(1 for a in deduped if a.get("pdf_status") == "downloaded")
    report = {
        "input_source": input_source,
        "captured_count": len(deduped),
        "enriched_count": enriched_count,
        "doi_duplicates_removed": duplicates,
        "pdf_success_count": pdf_success_count,
        "pdf_downloaded_total": pdf_success_count,
        "input_warning": input_warning,
    }
    write_outputs(deduped, run_dir, formats, report)

    print(f"Captured {len(deduped)} record(s)")
    print(f"Output: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
