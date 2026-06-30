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
5. Let OneFind index `references/`, a Zotero storage folder, an EndNote library export folder, or another local folder that contains `captured.md`, `captured.json`, and legal PDF files.

## File Roles

- `captured.json`: structured metadata for later automation.
- `captured.md`: AI-readable literature summary.
- `captured.bib`: BibTeX import for Zotero, JabRef, LaTeX, and many editors.
- `captured.ris`: RIS import for Zotero, EndNote, and Mendeley.
- `dois.txt`: DOI handoff list for optional downstream tools.
- `pdfs/`: legal open-access PDFs when `--pdf legal` succeeds.

## Boundaries

OneFind is not a PDF downloader and should not be treated as a web scraper. Use `web-capture.py` for capture, optional legal OA PDF lookup for downloads, then OneFind/Zotero/EndNote for local indexing and retrieval.
