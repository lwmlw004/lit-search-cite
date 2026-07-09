# OneFind Workflow

OneFind is best treated as a local knowledge-base index. `lit-search-cite` captures and normalizes the literature records; OneFind, Zotero, EndNote, or a normal file index can make those local files searchable afterward.

## Recommended Workflow

1. Capture web literature metadata:

   ```bash
   python scripts/web-capture.py --url "https://example.com/references" --out references/captured --pdf legal
   ```

2. Let `lit-search-cite` enrich citation metadata and journal information where possible.
3. Save the run outputs under `references/captured/YYYYMMDD_HHMMSS/`.
4. Import `captured.bib` or `captured.ris` into Zotero or EndNote when reference-manager records are needed.
5. Let OneFind index `references/`, a Zotero storage folder, an EndNote library export folder, or another local folder that contains `onefind_index.md`, `captured.md`, `captured.json`, and legal PDF files.

## File Roles

- `captured.json`: structured metadata for later automation, including abstract/keyword/concept provenance and metadata warnings.
- `captured.md`: AI-readable literature summary with Abstract, Keywords, Concepts, enrichment sources, and warnings.
- `captured.bib`: BibTeX import for Zotero, JabRef, LaTeX, and many editors.
- `captured.ris`: RIS import for Zotero, EndNote, and Mendeley.
- `dois.txt`: DOI handoff list for optional downstream tools.
- `pdf_manifest.json`: PDF status, source, URL, local path, license, and OA status for each article.
- `onefind_index.md`: compact AI-readable index for OneFind and local knowledge-base search.
- `zotero_import_guide.md`: manual import instructions for Zotero / EndNote and local PDFs.
- `pdfs/`: legal open-access PDFs when `--pdf legal` succeeds.

## Boundaries

OneFind is not a PDF downloader and should not be treated as a web scraper. Use `web-capture.py` for capture, optional legal OA PDF lookup for downloads, then OneFind/Zotero/EndNote for local indexing and retrieval.

Point OneFind at the run directory or at the parent `references/captured/` folder. `onefind_index.md` keeps every article visible even when no PDF was found, and its `Local PDF` field uses a relative `pdfs/...` path when a legal OA PDF was downloaded.

## Metadata Enrichment

Publisher citation meta, CrossRef, OpenAlex, PubMed, JSON-LD, and arXiv can contribute metadata without changing the legal PDF policy. OpenAlex `abstract_inverted_index` values are rebuilt in position order, while `abstract_source`, `keywords_source`, `concepts_source`, and `metadata_warnings` keep the handoff traceable. Conservative chemistry terms are emitted only when the term or an approved spelling variant appears in source metadata, the title, or the abstract.
