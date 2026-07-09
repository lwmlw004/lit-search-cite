# Metadata Enrichment Design

## Goal

Improve the metadata handed from `web-capture.py` to local search and
Obsidian workflows without changing existing CLI behavior, adding paywall
bypasses, or inventing scholarly content.

## Scope

The implementation is limited to `lit-search-cite`. It reuses the existing
CrossRef, OpenAlex, PubMed-by-PMID, HTML meta, JSON-LD, and arXiv sources.
It does not add EuropePMC, change legal PDF discovery, modify
`obsidian-vault-mcp`, import a formal vault, or push commits.

## Pipeline

The existing pipeline remains:

`source parsing -> article_template normalization -> merge_article selection -> enrich_article_metadata derivation -> existing output writers`

`article_template` gains stable fields:

- `abstract_source`
- `keywords_source`
- `concepts`
- `concepts_source`
- `enrichment_sources`
- `metadata_warnings`

Empty scalar fields use `""`; empty collection fields use `[]`.

## Abstract Processing

`clean_text()` keeps its current title behavior. A separate
`clean_abstract_text()` removes JATS/XML and ordinary HTML tags, decodes
entities, collapses whitespace, and normalizes `C(sp 3 )` to `C(sp3)` and
`S H 2` to `SH2`.

Abstract candidates are scored using length, sentence count, residual markup,
abnormal fragment starts, and title/SEO repetition. `merge_article()` keeps
the higher-quality abstract and its `abstract_source`. Suspected truncation is
preserved verbatim after cleaning and recorded in `metadata_warnings`; missing
text is never reconstructed.

OpenAlex `abstract_inverted_index` is rebuilt by sorted integer position.
Malformed indexes, invalid positions, and duplicate positions produce
warnings instead of exceptions.

## Publisher Metadata

Publisher meta extraction prefers `citation_abstract`,
`citation_keywords`, and `article:tag`. `DC.Description`, `description`, and
`og:description` are lower-priority abstract candidates and are used only when
no better abstract exists. The selected field is reflected in
`abstract_source`.

## Keywords And Concepts

Source-provided keywords are merged with a fixed, conservative phrase matcher
over title, abstract, and explicit source metadata. Canonical phrases include
the requested electrochemistry, catalysis, reactant, mechanism, and coupling
terms. Matches must occur in source text.

`SET` matches only the standalone uppercase abbreviation or an explicit
single-electron-transfer phrase. Generic `acid`, `catalyst`, `coupling
constant`, and lowercase `set` do not trigger chemistry concepts.

Concepts combine explicit OpenAlex concepts/topics with the same conservative
canonical matches. `keywords_source`, `concepts_source`, and
`enrichment_sources` retain stable source names.

## Outputs

- `captured.json` always includes all enrichment fields.
- `captured.md` shows Abstract, Keywords, Concepts, enrichment sources, and
  warnings.
- `onefind_index.md` shows Title, DOI, Authors, Journal, Year, Abstract,
  Keywords, Concepts, PDF/OA status, and source capture directory.
- `run_report.md` summarizes abstract coverage, source counts, keyword and
  concept source counts, and warning totals.

Existing BibTeX, RIS, CSV, PDF manifest, and legal PDF behavior remain
compatible.

## Error Handling

Metadata parsing failures are attached to `metadata_warnings` and do not stop
the current article or batch. Network failures keep the existing fallback
behavior. A publisher HTTP 403 remains a normal identifier-fallback case.

## Verification

No-network fixtures and tests cover:

- JATS/XML abstract cleaning and chemistry spacing normalization
- robust OpenAlex inverted-index reconstruction
- CrossRef/OpenAlex abstract selection
- publisher abstract and keyword meta
- positive canonical chemistry phrases and SH2
- negative `acid wash`, `catalyst amount`, `coupling constant`, and
  `set of values`
- stable JSON, Markdown, OneFind, and run-report outputs

After local tests and `git diff --check`, JACS DOI
`10.1021/jacs.6c08562` and Science DOI `10.1126/science.abl4322` receive
best-effort smoke tests. Network instability or publisher 403 responses do
not override fixture-based acceptance.
