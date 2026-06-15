# Optional API Reference

All APIs in this file are optional enhancements. The skill works without any of them using the core search paths.

> **Status as of 2026-06-14:** OneScholar, Elsevier Scopus, and Semantic Scholar APIs have been tested and verified working.

---

## OneScholar API (SciGreat) ✅ Verified

**What it adds:** Journal JCR quartile, CAS zone (中科院分区), Impact Factor, CiteScore, and 50+ Chinese university-specific journal rankings in a single API call.

**Registration:** https://www.scigreat.com/s/app/?t=oneapi-info  
Free base tier: 30 journal queries/day; Membership ¥2.0–2.5/month for 100/day

**Env var:** `ONESCHOLAR_API_KEY`

**Call format (array body, max 5 per request):**
```http
POST https://api.scigreat.com/info/getrank
Authorization: Bearer <ONESCHOLAR_API_KEY>
Content-Type: application/json

[{"journal": ["Nature"]}, {"journal": ["Science"]}]
```

**Full verified response example (Nature, ISSN 0028-0836):**
```json
{
  "imf": 48.5,           // Impact Factor (最新)
  "if5": 55,             // 5年 Impact Factor
  "jci": 11.14,          // Journal Citation Indicator
  "jcr": "Q1",           // JCR 分区
  "cas": "1区",          // 中科院基础版分区
  "cas_top": "中科院 Top", // 中科院 Top 期刊标识
  "xr": "1区",           // 中科院升级版（新锐）分区
  "xr_top": "新锐 Top",
  "citescore": 77.7,     // CiteScore
  "sjr": 19.713,         // SCImago Journal Rank
  "wos_core": "SCIE",    // WoS 数据库收录
  "nij": "Nature Index", // Nature Index 期刊
  "istic": "Q1",         // 中国科学院文献情报中心分级
  "jcar_risk": "低风险",  // 预警等级
  "hust": "A",  "sjtu": "A+",  "nju": "综合顶级",  // 高校认定等级示例
  ...                    // 50+ 高校各自的期刊等级
}
```

**Display format for search results:**
```
IF: 48.5 | JCR Q1 | CAS 1区 Top | CiteScore: 77.7 | Nature Index
```

**Batch query (max 5 per request, array format):**
```json
[{"issn": ["0028-0836"]}, {"issn": ["0036-8075"]}, {"journal": ["Nature Materials"]}]
```
Each object in the array is one query. Mix ISSN and journal name freely.

**University ranking query:**
```json
{"university": ["Tsinghua University", "MIT", "Stanford University"]}
```

---

## Semantic Scholar API ✅ Verified (Path B — standalone)

See `api-setup.md` → "Path B" for full configuration and call format.

**Registration:** https://www.semanticscholar.org/product/api  
**Free, authenticated rate:** 1 RPS dedicated (vs. shared anonymous pool)  
**Coverage:** 214M papers across all disciplines

---

## Elsevier (Scopus + ScienceDirect) ✅ Verified

**What it adds:** Scopus indexes 78M items; ScienceDirect provides full-text for Elsevier journals.

**Registration:** https://dev.elsevier.com/apikey/manage  
- Non-commercial/academic: free with institutional affiliation
- Commercial: requires Elsevier licensing

**Env var:** `ELSEVIER_API_KEY`  
**Authentication:** `X-ELS-APIKey: <key>` header (NOT Bearer format)

**Verified search call:**
```http
GET https://api.elsevier.com/content/search/scopus
  ?query=TITLE-ABS-KEY(transformer+neural+network)
  &count=10
  &field=title,publicationName,coverDate,citedby-count,doi,creator
X-ELS-APIKey: <ELSEVIER_API_KEY>
Accept: application/json
```

**Key query operators:**
```
TITLE-ABS-KEY(...)     — search title, abstract, keywords
TITLE(...)             — title only
AF-ID(60031834)        — by institution Scopus ID
SRCNAME("Nature")      — by source/journal name
PUBYEAR > 2020         — year filter
DOCTYPE(ar)            — article type: ar=article, re=review, cp=conference paper
```

**Python SDK:** `pip install elsapy`

**Rate limits:** Varies by subscription; institutional access typically 2-6 req/sec.

---

## Web of Science (Clarivate)

**What it adds:** Gold-standard citation metrics, Journal Impact Factor (JIF), field-normalized citation analysis.

**Registration:** https://developer.clarivate.com/apis/wos  
**No free tier** — requires paid WoS license (typically institutional). Contact your library.

**Env var:** `WOS_API_KEY`  
**Authentication:** `X-ApiKey: <key>` header

**Search endpoint:**
```http
GET https://api.clarivate.com/apis/wos-starter/v1/documents
  ?db=WOS&q=AI%3Amachine+learning&limit=10
X-ApiKey: <WOS_API_KEY>
```

**Swagger docs:** https://developer.clarivate.com/apis/wos/swagger  
**Rate limits:** 2 req/sec (Basic plan); 50,000 full records/year

---

## Springer Nature

**What it adds:** 3M+ articles from Springer, Nature family, and Palgrave; open-access full-text retrieval.

**Registration:** https://dev.springernature.com/ — free API key, register an application  
**Env var:** `SPRINGER_API_KEY`

> ⚠️ **端点说明（实测）：** `/meta/v2/json` 需要机构授权（免费 key 返回 401）。使用 `/openaccess/json` — 免费 key 可用（已验证返回 200，覆盖 16,000+ OA 论文）。

**Search endpoint（已验证可用，用此端点）:**
```http
GET https://api.springernature.com/openaccess/json
  ?q=transformer+medical+imaging
  &api_key=<SPRINGER_API_KEY>
  &p=10
```

**按 DOI 获取全文（openaccess）:**
```http
GET https://api.springernature.com/openaccess/json
  ?q=doi:10.1038/s41586-021-03819-2
  &api_key=<SPRINGER_API_KEY>
```

**Rate limits:** 10 req/sec; no documented daily cap on metadata.

---

## Wiley (Text & Data Mining)

**What it adds:** Full-text access to 1,600+ Wiley journals (chemistry, ecology, social sciences).

**Registration:** https://onlinelibrary.wiley.com/library-info/resources/text-and-data-mining  
Requires institutional subscription or TDM agreement. Contact your library.

**Env var:** `WILEY_TDM_TOKEN`  
**Usage:** Primarily for full-text retrieval by DOI after finding papers via search. Not a search API.

---

## CAS SciFinder-n

**What it adds:** 200M+ substance records, reaction data, patent chemistry — the most comprehensive chemistry database.

**Registration:** https://www.cas.org/products/scifinder-solutions/api-overview  
Commercial/institutional licensing only; no free tier.

**Use case:** Chemistry, materials science, pharmaceutical research, patent chemistry searches.

---

## Quick Decision Guide

| Need | Use |
|---|---|
| Fast setup, no cost | Semantic Scholar direct API (Path B) |
| Multi-source (PubMed + GS + S2) | ai4scholar MCP (Path A) |
| Journal tier / 中科院分区 | OneScholar API (recommended) |
| Chinese literature 知网 | scansci-pdf CARSI login |
| Elsevier full-text / Scopus | Elsevier API (institutional) |
| Citation impact metrics | Web of Science (institutional, paid) |
| Springer Nature full-text | Springer API (free key) |
| Chemistry / materials | CAS SciFinder (institutional) |
