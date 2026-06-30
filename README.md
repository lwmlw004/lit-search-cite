# lit-search-cite

> 多源学术文献检索、期刊等级查询、自动引用标注、PDF 下载 —— AI 编程助手的学术 Skill

一键安装：

```bash
npx lit-search-cite@latest
```

自动适配 Claude Code / Claude Desktop / OpenCode / Codex / Hermes。

---

## 功能

- **文献检索** — OpenAlex、CrossRef、PubMed、arXiv（零配置）；Semantic Scholar、Google Scholar（ai4scholar MCP）；CNKI（OpenCLI，复用浏览器登录态）；万方（API Key）
- **网页文献抓取** — 从 URL、保存的 HTML、复制文本、PubMed/arXiv/出版社页、搜索结果页、参考文献列表中提取 DOI 和文献元数据
- **期刊等级** — OneScholar 在线 API（IF / JCR / CAS / CiteScore）+ 300+ 期刊离线库（无需 Key）
- **PDF 下载** — scansci-pdf MCP（13+ 来源：Springer Direct / ElsevierAPI / OA 库 / Sci-Hub）；付费墙兜底：OpenCLI（零额外配置，复用机构登录，Wiley 实测 6.2MB 真实 PDF）
- **引用标注** — GB/T 7714 / APA / IEEE / MLA / Chicago / Nature / Vancouver
- **综述写作** — 多轮搜索 + 论文聚类 + 结构化草稿

## 快速开始

```bash
# 英文文献（零配置）
python scripts/multi-search.py -q "styrene shape memory polymer" -d chemistry

# 带在线期刊等级
python scripts/multi-search.py -q "transformer attention mechanism" -d cs --online-rank

# 年份过滤
python scripts/multi-search.py -q "cancer immunotherapy" -d biomedicine --year-from 2022 -t 20

# 从网页自动抓取文献
python scripts/web-capture.py --url "https://example.com/article" --out references/captured --format bibtex,ris,csv,md,json

# 期刊等级查询（需 OneScholar Key）
python scripts/journal-rank.py -j "Nature" "Science" "Advanced Materials"

# PDF 下载（需 scansci-pdf MCP）
# 告诉 Claude："下载 DOI 10.1038/s41586-021-03819-2 的 PDF"

# 中文文献（需 OpenCLI，Chrome 中已登录知网）
# 告诉 Claude："帮我在知网搜索「大语言模型 代码生成」"
```

## 安装

```bash
npx lit-search-cite@latest                    # 自动检测所有平台（推荐）
npx lit-search-cite@latest --claude           # 仅 Claude Code / Claude Desktop
npx lit-search-cite@latest --opencode         # 仅 OpenCode
npx lit-search-cite@latest --codex            # 仅 Codex
npx lit-search-cite@latest --agents           # 仅 Agent Skills (.agents)
npx lit-search-cite@latest --target ~/my-skills      # 自定义路径
```

每次安装会先清空旧目录再写入，重复运行安全。安装内容仅包含 `SKILL.md`、`AGENTS.md`、`scripts/`、`references/`、`docs/`、`evals/`。

或手动复制到平台对应的 skills 目录：

| 平台 | 目录（全局） | 目录（项目级） |
|------|------------|--------------|
| Claude Code / Claude Desktop | `~/.claude/skills/lit-search-cite/` | `.claude/skills/lit-search-cite/` |
| OpenCode | `~/.config/opencode/skills/lit-search-cite/` | `.opencode/skills/lit-search-cite/` |
| Codex | `~/.codex/skills/lit-search-cite/` | `.codex/skills/lit-search-cite/` |
| 通用 Agent Skills | `~/.agents/skills/lit-search-cite/` | `.agents/skills/lit-search-cite/` |

## 脚本

| 脚本 | 平台 | 说明 |
|------|------|------|
| `multi-search.py` | 全平台 | 一键多源搜索（OpenAlex/CrossRef/PubMed/arXiv）+ DOI 去重 + 期刊等级 |
| `multi-search.ps1` | Windows | 同上，PowerShell 版 |
| `web-capture.py` | 全平台 | 从 URL/HTML/复制文本抓取网页文献，导出 BibTeX/RIS/CSV/Markdown/JSON |
| `web-capture.ps1` | Windows | 同上，PowerShell 包装脚本 |
| `test-web-capture.py` | 全平台 | `web-capture.py` 的无网络样例测试 |
| `journal-rank.py` | 全平台 | OneScholar API 期刊等级查询（需 Key） |
| `journal-rank.ps1` | Windows | 同上，PowerShell 版，支持 ISSN 查询 |
| `pdf-fetch.py` | 全平台 | PDF 下载回退链（DOI 输入，Unpaywall → OpenAlex → EuropePMC） |
| `pdf-fetch.ps1` | Windows | 同上，PowerShell 版 |
| `cnki-search.ps1` | Windows | 万方 API + CNKI/百度学术/维普 浏览器 URL 生成 |
| `check-deps.ps1` | Windows | 依赖检查 |
| `setup.ps1` | Windows | API Key 配置向导 |

## 从网页自动抓取文献

`web-literature-capture` 由 `scripts/web-capture.py` 提供，优先读取 HTML meta、JSON-LD、PubMed/arXiv 页面线索和 DOI 正则；有 DOI 时按 CrossRef → OpenAlex 补全，没有 DOI 时用标题尝试 CrossRef/OpenAlex fallback。每次运行写入 `references/captured/YYYYMMDD_HHMMSS/`，包含 `captured.json`、`captured.csv`、`captured.bib`、`captured.ris`、`captured.md`、`dois.txt`、`failed.txt`、`run_report.md`。

```bash
# 1. 单篇出版社页面
python scripts/web-capture.py --url "https://example.com/article" --out references/captured --pdf legal

# Windows 推荐写法
py -3 scripts\web-capture.py --url "https://example.com/article" --out references\captured --pdf legal

# 2. PubMed 页面
python scripts/web-capture.py --url "https://pubmed.ncbi.nlm.nih.gov/12345678/" --out references/captured

# 3. 搜索结果页 / 期刊目录页
python scripts/web-capture.py --url "https://example.com/search?q=catalyst" --limit 50 --year-from 2020

# 4. 参考文献列表或复制文本
python scripts/web-capture.py --text copied-references.txt --dedupe doi --format bibtex,ris,csv,md

# 5. 抓取后交给 OneFind / Zotero / EndNote 做本地知识库
python scripts/web-capture.py --url "https://example.com/references" --out references/captured --format bibtex,ris,csv,md,json
```

真实出版社网页可能返回 HTTP 403，这是正常情况，不代表解析器失败。如果 URL 本身含 DOI、PMID 或 arXiv ID，脚本会 fallback 到 identifier 再用公开元数据源补全；更稳定的方式是在浏览器里把网页另存为 HTML 后运行 `--html page.html`。因此 live URL 测试不应作为唯一验收标准，本地 HTML 和文本 fixture 同样是必要验收。

如果 PowerShell execution policy 阻止 `.ps1` 执行，可用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\web-capture.ps1 -Url "https://example.com/article" -Out "references\captured" -Pdf legal
```

本地无网络测试样例位于 `evals/web-capture/`，覆盖 publisher meta、JSON-LD article、PubMed-like page、arXiv-like page、reference list text 和 noisy reference list text。

`run_report.md` 中常见 PDF 状态：

| 状态 | 含义 |
|------|------|
| `not_requested` | 未传入 `--pdf legal`，没有尝试 PDF 获取 |
| `not_found_or_paywalled` | 已尝试合法开放来源，但没有找到开放 PDF，或可能在付费墙后 |
| `found_url_download_failed` | 找到了候选 PDF URL，但下载失败、返回非 PDF 或被网络/站点拦截 |
| `downloaded` | 已成功保存合法开放 PDF 到本次输出目录 |

开放 PDF 获取仅在 `--pdf legal` 时启用，来源限制为出版社明确给出的开放 PDF、Unpaywall、OpenAlex OA location、EuropePMC/PubMed Central 和 arXiv；不会在 `web-capture.py` 中内置 Sci-Hub、LibGen、Anna's Archive 或绕过付费墙逻辑。OneFind 工作流见 `docs/onefind-workflow.md`，scansci-pdf 可选衔接见 `docs/scansci-pdf-integration.md`，浏览器辅助见 `docs/browser-capture.md`。

## 支持的文献源

| 数据源 | 规模 | 费用 |
|--------|------|------|
| OpenAlex | 2.5 亿篇 | 免费 |
| CrossRef | 1.5 亿篇 | 免费 |
| PubMed | 3,600 万篇 | 免费 |
| arXiv | 200 万+ 篇 | 免费 |
| Semantic Scholar | 2.14 亿篇 | 免费 Key |
| Google Scholar | — | ai4scholar MCP Key |
| CNKI / 知网 | — | OpenCLI（浏览器登录态，零额外配置） |
| 万方 | — | API Key |
| 百度学术 / 维普 | — | 浏览器 URL |
| Elsevier Scopus | 7,800 万篇 | 机构授权 |
| Springer Nature OA | — | 免费 Key |

## MCP 配置

详见 `references/mcp-template.md`，支持三种配置级别：

| 级别 | MCP | 适用场景 |
|------|-----|---------|
| 最小 | scansci-pdf | 仅 OA PDF 下载 |
| 推荐 | ai4scholar + scansci-pdf | 全功能搜索 + 多源下载 |
| 完整 | ai4scholar + scansci-pdf | 同上（付费墙兜底由 OpenCLI CLI 提供，非 MCP） |

## 兼容平台

Claude Code · Claude Desktop · OpenCode · Codex · Hermes

---

[English](AGENTS.md) · [Setup Guide](references/setup-guide.md) · [OpenCLI Browser](references/opencli.md) · [Chrome DevTools MCP (legacy)](references/chrome-devtools.md)
