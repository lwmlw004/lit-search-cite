# lit-search-cite v1.0.0

> 多源学术文献检索、期刊等级查询、自动引用标注、PDF 下载一体化 Skill。

## 安装

### 一键安装（推荐）

```bash
npx lit-search-cite
```

自动检测并安装到 Claude Code / OpenCode / Agent Skills 目录。也可指定平台：

```bash
npx lit-search-cite --claude      # 仅 Claude Code
npx lit-search-cite --opencode    # 仅 OpenCode
npx lit-search-cite --all         # 全部
npx lit-search-cite --target ~/my-skills  # 自定义路径
```

### 手动安装

#### Claude Code / Claude Desktop

```powershell
# 复制到个人 skills（所有项目可用）：
cp -r "$SKILL_DIR" "$env:USERPROFILE\.claude\skills\lit-search-cite"

# 或仅复制到当前项目：
cp -r "$SKILL_DIR" ".claude\skills\lit-search-cite"
```

需要配置 MCP 服务器（复制 `references/mcp-template.json` → `%USERPROFILE%\.claude\mcp.json`）。

### OpenCode / Codex

```powershell
# 个人（所有项目）：
cp -r "$SKILL_DIR" "$env:USERPROFILE\.config\opencode\skills\lit-search-cite"

# 仅当前项目：
cp -r "$SKILL_DIR" ".opencode\skills\lit-search-cite"
```

OpenCode 也会自动发现 `.claude/skills/` 和 `.agents/skills/` 中的 skill —— 三个位置任选其一。

### Hermes

复制到 Hermes skills 目录。SKILL.md 中工具引用使用通用名称（无 `mcp__` 前缀），兼容 Hermes 的工具解析。

## 快速开始

```bash
# 一条命令，零配置
python scripts/multi-search.py -q "transformer attention mechanism" -d cs

# 带期刊等级标注
python scripts/multi-search.py -q "styrene shape memory polymer" -d chemistry --online-rank

# CNKI 中文文献检索（需一次性 VPN 配置）
python scripts/cnki-playwright.py --setup
python scripts/cnki-playwright.py --query "大语言模型 代码生成" --limit 20
```

## 功能概览

| 功能 | 零配置 | 有 API Key |
|------|--------|-----------|
| 英文文献检索 | OpenAlex + CrossRef + PubMed + arXiv | + Semantic Scholar + Google Scholar (ai4scholar) |
| 中文文献检索 | CNKI Playwright + 万方 API | — |
| 期刊等级查询 | 300+ 期刊离线库 | + OneScholar 在线 API |
| PDF 下载 | scansci-pdf (13+ 来源) | + Elsevier/Springer 全文 |
| 论文引用标注 | 手动工作流（全格式） | — |

## 环境要求

- Python 3.10+（核心搜索脚本）
- **Windows:** PowerShell 5.1+（legacy .ps1 脚本 + CNKI Playwright）
- **macOS/Linux:** Bash（curl 备选 + CNKI Playwright）
- Playwright + Chromium（`pip install playwright && playwright install chromium`）
- Node.js 18+（ai4scholar MCP）
- scansci-pdf MCP（PDF 下载）

## 支持的文献源

| 数据源 | 类型 | 费用 |
|--------|------|------|
| OpenAlex (2.5 亿篇) | REST API | 免费 |
| CrossRef (1.5 亿篇) | REST API | 免费 |
| PubMed (3600 万篇) | E-utilities | 免费 |
| arXiv (200 万篇) | API | 免费 |
| Semantic Scholar (2.14 亿篇) | API / MCP | 免费申请 Key |
| Google Scholar | MCP / Playwright | MCP Key 或浏览器配置 |
| CNKI / 万方 / 维普 | Playwright / API | 需配置 |
| Elsevier Scopus | REST API | 机构授权 |
| Springer Nature | REST API | 免费 Key |

## 平台兼容性

| 功能 | Claude Code | Claude Desktop | OpenCode | Codex | Hermes |
|------|------------|---------------|----------|-------|--------|
| MCP 工具 | ✅ `mcp__server__tool` | ✅ 同上 | ✅ 自动映射 | ✅ 自动映射 | ✅ 通用名称 |
| Skill 自动加载 | ✅ | ✅ | ✅ `skill` 工具 | ✅ | ✅ |
| Python 脚本 (all) | ✅ | ✅ | ✅ | ✅ | ✅ |
| PowerShell (Win) | ✅ | ✅ | ✅ | ✅ | — |
| Bash (macOS/Linux) | ✅ | ✅ | ✅ | ✅ | ✅ |

---

[English Documentation](AGENTS.md)
