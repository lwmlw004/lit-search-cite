---
name: lit-search-cite
description: Multi-source academic literature search, journal ranking, auto-citation, and PDF download. Use when finding/sourcing academic papers across databases (CNKI, arXiv, PubMed, Google Scholar, Wanfang), downloading PDFs, checking journal rankings (JCR/CAS/CCF), adding citations (GB/T 7714, APA, IEEE), or writing literature reviews. Supports Chinese and English research workflows.
compatibility: opencode, claude-code, codex, hermes, claude-desktop
---

# Lit-Search-Cite: Academic Literature & Citation Skill

Multi-source literature search, journal ranking, auto-citation, and PDF download. English & Chinese.

> **Setup:** `.\scripts\check-deps.ps1` → `references/setup-guide.md`
> **Windows:** Use PowerShell `Invoke-RestMethod` — never Bash `curl` (returns exit 49).

---

## Source Selection (Quick Reference)

Pick 1–2 sources per search. More ≠ better. Journal tier via `journal-rank.py` works on any source's results.

| Domain | Best source (with key) | Free fallback | Journal tier |
|--------|----------------------|--------------|--------------|
| CS / AI | `ai4scholar` → arXiv | `multi-search.py -d cs` | Built-in auto |
| Engineering | `ai4scholar` → Semantic Scholar | `multi-search.py -d engineering` | Built-in auto |
| Chemistry / Materials | `ai4scholar` → Semantic Scholar | `multi-search.py -d chemistry` | Built-in auto |
| Biomedicine | `ai4scholar` → PubMed | `multi-search.py -d biomedicine` | Built-in auto |
| Physics / Math | arXiv + Semantic Scholar | `multi-search.py -d physics` | Built-in auto |
| Social / Humanities | Google Scholar + S2 | OpenAlex + CrossRef | `journal-rank.py` |
| **Chinese** | CNKI Playwright + Wanfang API | Same (no ai4scholar needed) | `journal-rank.py` |
| General | `multi-search.py -d general` (covers all free APIs) | Same | Built-in auto |

**Google Scholar priority:** ai4scholar MCP (fastest) → Playwright `google-scholar.py` (one-time browser config) → OpenAlex/CrossRef (zero config).

**Journal tier (universal):**
```bash
python scripts/journal-rank.py -j "Nature" "Adv. Mater." "JACS" --quiet
# Checks: OneScholar API (if key) → local 300-journal DB
```

---

## Mode 1 — Literature Search

**Triggers:** "find papers on X", "搜索关于X的文献", "state of the art", "related work"

1. **Clarify:** topic + domain (→ table above), year range, language, how many papers needed
2. **Search:** use best source for domain — `python scripts/multi-search.py -q "..." -d <dom>` is the zero-config default
3. **Annotate:** run `journal-rank.py` on unique venues, add tier to each paper
4. **Output** in this format:

```
[N] Title (Year)
    Authors: Lead Author et al.
    Venue: Journal Name  |  Tier: IF=X.X JCR-Q1 CAS-Q1
    Citations: N  |  DOI: https://doi.org/...
    Relevance: (why it matches — 1-2 sentences)
```

5. **Ask:** "Download PDFs? Find citing papers? Add citations?"

---

## Mode 2 — Auto-Citation

**Triggers:** "add citations to this text", "加引用", "annotate with references", "标注参考文献"

**Citation styles:** `apa` | `gbt7714` (ZH default) | `ieee` | `nature` | `vancouver` | `mla` | `chicago`

**Workflow:**
1. Read user's text. Identify each claim/sentence that needs a citation. Mark them `[1]`, `[2]`, etc.
2. For each claim, run 1 targeted search. Pick the best match by relevance + citation count.
3. Build output:

```
--- Annotated Text ---
[Original sentence with inline [1] markers]...

--- References ---
[1] Author A, Author B. "Title." *Journal*, Year. DOI: 10.xxxx/...
    Relevance: directly supports claim about X
    (⚠ verify) ← if match confidence < 80%
```

4. If a claim has no good match, insert `[?]` marker and note "No strong match found" in references.

---

## Mode 3 — Literature Review

**Triggers:** "write a literature review", "综述", "survey", "related work section"

1. Clarify: topic, 3–5 sub-themes, years, length (words/sections), style, language
2. **Round 1 (broad):** 2–3 queries per sub-theme, collect 20–30 papers
3. **Round 2 (fill gaps):** use `get_semantic_citations` on key papers, `get_semantic_recommendations` for related work
4. **Cluster** papers by sub-theme. Draft structure:

```
## 1. Overview → 2. Background → 3. Theme A → 4. Theme B → 5. Recent Advances → 6. Gaps → References
```

5. Each paragraph cites specific papers via `[Author, Year]` markers. Append full reference list at end.

---

## Mode 4 — Relevance Assessment

**Triggers:** "is this paper relevant?", "评价这篇文献", "rate this paper"

Score **1–10** with weights: topic fit (40%) + methodology (20%) + recency (20%) + venue quality (20%).

For venue quality, use `python scripts/journal-rank.py -j "JournalName" --quiet`. Also run `get_semantic_recommendations_for_paper` to surface related papers the user may have missed.

---

## Mode 5 — PDF Download

**Triggers:** "download this paper", "get the PDF", user says yes after Mode 1

### English papers

```
# Primary — headless, 13+ sources:
scansci_pdf_smart_download(identifier="DOI or arXiv ID")

# Fallback (no scansci-pdf MCP):
.\scripts\pdf-fetch.ps1 -DOI "10.xxxx/..."
```

Paywalled papers: one-time browser login (`scansci_pdf_import_browser_cookies` / `scansci_pdf_carsi_login`), then permanent headless.

### Chinese papers (CNKI)

Search is headless after VPN setup. PDF download requires visible browser (CNKI CAPTCHA):
```powershell
python scripts/cnki-playwright.py --query "关键词" --download --output ./Papers --no-headless
```

---

## Reference Files

| File | When to read |
|------|-------------|
| `references/setup-guide.md` | Installation: Node, Python, Playwright, MCP config, CNKI VPN |
| `references/api-setup.md` | All API endpoints, PowerShell/Bash examples |
| `references/search-strategies.md` | Query syntax: PubMed MeSH, arXiv cats, CNKI Boolean |
| `references/optional-apis.md` | OneScholar, Elsevier, Springer setup |
| `references/journal-ranks.json` | 300+ journal tier DB (offline fallback) |
| `references/mcp-template.json` | MCP server config to copy-paste |
