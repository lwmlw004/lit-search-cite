# scansci-pdf Integration

`web-capture.py` is responsible for extracting DOI values, metadata, and citation files from public web pages, saved HTML, or copied text. It is not a hard dependency on scansci-pdf.

## Recommended Boundary

- `lit-search-cite` extracts records and writes `captured.json`, `captured.md`, `captured.bib`, `captured.ris`, `captured.csv`, and `dois.txt`.
- `scripts/web-capture.py --pdf legal` only tries legal open-access routes: publisher-provided PDF links, Unpaywall, OpenAlex OA locations, EuropePMC, PubMed Central, and arXiv.
- `scansci-pdf` can be used separately when the user has voluntarily configured that MCP server.
- Do not store school accounts, WebVPN passwords, CARSI credentials, EZProxy passwords, or institutional authentication secrets inside this project.

## Handoff Workflow

Run web capture first:

```bash
python scripts/web-capture.py --url "https://example.com/article-list" --out references/captured --format bibtex,ris,csv,md,json
```

Each run creates:

```text
references/captured/YYYYMMDD_HHMMSS/dois.txt
```

If scansci-pdf is configured in the user's AI environment, pass the DOI list to that external tool in the chat or through the MCP workflow the user already trusts. Keep this repository focused on extraction, enrichment, citation export, and legal OA lookup.

## What This Project Does Not Do

- It does not require scansci-pdf.
- It does not bypass paywalls.
- It does not embed Sci-Hub, LibGen, Anna's Archive, or other unauthorized mirrors in `web-capture.py`.
- It does not keep institutional credentials or browser session secrets.
