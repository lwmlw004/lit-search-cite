# Setup Guide — lit-search-cite

Complete installation and one-time configuration.

---

## Step 1 — Install System Dependencies

| Component | Required for | Install (Windows) |
|-----------|-------------|-------------------|
| Node.js 18+ | ai4scholar MCP | `winget install OpenJS.NodeJS` |
| Python 3.10+ | CNKI Playwright, scansci-pdf | `winget install Python.Python.3.11` |
| Playwright + Chromium | CNKI, Google Scholar browser | `pip install playwright && playwright install chromium` |
| uv | scansci-pdf MCP | `pip install uv` or `winget install astral-sh.uv` |

**Verify:**
```powershell
node --version          # v18+
python --version        # 3.10+
python -c "from playwright.sync_api import sync_playwright; print('OK')"
uvx --version
```

---

## Step 2 — MCP Servers

Edit `%USERPROFILE%\.claude\mcp.json` and add:

```json
{
  "mcpServers": {
    "ai4scholar": {
      "command": "npx",
      "args": ["-y", "@ai4scholar/mcp-server"],
      "env": { "AI4SCHOLAR_API_KEY": "sk-user-your-key-here" }
    },
    "scansci-pdf": {
      "command": "uvx",
      "args": ["scansci-pdf"]
    }
  }
}
```

Restart Claude Code. Copy-paste template: `references/mcp-template.json`.

---

## Step 3 — API Keys

```powershell
.\scripts\setup.ps1
```

Interactive wizard. Keys saved to `~/.lit-search-cite/config.json`. Priority:

| Key | Impact |
|-----|--------|
| `ai4scholar` | Google Scholar + S2 (214M papers) — highest impact |
| `unpaywall_email` | OA PDF discovery — free, any email |
| `onescholar` | Live journal rankings (JCR/CAS/IF) |
| `semantic_scholar` | S2 direct fallback |
| `wanfang` | Structured Chinese search |

View: `.\scripts\setup.ps1 -Show`

---

## Step 4 — Google Scholar Playwright (Optional)

One-time browser setup for real Google Scholar results:
```powershell
python scripts/google-scholar.py --setup
# Browser opens → solve CAPTCHA → press Enter in terminal
```
Then headless forever:
```powershell
python scripts/google-scholar.py --query "styrene smart polymer" --limit 10
python scripts/google-scholar.py --status
```
Cookie expires ~7 days. Refresh: `python scripts/google-scholar.py --login-only`

---

## Step 5 — CNKI WebVPN (Chinese Literature)

One-time setup with auto-detection for 76 Chinese universities:
```powershell
python scripts/cnki-playwright.py --setup --school scau       # abbreviation
python scripts/cnki-playwright.py --setup --school "清华大学"  # Chinese name
```
Then headless search works:
```powershell
python scripts/cnki-playwright.py --query "形状记忆 聚合物" --limit 20
```
Session expires ~7 days. Refresh: `python scripts/cnki-playwright.py --login-only --no-headless`

---

## Step 6 — Publisher PDF Access

For paywalled papers. Tell Claude one of:
- "帮我配置 scansci-pdf 的 ScienceDirect Cookie" (universal)
- "帮我配置 scansci-pdf CARSI 登录" (Chinese universities)
- "帮我配置 scansci-pdf EZProxy 登录" (library proxy)

Browser opens → log in once → cookies saved → permanent headless PDF download.

---

## Step 7 — Verify

```powershell
.\scripts\check-deps.ps1
```

Expected: `Status: READY — all critical components configured.`

---

## Minimum Working Config

| Tier | Setup needed | What works |
|------|-------------|------------|
| Zero-config | Nothing | PubMed, arXiv, OpenAlex, CrossRef, OA PDF |
| Recommended | Steps 2-3 | + Google Scholar, S2, journal rankings |
| Full English | + Step 6 | + Paywalled PDF from any publisher |
| Full Chinese | + Step 5 | + CNKI headless search |
| Complete | All steps | + Wanfang structured Chinese results |

---

## Config File

`~/.lit-search-cite/config.json` (local only, never share):

```json
{
  "vpn_url": "https://vpn.your-school.edu.cn",
  "cnki_vpn_base": "https://kns-cnki-net-s.vpn.your-school.edu.cn",
  "api_keys": {
    "ai4scholar": "sk-user-...",
    "onescholar": "sk_...",
    "semantic_scholar": "s2k-...",
    "unpaywall_email": "you@email.com",
    "wanfang": "",
    "elsevier": "",
    "springer": ""
  }
}
```

> **For AI agents:** Do NOT run `setup.ps1`, `cnki-playwright.py --setup/--login-only`, or scansci-pdf login tools via shell — they require interactive terminal + visible browser. Tell the user the exact command to run themselves.
