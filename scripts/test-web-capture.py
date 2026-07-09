#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""No-network tests for scripts/web-capture.py.

Usage:
    python scripts/test-web-capture.py
    python scripts/test-web-capture.py --fixtures evals/web-capture
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
WEB_CAPTURE_PATH = ROOT / "scripts" / "web-capture.py"


def load_web_capture():
    spec = importlib.util.spec_from_file_location("web_capture", WEB_CAPTURE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {WEB_CAPTURE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_doi_regex(wc) -> None:
    text = "See DOI: 10.1234/example.2024.001). Also https://doi.org/10.5678/ABC.DEF;"
    dois = wc.extract_dois(text)
    assert_true(dois == ["10.1234/example.2024.001", "10.5678/abc.def"], f"Unexpected DOIs: {dois}")


def test_noisy_reference_dois(wc, fixtures: Path) -> None:
    text = (fixtures / "sample_reference_noise.txt").read_text(encoding="utf-8")
    dois = wc.extract_dois(text)
    assert_true("10.1126/science.abl4322" in dois, "Science DOI missing from noisy text")
    assert_true("10.1007/s11426-026-3403-4" in dois, "SciEngine DOI missing from noisy text")
    assert_true("10.1038/s41586-021-03819-2" in dois, "PubMed DOI missing from noisy text")
    assert_true(all(not d.endswith((".", ")", "）", "。", "；")) for d in dois), f"DOI punctuation leaked: {dois}")


def test_markup_sanitized_for_exports(wc) -> None:
    article = wc.article_template(
        title="A biomimetic S\n <sub>H</sub> 2 and sp <sup>3</sup> title",
        authors=["Alice <b>Zhang</b>"],
        journal="Journal <i>Name</i>",
        doi="10.1234/markup.fixture",
    )
    assert_true(article["title"] == "A biomimetic S H 2 and sp 3 title", f"Title not sanitized: {article['title']}")
    assert_true(article["authors"] == ["Alice Zhang"], f"Author not sanitized: {article['authors']}")
    assert_true(article["journal"] == "Journal Name", f"Journal not sanitized: {article['journal']}")


def test_sub_sup_tags_do_not_insert_spaces(wc) -> None:
    article = wc.article_template(
        title="A biomimetic S<sub>H</sub>2 cross-coupling mechanism for quaternary sp<sup>3</sup>-carbon formation"
    )
    assert_true(
        article["title"] == "A biomimetic SH2 cross-coupling mechanism for quaternary sp3-carbon formation",
        f"Sub/sup tags inserted spaces: {article['title']}",
    )


def test_jats_abstract_cleaning(wc) -> None:
    raw = (
        "<jats:p>A nickel-catalyzed C(sp <jats:sup>3</jats:sup> ) reaction "
        "uses S <jats:sub>H</jats:sub> 2 chemistry &amp; mild conditions.</jats:p>\n"
    )
    cleaned = wc.clean_abstract_text(raw)
    assert_true("<" not in cleaned, f"JATS markup leaked: {cleaned}")
    assert_true("C(sp3)" in cleaned, f"C(sp 3 ) was not normalized: {cleaned}")
    assert_true("SH2" in cleaned, f"S H 2 was not normalized: {cleaned}")
    assert_true("&amp;" not in cleaned and "&" in cleaned, f"HTML entity not decoded: {cleaned}")


def test_arxiv_detection_requires_prefix(wc) -> None:
    assert_true(
        wc.extract_arxiv_id("DOI 10.48550/arXiv.1706.03762", "") == "",
        "arXiv DOI should not become a duplicate arXiv page record",
    )
    assert_true(
        wc.extract_arxiv_id("", "https://arxiv.org/abs/1706.03762") == "1706.03762",
        "arXiv URL was not detected",
    )


def test_meta_extraction(wc, fixtures: Path) -> None:
    html = (fixtures / "sample_publisher_meta.html").read_text(encoding="utf-8")
    articles = wc.build_initial_candidates(html, "sample_publisher_meta.html", True)
    assert_true(articles, "No article extracted from meta fixture")
    first = articles[0]
    assert_true(first["title"] == "Catalytic conversion of captured carbon dioxide", "Meta title mismatch")
    assert_true(first["doi"] == "10.1234/example.2024.001", "Meta DOI mismatch")
    assert_true(first["authors"] == ["Alice Zhang", "Bernard Smith"], "Meta author mismatch")
    assert_true(first["abstract_source"] == "html-meta:citation_abstract", "Citation abstract not preferred")
    assert_true("C(sp3)" in first["abstract"], "Publisher abstract was not cleaned")
    assert_true("nickel catalysis" in first["keywords"], "citation_keywords missing")
    assert_true("single electron transfer" in first["keywords"], "article:tag missing")
    assert_true("alkyl halide" in first["keywords"], "meta keywords missing")


def test_citation_pdf_url_extraction(wc, fixtures: Path) -> None:
    html = (fixtures / "sample_open_pdf_meta.html").read_text(encoding="utf-8")
    articles = wc.build_initial_candidates(html, "https://example.org/article", True)
    first = articles[0]
    assert_true(first["pdf_url"] == "https://example.org/papers/open-fixture.pdf", "citation_pdf_url not extracted")
    candidates = first.get("pdf_candidates") or []
    assert_true(any(c.get("source") == "citation_pdf_url" for c in candidates), "PDF candidate source missing")


def test_jsonld_extraction(wc, fixtures: Path) -> None:
    html = (fixtures / "sample_jsonld_article.html").read_text(encoding="utf-8")
    articles = wc.build_initial_candidates(html, "sample_jsonld_article.html", True)
    match = next((a for a in articles if a["doi"] == "10.5678/jsonld.2023.002"), None)
    assert_true(match is not None, "JSON-LD DOI not extracted")
    assert_true(match["journal"] == "Example AI Chemistry", "JSON-LD journal mismatch")
    assert_true("Carla Nguyen" in match["authors"], "JSON-LD author missing")


def test_jsonld_pdf_extraction(wc, fixtures: Path) -> None:
    html = (fixtures / "sample_arxiv_pdf.html").read_text(encoding="utf-8")
    articles = wc.build_initial_candidates(html, "https://arxiv.org/abs/1706.03762", True)
    assert_true(
        any(a.get("pdf_url") == "https://arxiv.org/pdf/1706.03762" for a in articles),
        "JSON-LD PDF contentUrl not extracted",
    )


def test_openalex_and_unpaywall_fixture_candidates(wc, fixtures: Path) -> None:
    openalex = json.loads((fixtures / "sample_openalex_oa.json").read_text(encoding="utf-8"))
    article = wc.openalex_to_article(openalex)
    assert_true(article["pdf_url"] == "https://example.org/openalex-best.pdf", "OpenAlex best OA PDF missing")
    assert_true(article["oa_status"] == "gold", "OpenAlex OA status missing")
    assert_true(article["abstract"] == "A complete OpenAlex abstract.", "OpenAlex abstract reconstruction failed")
    assert_true("Photoredox catalysis" in article["concepts"], "OpenAlex concept missing")
    unpaywall = json.loads((fixtures / "sample_unpaywall.json").read_text(encoding="utf-8"))
    old_request_json = wc.request_json
    wc.request_json = lambda url, timeout=20, retries=2, verbose=False: unpaywall
    try:
        candidates = wc.unpaywall_pdf_candidates("10.2222/unpaywall.fixture", "test@example.org")
    finally:
        wc.request_json = old_request_json
    assert_true(len(candidates) == 2, f"Unexpected Unpaywall candidates: {candidates}")
    assert_true(candidates[0]["oa_status"] == "green", "Unpaywall OA status missing")


def test_openalex_abstract_reconstruction_is_robust(wc) -> None:
    warnings = []
    abstract = wc.invert_openalex_abstract(
        {
            "Stable": [0],
            "rebuild.": [1],
            "duplicate": [1],
            "broken": ["not-a-position", -1],
            "missing-list": "2",
        },
        warnings,
    )
    assert_true(abstract == "Stable rebuild.", f"Unexpected OpenAlex abstract: {abstract}")
    assert_true(any("duplicate position" in warning for warning in warnings), "Duplicate position warning missing")
    assert_true(any("invalid position" in warning for warning in warnings), "Invalid position warning missing")
    assert_true(any("not a list" in warning for warning in warnings), "Malformed positions warning missing")


def test_abstract_source_priority(wc) -> None:
    crossref = wc.article_template(
        title="A complete article title",
        abstract=") bonds remains a fragment without its missing beginning.",
        abstract_source="crossref",
        metadata_source="crossref",
    )
    openalex = wc.article_template(
        title="A complete article title",
        abstract=(
            "This complete OpenAlex abstract introduces the problem. "
            "It then describes the method and reports the principal result."
        ),
        abstract_source="openalex",
        metadata_source="openalex",
    )
    merged = wc.merge_article(crossref, openalex)
    assert_true(merged["abstract_source"] == "openalex", f"Wrong abstract selected: {merged}")
    assert_true(merged["abstract"].startswith("This complete"), "Complete OpenAlex abstract not selected")
    assert_true(
        any("incomplete fragment" in warning for warning in merged["metadata_warnings"]),
        "Fragment warning was not retained",
    )
    seo = wc.article_template(
        title="A complete article title",
        abstract="Read the full article on the publisher website. " * 20,
        abstract_source="html-meta:og:description",
        metadata_source="html-meta",
    )
    formal = wc.article_template(
        title="A complete article title",
        abstract="A concise formal abstract reports the principal result.",
        abstract_source="crossref",
        metadata_source="crossref",
    )
    preferred = wc.merge_article(seo, formal)
    assert_true(preferred["abstract_source"] == "crossref", "SEO description displaced a formal abstract")


def test_conservative_keyword_and_concept_extraction(wc) -> None:
    article = wc.enrich_article_metadata(
        wc.article_template(
            title="C(sp 3 )-C(sp 3 ) cross-coupling",
            abstract=(
                "Nickel-catalyzed cross-coupling of redox-active esters with alkyl halides "
                "proceeds through single-electron transfer. Biomimetic S H 2 homolytic "
                "substitution with iron porphyrin is also discussed."
            ),
            metadata_source="fixture",
        )
    )
    expected = {
        "nickel catalysis",
        "redox-active ester",
        "alkyl halide",
        "single electron transfer",
        "SH2",
        "homolytic substitution",
        "iron porphyrin",
        "cross-coupling",
        "C(sp3)-C(sp3) cross-coupling",
    }
    assert_true(expected.issubset(set(article["keywords"])), f"Missing keywords: {expected - set(article['keywords'])}")
    assert_true(expected.issubset(set(article["concepts"])), f"Missing concepts: {expected - set(article['concepts'])}")


def test_conservative_keyword_negative_cases(wc) -> None:
    article = wc.enrich_article_metadata(
        wc.article_template(
            title="Analytical control experiment",
            abstract="An acid wash changed catalyst amount, coupling constant, and a set of values.",
            metadata_source="fixture",
        )
    )
    forbidden = {"carboxylic acid", "nickel catalysis", "cross-coupling", "single electron transfer"}
    assert_true(not forbidden.intersection(article["keywords"]), f"False-positive keywords: {article['keywords']}")
    assert_true(not forbidden.intersection(article["concepts"]), f"False-positive concepts: {article['concepts']}")


def test_multi_doi_dedupe(wc, fixtures: Path) -> None:
    text = (fixtures / "sample_reference_list.txt").read_text(encoding="utf-8")
    articles = wc.build_initial_candidates(text, "sample_reference_list.txt", False)
    deduped, duplicate_count = wc.dedupe_articles(articles, "doi")
    assert_true(duplicate_count == 1, f"Expected one duplicate, got {duplicate_count}")
    assert_true(len(deduped) == 3, f"Expected 3 unique DOI records, got {len(deduped)}")


def test_outputs(wc) -> None:
    article = wc.article_template(
        title="Output fixture",
        authors=["Alice Zhang"],
        year="2024",
        journal="Journal of Example Chemistry",
        doi="10.1234/output.fixture",
        source_page="fixture",
        metadata_source="test",
        abstract="A complete fixture abstract about nickel-catalyzed cross-coupling.",
        abstract_source="test-abstract",
        keywords=["nickel catalysis"],
        keywords_source=["test-keywords"],
        concepts=["cross-coupling"],
        concepts_source=["test-concepts"],
        enrichment_sources=["test"],
        metadata_warnings=["fixture warning"],
        confidence=0.9,
        pdf_status="downloaded",
        pdf_source="test PDF",
        pdf_url="https://example.org/output.pdf",
        pdf_path="pdfs/output.pdf",
        oa_status="gold",
        license="cc-by",
    )
    report = {
        "input_source": "fixture",
        "captured_count": 1,
        "enriched_count": 1,
        "doi_duplicates_removed": 0,
        "pdf_success_count": 0,
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        wc.write_outputs([article], out, {"bibtex", "ris", "csv", "md", "json"}, report)
        for name in [
            "captured.bib", "captured.ris", "captured.csv", "captured.md", "captured.json",
            "dois.txt", "failed.txt", "run_report.md", "pdf_manifest.json",
            "onefind_index.md", "zotero_import_guide.md",
        ]:
            assert_true((out / name).exists(), f"Missing output file: {name}")
        assert_true("10.1234/output.fixture" in (out / "captured.bib").read_text(encoding="utf-8"), "BibTeX missing DOI")
        captured_md = (out / "captured.md").read_text(encoding="utf-8")
        assert_true("# Captured Literature" in captured_md, "Markdown heading missing")
        assert_true("PDF status: downloaded" in captured_md, "Markdown missing PDF status")
        assert_true("### Abstract" in captured_md, "Markdown missing Abstract section")
        assert_true("### Keywords" in captured_md, "Markdown missing Keywords section")
        assert_true("### Concepts" in captured_md, "Markdown missing Concepts section")
        captured_json = json.loads((out / "captured.json").read_text(encoding="utf-8"))[0]
        for field in [
            "abstract", "abstract_source", "keywords", "keywords_source", "concepts",
            "concepts_source", "enrichment_sources", "metadata_warnings",
        ]:
            assert_true(field in captured_json, f"captured.json missing {field}")
        manifest = json.loads((out / "pdf_manifest.json").read_text(encoding="utf-8"))
        assert_true(manifest["downloaded"] == 1, "PDF manifest downloaded count wrong")
        onefind = (out / "onefind_index.md").read_text(encoding="utf-8")
        assert_true("Local PDF: pdfs/output.pdf" in onefind, "OneFind index missing local PDF")
        assert_true("Concepts: cross-coupling" in onefind, "OneFind index missing concepts")
        assert_true("PDF status: downloaded" in onefind, "OneFind index missing PDF status")
        assert_true("Source capture dir:" in onefind, "OneFind index missing capture directory")
        run_report = (out / "run_report.md").read_text(encoding="utf-8")
        assert_true("Abstract coverage: 1/1" in run_report, "Run report missing abstract coverage")
        assert_true("Metadata warnings count: 1" in run_report, "Run report missing warning count")
        assert_true("captured.bib" in (out / "zotero_import_guide.md").read_text(encoding="utf-8"), "Zotero guide missing BibTeX instructions")


def test_pdf_filename_cleaning(wc) -> None:
    article = wc.article_template(
        title="Unsafe / title",
        authors=["Jane Doe"],
        year="2024",
        journal="Journal: Of * Tests",
        doi="10.1234/unsafe:path",
    )
    name = wc.pdf_filename(article)
    assert_true(name.endswith(".pdf"), "PDF filename missing extension")
    assert_true(all(ch not in name for ch in '\\/:*?"<>|'), f"Unsafe filename: {name}")


class FakeResponse:
    def __init__(self, data: bytes, content_type: str):
        self._data = data
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._data


def test_non_pdf_response_not_saved(wc) -> None:
    old_urlopen = wc.urllib.request.urlopen
    wc.urllib.request.urlopen = lambda req, timeout=30: FakeResponse(b"<html>not pdf</html>", "text/html")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            result = wc.download_pdf(
                {"url": "https://example.org/not-a-pdf.pdf", "source": "test"},
                wc.article_template(title="Non PDF"),
                run_dir / "pdfs",
                run_dir,
            )
            assert_true(result["status"] == "skipped_non_pdf", f"Expected skipped_non_pdf, got {result}")
            assert_true(not list((run_dir / "pdfs").glob("*.pdf")), "Non-PDF response was saved")
    finally:
        wc.urllib.request.urlopen = old_urlopen


def test_pdf_failure_does_not_stop_batch(wc) -> None:
    old_candidates = wc.legal_pdf_candidates
    old_download = wc.download_pdf
    wc.legal_pdf_candidates = lambda article, email, verbose=False: [{"url": f"https://example.org/{article['doi']}.pdf", "source": "test"}]
    def fake_download(candidate, article, output_dir, run_dir, verbose=False):
        if article["doi"].endswith("1"):
            return {"status": "found_url_download_failed", "path": "", "error": "network failed"}
        return {"status": "downloaded", "path": "pdfs/ok.pdf", "error": ""}
    wc.download_pdf = fake_download
    try:
        articles = [
            wc.article_template(doi="10.1234/fail1"),
            wc.article_template(doi="10.1234/ok2"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            wc.fetch_legal_pdfs(articles, Path(tmp))
        assert_true(articles[0]["pdf_status"] == "found_url_download_failed", "Failed item status wrong")
        assert_true(articles[1]["pdf_status"] == "downloaded", "Batch stopped before second item")
    finally:
        wc.legal_pdf_candidates = old_candidates
        wc.download_pdf = old_download


def test_not_requested_default(wc) -> None:
    article = wc.article_template(title="No PDF requested")
    assert_true(article["pdf_status"] == "not_requested", "Default PDF status should be not_requested")


def test_title_fallback_does_not_crash(wc) -> None:
    wc.query_crossref_by_title = lambda title, verbose=False: None
    wc.query_openalex_by_title = lambda title, verbose=False: None
    article = wc.article_template(title="A title without DOI", metadata_source="plain-text", confidence=0.25)
    enriched = wc.enrich_one(article)
    assert_true(enriched["title"] == "A title without DOI", "Title fallback lost original title")
    assert_true(enriched["doi"] == "", "Title fallback should not invent DOI when APIs return nothing")


def web_capture_tests(wc, fixtures: Path):
    return [
        test_doi_regex,
        lambda module: test_noisy_reference_dois(module, fixtures),
        test_markup_sanitized_for_exports,
        test_sub_sup_tags_do_not_insert_spaces,
        test_jats_abstract_cleaning,
        test_arxiv_detection_requires_prefix,
        lambda module: test_meta_extraction(module, fixtures),
        lambda module: test_citation_pdf_url_extraction(module, fixtures),
        lambda module: test_jsonld_extraction(module, fixtures),
        lambda module: test_jsonld_pdf_extraction(module, fixtures),
        lambda module: test_openalex_and_unpaywall_fixture_candidates(module, fixtures),
        test_openalex_abstract_reconstruction_is_robust,
        test_abstract_source_priority,
        test_conservative_keyword_and_concept_extraction,
        test_conservative_keyword_negative_cases,
        lambda module: test_multi_doi_dedupe(module, fixtures),
        test_outputs,
        test_pdf_filename_cleaning,
        test_non_pdf_response_not_saved,
        test_pdf_failure_does_not_stop_batch,
        test_not_requested_default,
        test_title_fallback_does_not_crash,
    ]


def load_tests(loader, standard_tests, pattern):
    del loader, standard_tests, pattern
    fixtures = ROOT / "evals" / "web-capture"
    wc = load_web_capture()
    suite = unittest.TestSuite()
    for test in web_capture_tests(wc, fixtures):
        suite.addTest(unittest.FunctionTestCase(lambda test=test: test(wc)))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run no-network web-capture tests")
    parser.add_argument("--fixtures", default=str(ROOT / "evals" / "web-capture"), help="Fixture directory")
    args = parser.parse_args()

    fixtures = Path(args.fixtures)
    wc = load_web_capture()
    tests = web_capture_tests(wc, fixtures)
    for test in tests:
        test(wc)
    print(f"web-capture tests passed: {len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
