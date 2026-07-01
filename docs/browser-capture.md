# Browser Capture

`web-capture.py` accepts a live URL, a saved HTML file, or copied page text. The browser side can stay lightweight; it only needs to provide public page content to the script.

## Option A: Copy the Current URL

```bash
python scripts/web-capture.py --url "https://example.com/article" --out references/captured --pdf legal
```

On Windows, prefer the Python launcher:

```powershell
py -3 scripts\web-capture.py --url "https://example.com/article" --out references\captured --pdf legal
```

Use this for publisher article pages, PubMed pages, arXiv pages, journal issue pages, and reference-list pages that are publicly reachable from the current network.

Some publisher pages return HTTP 403 to command-line fetchers. That is normal. If the URL contains a DOI, PMID, or arXiv ID, `web-capture.py` falls back to that identifier and tries public metadata enrichment. For the most stable capture, save the browser-rendered page as HTML and use Option B. Live URL tests should not be the only acceptance check.

## Option B: Save the Page HTML

In the browser, save the current page as HTML, then run:

```bash
python scripts/web-capture.py --html page.html --out references/captured
```

Windows:

```powershell
py -3 scripts\web-capture.py --html page.html --out references\captured
```

This is useful when the browser already rendered metadata into the page or when the network request is easier from the browser than from the command line.

## Option C: Bookmarklet

Create a bookmark with this URL:

```javascript
javascript:(()=>{const s=window.getSelection().toString();const text=[`Title: ${document.title}`,`URL: ${location.href}`,`Selected: ${s}`,`DOI candidates: ${document.body.innerText.match(/\b10\.\d{4,9}\/[-._;()/:A-Z0-9%]+/ig)?.join(", ")||""}`].join("\n");navigator.clipboard.writeText(text).then(()=>alert("lit-search-cite capture text copied"));})();
```

Then paste the clipboard into a text file and run:

```bash
python scripts/web-capture.py --text copied.txt --out references/captured
```

Windows:

```powershell
py -3 scripts\web-capture.py --text copied.txt --out references\captured
```

The bookmarklet only collects visible page title, URL, selected text, and DOI candidates. It does not bypass login, does not decrypt content, and does not circumvent paywalls.

## PowerShell Wrapper

The Windows wrapper is convenient when PowerShell script execution is allowed:

```powershell
.\scripts\web-capture.ps1 -Url "https://example.com/article" -Out "references\captured" -Pdf legal
```

If execution policy blocks local scripts, run it explicitly with a one-command bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\web-capture.ps1 -Url "https://example.com/article" -Out "references\captured" -Pdf legal
```

## Local Fixtures

The no-network fixtures in `evals/web-capture/` cover:

- `sample_publisher_meta.html`: publisher `citation_*` meta tags
- `sample_jsonld_article.html`: schema.org `ScholarlyArticle` JSON-LD
- `sample_pubmed.html`: PubMed-like page metadata
- `sample_arxiv.html`: arXiv-like abstract page
- `sample_reference_list.txt`: multi-DOI reference list
- `sample_reference_noise.txt`: noisy DOI text with Chinese punctuation, parentheses, duplicates, and line breaks
- `sample_open_pdf_meta.html`: `citation_pdf_url` and publisher PDF link extraction
- `sample_arxiv_pdf.html`: JSON-LD PDF `contentUrl` extraction
- `sample_openalex_oa.json`: OpenAlex OA PDF metadata fixture
- `sample_unpaywall.json`: Unpaywall OA location fixture

Run them with:

```powershell
py -3 scripts\test-web-capture.py
```

## Run Report PDF Status

Each capture run writes `run_report.md`. Common PDF statuses are:

| Status | Meaning |
|--------|---------|
| `not_requested` | `--pdf legal` was not used, so no PDF lookup was attempted |
| `not_found_or_paywalled` | Legal open-access lookup ran but no open PDF was found, or the PDF appears to be behind a paywall |
| `found_url_download_failed` | A candidate PDF URL was found, but the download failed, returned non-PDF content, or was blocked |
| `skipped_non_pdf` | The candidate URL returned HTML or other non-PDF content and was not saved |
| `skipped_unsafe_url` | The candidate URL used an unsupported scheme or a blocked unauthorized source |
| `downloaded` | A legal open-access PDF was saved successfully in the run directory |

When `--pdf legal` succeeds, PDFs are saved under `pdfs/`. The same run also writes `pdf_manifest.json`, `onefind_index.md`, and `zotero_import_guide.md` for local indexing and reference-manager handoff.
