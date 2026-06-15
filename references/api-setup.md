# API 配置指南 / API Setup Guide

Core search and download APIs. All endpoint examples include PowerShell (Windows) and Bash (macOS/Linux).

> **Setup shortcut:** `.\setup.ps1` + `references\mcp-template.json` for everything below.
> **Full guide:** `references\setup-guide.md` for system deps, MCP install, CNKI VPN.

---

## Quick Reference — Which Path Needs What

| Path | API | Key required? | Best for |
|------|-----|--------------|----------|
| A1 | ai4scholar MCP (Google Scholar + S2 + PubMed) | `AI4SCHOLAR_API_KEY` | Multi-source, fastest |
| A2 | ai4scholar REST API (S2) | `AI4SCHOLAR_API_KEY` | No MCP needed |
| B | Semantic Scholar direct | `SEMANTIC_SCHOLAR_API_KEY` | S2-only fallback |
| C | PubMed E-utilities | Free | Biomedicine |
| D | arXiv API | Free | CS / Physics / Math |
| E | scansci-pdf MCP | Free | PDF download |
| F | OpenAlex | Free | General (250M papers) |
| G | CrossRef | Free | DOI-registered papers |
| I | `multi-search.ps1` | Free | One-command multi-source |

---

## Path A1/A2 — ai4scholar (Google Scholar + Semantic Scholar + PubMed)

One key, three databases. MCP mode (A1) for tool-based calls; REST mode (A2) for direct HTTP.

### REST API (Path A2, no MCP required)

```
GET https://ai4scholar.net/graph/v1/paper/search
  ?query=<keywords>&limit=10
  &fields=paperId,title,year,citationCount,authors,abstract,venue
Authorization: Bearer <AI4SCHOLAR_API_KEY>
```

**PowerShell:**
```powershell
$headers = @{"Authorization"="Bearer $env:AI4SCHOLAR_API_KEY"}
$r = Invoke-RestMethod "https://ai4scholar.net/graph/v1/paper/search?query=styrene+polymer&limit=10&fields=paperId,title,year,citationCount,venue" -Headers $headers
```

**Bash:**
```bash
curl "https://ai4scholar.net/graph/v1/paper/search?query=styrene+polymer&limit=10&fields=paperId,title,year,citationCount,venue" -H "Authorization: Bearer $AI4SCHOLAR_API_KEY"
```

Also available: `/paper/{id}/citations`, `/paper/{id}/references`, `/author/search`.

---

## Path B — Semantic Scholar Direct API

Free key at https://www.semanticscholar.org/product/api (1-2 day approval).

> **Anonymous use:** Theoretically supported, practically always returns 429. A key is required.

```
GET https://api.semanticscholar.org/graph/v1/paper/search
  ?query=<keywords>&limit=10&fields=title,year,citationCount,venue
x-api-key: <SEMANTIC_SCHOLAR_API_KEY>
```

**PowerShell:**
```powershell
$r = Invoke-RestMethod "https://api.semanticscholar.org/graph/v1/paper/search?query=styrene+block+copolymer&limit=10&fields=title,year,citationCount,venue" -Headers @{"x-api-key"=$env:SEMANTIC_SCHOLAR_API_KEY}
```

---

## Path C — PubMed E-utilities (Free)

Two-step: search → get IDs → fetch summaries. No key needed.

```powershell
# Step 1: Search
$s = Invoke-RestMethod "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=styrene+smart+material&retmax=10&retmode=json&sort=relevance"
$ids = $s.esearchresult.idlist -join ","

# Step 2: Summaries
$sum = Invoke-RestMethod "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=$ids&retmode=json"
```

MeSH qualifiers: `[Title/Abstract]`, `[MeSH Terms]`, `[Author]`, `[Journal]`.  
Full syntax in `references/search-strategies.md`.

---

## Path D — arXiv API (Free)

Returns Atom XML. Always add category filter to avoid noise.

```
GET https://export.arxiv.org/api/query
  ?search_query=all:styrene+polymer+AND+(cat:cond-mat.mtrl-sci)
  &max_results=10&sortBy=relevance
```

**PowerShell:**
```powershell
$r = Invoke-WebRequest "https://export.arxiv.org/api/query?search_query=all:styrene+polymer+AND+(cat:cond-mat.mtrl-sci)&max_results=10&sortBy=relevance" -UseBasicParsing
# Parse: [regex]::Matches($r.Content, '<entry>.*?<title>(.*?)</title>', 'Singleline')
```

| Category | Use for |
|----------|---------|
| `cond-mat.mtrl-sci` | Materials / Chemistry |
| `physics.chem-ph` | Chemical Physics |
| `cs.LG` | Machine Learning |
| `q-bio` | Biology |

---

## Path F — OpenAlex (Free, 250M papers)

No key. Sort by citation count. Use precise keywords.

```
GET https://api.openalex.org/works
  ?search=<keywords>&per-page=10&sort=cited_by_count:desc
  &select=id,doi,title,publication_year,cited_by_count,authorships,primary_location,open_access
```

**PowerShell (PS5.1: must use `select=` to exclude `abstract_inverted_index`):**
```powershell
$q = [uri]::EscapeDataString("styrene-butadiene-styrene strain sensor")
$r = Invoke-RestMethod "https://api.openalex.org/works?search=$q&per-page=10&sort=cited_by_count:desc&select=id,doi,title,publication_year,cited_by_count,authorships,primary_location,open_access"
```

Year filter: `&filter=publication_year:>2022`

---

## Path G — CrossRef (Free, 150M DOI papers)

Better relevance than OpenAlex. Combine `type:journal-article,has-abstract:true` to filter noise.

```
GET https://api.crossref.org/works
  ?query=<keywords>&rows=10&sort=relevance
  &filter=type:journal-article,has-abstract:true
```

**PowerShell:**
```powershell
$q = [uri]::EscapeDataString("styrene block copolymer self-healing")
$r = Invoke-RestMethod "https://api.crossref.org/works?query=$q&rows=10&sort=relevance&filter=type:journal-article,has-abstract:true"
# $r.message.items → title[0], DOI, published.date-parts[0][0], is-referenced-by-count
```

---

## Path I — multi-search.ps1 (One command, all free APIs)

```powershell
.\scripts\multi-search.ps1 -Query "styrene smart polymer" -Domain chemistry -TotalLimit 20
.\scripts\multi-search.ps1 -Query "..." -OnlineRank        # + live journal ranks from OneScholar
.\scripts\multi-search.ps1 -Query "..." -YearFrom 2022 -YearTo 2025
```

Wraps Paths C/D/F/G. Auto dedup, tier annotation, formatted output.

---

## Journal Ranking — journal-rank.ps1

Local (offline) or live (OneScholar API). Works with results from ANY search path.

```powershell
# Batch query 5 journals per API call, caches 30 days, falls back to 300-journal offline DB
.\scripts\journal-rank.ps1 -Journal @("Nature", "Adv. Mater.", "JACS") -Quiet
# → IF=48.5 JCR-Q1 CAS-Q1 CAS-Top
```

Offline DB: `references/journal-ranks.json` (300+ journals, no key needed).

---

## OneScholar API (Live journal rankings)

```http
POST https://api.scigreat.com/info/getrank
Authorization: Bearer <ONESCHOLAR_API_KEY>
Content-Type: application/json

[{"journal": ["Nature"]}, {"journal": ["Science"]}]
```

Free: 1,000/day, 1 req/sec, max 5 journals per request. Use `journal-rank.ps1` — it handles batching, caching, and fallback automatically.

---

## PDF Download

**Primary (MCP):**
```
scansci_pdf_smart_download(identifier="10.xxxx/..." or "arXiv ID")
```

**Fallback (no MCP):**
```powershell
.\scripts\pdf-fetch.ps1 -DOI "10.xxxx/..."
# Chain: Unpaywall → OpenAlex → EuropePMC → Sci-Hub URL
```

Paywalled papers: one-time browser login via `scansci_pdf_import_browser_cookies` / `carsi_login` / `ezproxy_login` → stored cookies → permanent headless.

---

## CNKI / 知网 (Chinese)

No REST API. Programmatic access via `scripts/cnki-playwright.py` (Playwright browser engine):

```powershell
python scripts/cnki-playwright.py --setup --school scau      # one-time VPN setup
python scripts/cnki-playwright.py --query "形状记忆 聚合物" --limit 20   # headless search
```

Wanfang API (structured Chinese results): register at https://open.wanfangdata.com.cn/ → `WANFANG_API_KEY`.

---

## Config File

`~/.lit-search-cite/config.json` — created by `.\scripts\setup.ps1`:

```json
{
  "vpn_url": "https://vpn.your-school.edu.cn",
  "cnki_vpn_base": "https://kns-cnki-net-s.vpn.your-school.edu.cn",
  "api_keys": {
    "ai4scholar": "sk-user-...",
    "semantic_scholar": "s2k-...",
    "onescholar": "sk_...",
    "elsevier": "",
    "springer": "",
    "unpaywall_email": "you@email.com",
    "wanfang": ""
  }
}
```

All scripts auto-read this file. Env vars used as fallback.
