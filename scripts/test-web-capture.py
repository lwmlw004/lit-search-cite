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
from pathlib import Path
import tempfile
import sys

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


def test_jsonld_extraction(wc, fixtures: Path) -> None:
    html = (fixtures / "sample_jsonld_article.html").read_text(encoding="utf-8")
    articles = wc.build_initial_candidates(html, "sample_jsonld_article.html", True)
    match = next((a for a in articles if a["doi"] == "10.5678/jsonld.2023.002"), None)
    assert_true(match is not None, "JSON-LD DOI not extracted")
    assert_true(match["journal"] == "Example AI Chemistry", "JSON-LD journal mismatch")
    assert_true("Carla Nguyen" in match["authors"], "JSON-LD author missing")


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
        confidence=0.9,
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
        for name in ["captured.bib", "captured.ris", "captured.csv", "captured.md", "captured.json", "dois.txt", "failed.txt", "run_report.md"]:
            assert_true((out / name).exists(), f"Missing output file: {name}")
        assert_true("10.1234/output.fixture" in (out / "captured.bib").read_text(encoding="utf-8"), "BibTeX missing DOI")
        assert_true("# Captured Literature" in (out / "captured.md").read_text(encoding="utf-8"), "Markdown heading missing")


def test_title_fallback_does_not_crash(wc) -> None:
    wc.query_crossref_by_title = lambda title, verbose=False: None
    wc.query_openalex_by_title = lambda title, verbose=False: None
    article = wc.article_template(title="A title without DOI", metadata_source="plain-text", confidence=0.25)
    enriched = wc.enrich_one(article)
    assert_true(enriched["title"] == "A title without DOI", "Title fallback lost original title")
    assert_true(enriched["doi"] == "", "Title fallback should not invent DOI when APIs return nothing")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run no-network web-capture tests")
    parser.add_argument("--fixtures", default=str(ROOT / "evals" / "web-capture"), help="Fixture directory")
    args = parser.parse_args()

    fixtures = Path(args.fixtures)
    wc = load_web_capture()
    tests = [
        test_doi_regex,
        lambda module: test_noisy_reference_dois(module, fixtures),
        test_markup_sanitized_for_exports,
        test_arxiv_detection_requires_prefix,
        lambda module: test_meta_extraction(module, fixtures),
        lambda module: test_jsonld_extraction(module, fixtures),
        lambda module: test_multi_doi_dedupe(module, fixtures),
        test_outputs,
        test_title_fallback_does_not_crash,
    ]
    for test in tests:
        test(wc)
    print(f"web-capture tests passed: {len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
