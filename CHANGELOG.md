# 更新日志

## v1.0.0 (2026-06-15)

### 核心功能

- **多源文献检索**: OpenAlex、CrossRef、PubMed、arXiv、Semantic Scholar、Google Scholar（MCP + Playwright）、CNKI（Playwright）、Elsevier Scopus、Springer Nature
- **期刊等级查询**: OneScholar API + 300+ 期刊离线库，支持 CAS/JCR/CCF/IF
- **PDF 下载**: scansci-pdf MCP（13+ 来源）+ pdf-fetch 回退链（Unpaywall → OpenAlex → EuropePMC → Sci-Hub）
- **自动引用**: 手动工作流，支持 APA、GB/T 7714、IEEE、MLA、Chicago、Nature、Vancouver
- **综述写作**: 多轮搜索、论文聚类、结构化草稿生成

### 脚本

| 脚本 | 平台 | 说明 |
|--------|----------|-------------|
| `multi-search.py` | 全平台 | 一键多源搜索 + 去重 + 期刊等级 |
| `multi-search.ps1` | Windows | PowerShell 版（同功能） |
| `journal-rank.py` | 全平台 | OneScholar API + 离线库期刊等级查询 |
| `journal-rank.ps1` | Windows | PowerShell 版（同功能） |
| `pdf-fetch.py` | 全平台 | PDF 下载回退链 |
| `pdf-fetch.ps1` | Windows | PowerShell 版（同功能） |
| `cnki-playwright.py` | 全平台 | 知网搜索 + 76 所高校 VPN 配置 |
| `cnki-search.ps1` | Windows | 中文文献检索（万方 API + 浏览器链接） |
| `google-scholar.py` | 全平台 | Google Scholar Playwright 方案（配置后无头运行） |
| `check-deps.ps1` | Windows | 依赖检查 |
| `setup.ps1` | Windows | API Key 配置向导 |

### 文档

- `SKILL.md` — 核心 Skill 指令（5 种模式，平台通用）
- `README.md` — 中文文档（GitHub 默认展示）
- `AGENTS.md` — 英文文档
- `references/api-setup.md` — 全部 API 端点及 PowerShell + Bash 示例
- `references/setup-guide.md` — 完整安装指南
- `references/search-strategies.md` — 各数据源查询语法
- `references/optional-apis.md` — OneScholar、Elsevier、Springer、WoS 配置
- `references/journal-ranks.json` — 300+ 期刊离线等级库
- `references/mcp-template.json` — MCP 服务器配置模板

### 平台支持

- Claude Code、Claude Desktop、OpenCode、Codex、Hermes
- Windows（PowerShell + Python）、macOS/Linux（Python）
- 符合 Agent Skills 标准（`compatibility` 字段声明）
