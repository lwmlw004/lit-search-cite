# lit-search-cite

> Multi-source academic literature search, journal ranking, auto-citation, and PDF download skill.

## Installation

### One command (recommended)

```bash
npx lit-search-cite@latest
```

Auto-detects and installs to Claude Code, OpenCode, and Agent Skills directories. Options:

```bash
npx lit-search-cite@latest --claude       # Claude Code / Claude Desktop only
npx lit-search-cite@latest --opencode     # OpenCode / Codex only
npx lit-search-cite@latest --agents       # Agent Skills only
npx lit-search-cite@latest --all          # All platforms (same as no flags)
npx lit-search-cite@latest --target ~/my-skills   # Custom path
```

### Manual installation

Copy the skill directory to the appropriate location for your platform:

| Platform | Global (all projects) | Project-level |
|----------|-----------------------|---------------|
| Claude Code | `~/.claude/skills/lit-search-cite/` | `.claude/skills/lit-search-cite/` |
| OpenCode / Codex | `~/.config/opencode/skills/lit-search-cite/` | `.opencode/skills/lit-search-cite/` |
| Agent Skills | `~/.agents/skills/lit-search-cite/` | `.agents/skills/lit-search-cite/` |

MCP servers are required for full functionality. Copy the JSON blocks from `references/mcp-template.md` into `~/.claude/mcp.json` (or merge into your existing file) and restart Claude Code.

### Hermes

Copy the directory to the Hermes skills directory. Tool names in SKILL.md are used without the `mcp__<server>__` prefix in some modes — Hermes resolves these automatically via its tool registry.

---

## Quick Start

```bash
# English search — zero-config (OpenAlex + CrossRef + PubMed)
python scripts/multi-search.py -q "transformer attention mechanism" -d cs

# With live journal rankings (requires OneScholar API key)
python scripts/multi-search.py -q "cancer immunotherapy" -d biomedicine --online-rank

# Year filter
python scripts/multi-search.py -q "styrene shape memory polymer" -d chemistry --year-from 2022 -t 20

# Capture literature from a web page, saved HTML, or copied references
python scripts/web-capture.py --url "https://example.com/article" --out references/captured --format bibtex,ris,csv,md,json

# Chinese literature — CNKI via OpenCLI browser (reuses existing browser login)
# Tell Claude: "帮我在知网搜索「大语言模型」" — no setup required

# Chinese literature — Wanfang API + browser URLs (Windows)
.\scripts\cnki-search.ps1 -Query "大语言模型 代码生成"

# Journal ranking (requires OneScholar API key)
python scripts/journal-rank.py -j "Nature" "Science" "Advanced Materials"
```

---

## Features

| Feature | Zero-config | With API key / setup |
|---------|------------|----------------------|
| English search | OpenAlex + CrossRef + PubMed + arXiv | + Semantic Scholar + Google Scholar (ai4scholar MCP) |
| Web literature capture | HTML meta + JSON-LD + DOI regex + PubMed/arXiv page cues | + CrossRef/OpenAlex/PubMed/arXiv enrichment, optional OneScholar rank |
| Google Scholar | Browser URLs only | ai4scholar MCP (key) |
| Chinese search | Browser URLs (CNKI/Baidu/Weipu) | + CNKI via OpenCLI browser + Wanfang API |
| Journal ranking | 300+ journal offline DB (built into multi-search) | + OneScholar live API (key) |
| PDF download | scansci-pdf (13+ sources) | + publisher access via CARSI / EZProxy / VPNSci |
| Citation | Manual workflow (all 7 styles) | — |

---

## Scripts

| Script | Platform | Description |
|--------|----------|-------------|
| `multi-search.py` | All | Multi-source search (OpenAlex/CrossRef/PubMed/arXiv), DOI dedup, journal ranking |
| `multi-search.ps1` | Windows | Same, PowerShell version |
| `web-capture.py` | All | Capture literature records from URL, HTML, or copied text; export BibTeX/RIS/CSV/Markdown/JSON |
| `web-capture.ps1` | Windows | Same, PowerShell wrapper |
| `test-web-capture.py` | All | No-network tests for web capture fixtures |
| `journal-rank.py` | All | OneScholar API journal ranking (requires key) |
| `journal-rank.ps1` | Windows | Same, PowerShell version; supports ISSN lookup |
| `pdf-fetch.py` | All | PDF download chain: Unpaywall → OpenAlex → EuropePMC → Sci-Hub URL (DOI input) |
| `pdf-fetch.ps1` | Windows | Same, PowerShell version |
| `cnki-search.ps1` | Windows | Wanfang API results + browser URLs for CNKI, Baidu Scholar, Weipu |
| `check-deps.ps1` | Windows | Dependency and config checker (12 checks) |
| `setup.ps1` | Windows | Interactive API key setup wizard |

---

## Web Literature Capture

Use `scripts/web-capture.py` when a user has a publisher article page, PubMed page, arXiv page, Google Scholar-style results page, journal issue page, saved HTML file, copied page text, or reference list and wants structured references.

```bash
# Single publisher page
python scripts/web-capture.py --url "https://example.com/article" --out references/captured --pdf legal

# PubMed page
python scripts/web-capture.py --url "https://pubmed.ncbi.nlm.nih.gov/12345678/" --out references/captured

# Search results or reference list text
python scripts/web-capture.py --text copied-references.txt --limit 50 --dedupe doi --format bibtex,ris,csv,md

# Windows wrapper
.\scripts\web-capture.ps1 -Url "https://example.com/article" -Out "references/captured" -Pdf legal
```

Each run writes `captured.json`, `captured.csv`, `captured.bib`, `captured.ris`, `captured.md`, `dois.txt`, `failed.txt`, and `run_report.md` under `references/captured/YYYYMMDD_HHMMSS/`.

`--pdf legal` only attempts legal open-access routes: publisher-provided open PDF links, Unpaywall, OpenAlex OA locations, EuropePMC/PubMed Central, and arXiv. Do not add paywall bypasses or unauthorized mirrors to this workflow. Optional scansci-pdf handoff uses `dois.txt`; OneFind/Zotero/EndNote indexing is documented in `docs/`.

---

## Requirements

- **Python 3.10+** — multi-search, journal-rank, pdf-fetch
- **Node.js 18+** — ai4scholar MCP server (`npx -y @ai4scholar/mcp-server`)
- **uv** — scansci-pdf MCP server (`uvx scansci-pdf`)
- **Windows PowerShell 5.1+** — `.ps1` scripts (optional; Python scripts work cross-platform)

---

## Supported Sources

| Source | Scale | Cost |
|--------|-------|------|
| OpenAlex | 250M papers | Free |
| CrossRef | 150M papers | Free |
| PubMed | 36M papers | Free |
| arXiv | 2M+ papers | Free |
| Semantic Scholar | 214M papers | Free key |
| Google Scholar | — | ai4scholar MCP key |
| CNKI (知网) | — | OpenCLI browser (reuses existing browser institutional login) |
| Wanfang (万方) | — | API key |
| Baidu Scholar / Weipu | — | Browser URL only |
| Elsevier Scopus | 78M papers | Institutional |
| Springer Nature OA | — | Free key |

---

## Platform Compatibility

| Feature | Claude Code | Claude Desktop | OpenCode | Codex | Hermes |
|---------|------------|----------------|----------|-------|--------|
| MCP tools | `mcp__server__tool` | same | auto-mapped | auto-mapped | generic names |
| Skill auto-load | ✅ | ✅ | ✅ | ✅ | ✅ |
| Python scripts | ✅ | ✅ | ✅ | ✅ | ✅ |
| PowerShell scripts | ✅ (Windows) | ✅ (Windows) | ✅ (Windows) | ✅ (Windows) | — |
