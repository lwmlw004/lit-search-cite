# API 配置指南

核心搜索和下载 API。所有端点示例包含 PowerShell（Windows）和 Bash（macOS/Linux）。

---

## 速查表 — 各路径所需配置

| 路径 | API | 需要 Key？ | 最适合 |
|------|-----|--------------|----------|
| A1 | ai4scholar MCP（Google Scholar + S2 + PubMed） | `AI4SCHOLAR_API_KEY` | 多源，最快 |
| A2 | ai4scholar REST API（S2） | `AI4SCHOLAR_API_KEY` | 无需 MCP |
| B | Semantic Scholar 直连 | `SEMANTIC_SCHOLAR_API_KEY` | S2 专线备选 |
| C | PubMed E-utilities | 免费 | 生物医学 |
| D | arXiv API | 免费 | CS / 物理 / 数学 |
| E | scansci-pdf MCP | 免费 | PDF 下载 |
| F | OpenAlex | 免费 | 通用（2.5 亿篇） |
| G | CrossRef | 免费 | DOI 注册论文 |
| I | `multi-search.py` | 免费 | 一键多源 |

---

## Path A1/A2 — ai4scholar（Google Scholar + Semantic Scholar + PubMed）

一个 Key，三个数据库。MCP 模式（A1）用于工具调用；REST 模式（A2）用于直接 HTTP。

### REST API（Path A2，无需 MCP）

```
GET https://ai4scholar.net/graph/v1/paper/search
  ?query=<关键词>&limit=10
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
curl "https://ai4scholar.net/graph/v1/paper/search?query=styrene+polymer&limit=10" -H "Authorization: Bearer $AI4SCHOLAR_API_KEY"
```

其他端点：`/paper/{id}/citations`、`/paper/{id}/references`、`/author/search`。

---

## Path B — Semantic Scholar 直连 API

免费 Key：https://www.semanticscholar.org/product/api（1-2 天审批）。

> 匿名池几乎永远返回 429，必须申请 Key。

```
GET https://api.semanticscholar.org/graph/v1/paper/search
  ?query=<关键词>&limit=10&fields=title,year,citationCount,venue
x-api-key: <SEMANTIC_SCHOLAR_API_KEY>
```

**PowerShell:**
```powershell
$r = Invoke-RestMethod "https://api.semanticscholar.org/graph/v1/paper/search?query=styrene+block+copolymer&limit=10&fields=title,year,citationCount,venue" -Headers @{"x-api-key"=$env:SEMANTIC_SCHOLAR_API_KEY}
```

---

## Path C — PubMed E-utilities（免费）

两步：搜索获取 ID → 批量获取摘要。无需 Key。

```powershell
# 1. 搜索
$s = Invoke-RestMethod "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=styrene+smart+material&retmax=10&retmode=json&sort=relevance"
$ids = $s.esearchresult.idlist -join ","

# 2. 获取摘要
$sum = Invoke-RestMethod "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=$ids&retmode=json"
```

MeSH 限定词：`[Title/Abstract]`、`[MeSH Terms]`、`[Author]`、`[Journal]`。  
完整语法见 `search-strategies.md`。

---

## Path D — arXiv API（免费）

返回 Atom XML。务必加分类过滤避免噪声。

```
GET https://export.arxiv.org/api/query
  ?search_query=all:styrene+polymer+AND+(cat:cond-mat.mtrl-sci)
  &max_results=10&sortBy=relevance
```

**PowerShell:**
```powershell
$r = Invoke-WebRequest "https://export.arxiv.org/api/query?search_query=all:styrene+polymer+AND+(cat:cond-mat.mtrl-sci)&max_results=10&sortBy=relevance" -UseBasicParsing
# 解析：[regex]::Matches($r.Content, '<entry>.*?<title>(.*?)</title>', 'Singleline')
```

| 分类 | 用途 |
|----------|---------|
| `cond-mat.mtrl-sci` | 材料 / 化学 |
| `physics.chem-ph` | 化学物理 |
| `cs.LG` | 机器学习 |
| `q-bio` | 生物学 |

---

## Path F — OpenAlex（免费，2.5 亿篇）

无 Key。按引用数排序。用精确关键词。

```
GET https://api.openalex.org/works
  ?search=<关键词>&per-page=10&sort=cited_by_count:desc
  &select=id,doi,title,publication_year,cited_by_count,authorships,primary_location,open_access
```

**PowerShell（PS5.1 必须用 `select=` 排除 `abstract_inverted_index`）：**
```powershell
$q = [uri]::EscapeDataString("styrene-butadiene-styrene strain sensor")
$r = Invoke-RestMethod "https://api.openalex.org/works?search=$q&per-page=10&sort=cited_by_count:desc&select=id,doi,title,publication_year,cited_by_count,authorships,primary_location,open_access"
```

年份过滤：`&filter=publication_year:>2022`

---

## Path G — CrossRef（免费，1.5 亿篇）

相关性比 OpenAlex 好。组合 `type:journal-article,has-abstract:true` 过滤噪声。

```
GET https://api.crossref.org/works
  ?query=<关键词>&rows=10&sort=relevance
  &filter=type:journal-article,has-abstract:true
```

**PowerShell:**
```powershell
$q = [uri]::EscapeDataString("styrene block copolymer self-healing")
$r = Invoke-RestMethod "https://api.crossref.org/works?query=$q&rows=10&sort=relevance&filter=type:journal-article,has-abstract:true"
# $r.message.items → title[0], DOI, is-referenced-by-count
```

---

## Path I — multi-search.py（一条命令，全部免费 API）

```bash
python scripts/multi-search.py -q "styrene smart polymer" -d chemistry -t 20
python scripts/multi-search.py -q "..." --online-rank        # + OneScholar 在线期刊等级
python scripts/multi-search.py -q "..." --year-from 2022 --year-to 2025
```

包装 Path C/D/F/G。自动去重、等级标注、格式化输出。

---

## 期刊等级 — journal-rank.py

离线或在线（OneScholar API）。适配任意搜索路径的结果。

```bash
# 批量查询，每批 5 个，缓存 30 天，回退到 300+ 期刊离线库
python scripts/journal-rank.py -j "Nature" "Adv. Mater." "JACS" --quiet
# → IF=48.5 JCR-Q1 CAS-1区 CAS-Top
```

离线库：`references/journal-ranks.json`（300+ 期刊，免费，无 Key）。

---

## OneScholar API（在线期刊等级）

```http
POST https://api.scigreat.com/info/getrank
Authorization: Bearer <ONESCHOLAR_API_KEY>
Content-Type: application/json

[{"journal": ["Nature"]}, {"journal": ["Science"]}]
```

免费：1,000 次/天，1 次/秒，每次最多 5 个期刊。推荐直接用 `journal-rank.py`，它处理了批量、缓存和回退。

---

## PDF 下载

**主方案（MCP）：**
```
scansci_pdf_smart_download(identifier="10.xxxx/..." 或 "arXiv ID")
```

**备选（无 MCP）：**
```bash
python scripts/pdf-fetch.py --doi "10.xxxx/..."
# 回退链：Unpaywall → OpenAlex → EuropePMC → Sci-Hub URL
```

付费论文：一次性浏览器登录（`scansci_pdf_import_browser_cookies` / `carsi_login` / `ezproxy_login`）→ 保存 Cookie → 永久无头下载。

---

## CNKI / 知网（中文）

无 REST API。通过 `cnki-playwright.py`（Playwright 浏览器引擎）访问：

```bash
python scripts/cnki-playwright.py --setup --school scau      # 一次性 VPN 配置
python scripts/cnki-playwright.py --query "形状记忆 聚合物" --limit 20  # 无头搜索
```

万方 API（结构化中文结果）：https://open.wanfangdata.com.cn/ 注册 → 设置 `WANFANG_API_KEY`。

---

## 配置文件

`~/.lit-search-cite/config.json` — 由 `setup.ps1` 创建：

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

所有脚本自动读取此文件。环境变量作为回退方案。
