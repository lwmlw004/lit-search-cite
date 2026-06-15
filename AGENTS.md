# lit-search-cite v1.0.0

> Multi-source academic literature search, journal ranking, auto-citation, and PDF download skill.

## Installation

### One-command (recommended)

```bash
npx lit-search-cite
```

Auto-detects Claude Code, OpenCode, and Agent Skills directories. Options:

```bash
npx lit-search-cite --claude       # Claude Code only
npx lit-search-cite --opencode     # OpenCode / Codex only
npx lit-search-cite --all          # All platforms
npx lit-search-cite --target ~/my-skills   # Custom path
```

### Manual

#### Claude Code / Claude Desktop

```powershell
# Copy to personal skills (all projects):
cp -r "$SKILL_DIR" "$env:USERPROFILE\.claude\skills\lit-search-cite"

# Or copy to project only:
cp -r "$SKILL_DIR" ".claude\skills\lit-search-cite"
```

MCP servers required (copy `references/mcp-template.json` → `%USERPROFILE%\.claude\mcp.json`).

### OpenCode / Codex

```powershell
# Personal (all projects):
cp -r "$SKILL_DIR" "$env:USERPROFILE\.config\opencode\skills\lit-search-cite"

# Project only:
cp -r "$SKILL_DIR" ".opencode\skills\lit-search-cite"
```

OpenCode auto-discovers from `.claude/skills/` and `.agents/skills/` too — any of the three locations work.

### Hermes

Copy to the Hermes skills directory. Tool references in SKILL.md use generic names (no `mcp__` prefix) — compatible with Hermes's tool resolution.

## Quick Start

```powershell
# One command — zero config required
.\scripts\multi-search.ps1 -Query "transformer attention mechanism" -Domain cs

# With journal rankings
.\scripts\multi-search.ps1 -Query "styrene shape memory polymer" -Domain chemistry -OnlineRank

# CNKI Chinese search (requires one-time VPN setup)
python scripts/cnki-playwright.py --setup
python scripts/cnki-playwright.py --query "大语言模型 代码生成" --limit 20
```

## Features

| Feature | Zero-config | With API Key |
|---------|------------|--------------|
| English search | OpenAlex + CrossRef + PubMed + arXiv | + Semantic Scholar + Google Scholar (ai4scholar) |
| Chinese search | CNKI Playwright + 万方 API | — |
| Journal ranking | 300+ journal offline DB | + OneScholar live API |
| PDF download | scansci-pdf (13+ sources) | + Elsevier/Springer full-text |
| Citation | Manual workflow (all styles) | — |

## Requirements

- **Windows:** PowerShell 5.1+, Python 3.10+, Playwright/Chromium
- **macOS/Linux:** Bash, Python 3.10+, Playwright/Chromium
- Node.js 18+ (ai4scholar MCP)
- scansci-pdf MCP (PDF download)

## Supported Sources

| Source | Type | Cost |
|--------|------|------|
| OpenAlex (250M papers) | REST API | Free |
| CrossRef (150M) | REST API | Free |
| PubMed (36M) | E-utilities | Free |
| arXiv (2M) | API | Free |
| Semantic Scholar (214M) | API / MCP | Free key |
| Google Scholar | MCP / Playwright | MCP key or browser setup |
| CNKI / 万方 / 维普 | Playwright / API | Setup required |
| Elsevier Scopus | REST API | Institutional |
| Springer Nature | REST API | Free key |

## Platform Compatibility

| Feature | Claude Code | Claude Desktop | OpenCode | Codex | Hermes |
|---------|------------|---------------|----------|-------|--------|
| MCP tools | ✅ `mcp__server__tool` | ✅ same | ✅ auto-map | ✅ auto-map | ✅ generic |
| Skill auto-load | ✅ | ✅ | ✅ `skill tool` | ✅ | ✅ |
| PowerShell scripts | ✅ | ✅ | ✅ | ✅ | — |
| Bash fallback | ✅ | ✅ | ✅ | ✅ | ✅ |
