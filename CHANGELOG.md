# Changelog

## v1.0.0 (2026-06-15)

### Core

- **Multi-source search**: OpenAlex, CrossRef, PubMed, arXiv, Semantic Scholar, Google Scholar (MCP + Playwright), CNKI (Playwright), Elsevier Scopus, Springer Nature
- **Journal ranking**: OneScholar API + 300-journal offline DB with CAS/JCR/CCF/IF annotation
- **PDF download**: scansci-pdf MCP (13+ sources) + pdf-fetch fallback chain (Unpaywall → OpenAlex → EuropePMC → Sci-Hub)
- **Auto-citation**: Manual workflow supporting APA, GB/T 7714, IEEE, MLA, Chicago, Nature, Vancouver styles
- **Literature review**: Multi-round search, paper clustering, structured draft generation

### Scripts

| Script | Platform | Description |
|--------|----------|-------------|
| `multi-search.py` | All | One-command multi-source search with dedup + journal tier |
| `multi-search.ps1` | Windows | PowerShell version (legacy) |
| `journal-rank.py` | All | Journal ranking via OneScholar API + offline DB |
| `journal-rank.ps1` | Windows | PowerShell version (legacy) |
| `pdf-fetch.py` | All | PDF download chain |
| `pdf-fetch.ps1` | Windows | PowerShell version (legacy) |
| `cnki-playwright.py` | All | CNKI search + VPN setup for 76 Chinese universities |
| `cnki-search.ps1` | Windows | Chinese literature search (Wanfang API + browser URLs) |
| `google-scholar.py` | All | Google Scholar via Playwright (headless after setup) |
| `check-deps.ps1` | Windows | Dependency verification |
| `setup.ps1` | Windows | API key configuration wizard |

### Documentation

- `SKILL.md` — Core skill instructions (5 modes, platform-agnostic)
- `README.md` — Chinese documentation (GitHub default)
- `AGENTS.md` — English documentation
- `references/api-setup.md` — All API endpoints with PowerShell + Bash examples
- `references/setup-guide.md` — Complete installation guide
- `references/search-strategies.md` — Query syntax by source
- `references/optional-apis.md` — OneScholar, Elsevier, Springer, WoS setup
- `references/journal-ranks.json` — 300+ journal tier offline database
- `references/mcp-template.json` — MCP server config for Claude Code / OpenCode

### Platform Support

- Claude Code, Claude Desktop, OpenCode, Codex, Hermes
- Windows (PowerShell + Python), macOS/Linux (Python)
- Agent Skills standard compliant (`compatibility` field)
