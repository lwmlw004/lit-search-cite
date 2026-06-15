# 可选 API 参考

以下 API 均为可选增强。不配置任何 API，Skill 仍可通过核心搜索路径正常工作。

---

## OneScholar API（期刊等级查询，推荐）

**功能：** JCR 分区、中科院分区、影响因子、CiteScore、50+ 中国高校期刊认定等级。

**注册：** https://www.scigreat.com/s/app/?t=oneapi-info  
免费版：1,000 次/天，1 次/秒，每次最多 5 个期刊。

**调用格式：**
```http
POST https://api.scigreat.com/info/getrank
Authorization: Bearer <ONESCHOLAR_API_KEY>
Content-Type: application/json

[{"journal": ["Nature"]}, {"journal": ["Science"]}]
```

**Python 脚本（推荐）：**
```bash
python scripts/journal-rank.py -j "Nature" "Science" "Advanced Materials"
```
处理了批量查询、缓存和离线回退。

---

## Semantic Scholar API（214M 篇论文，免费 Key）

**注册：** https://www.semanticscholar.org/product/api（1-2 个工作日审批）

**搜索端点：**
```
GET https://api.semanticscholar.org/graph/v1/paper/search
  ?query=styrene+polymer&limit=10&fields=title,year,citationCount,venue
x-api-key: <SEMANTIC_SCHOLAR_API_KEY>
```

> 匿名模式理论上支持，实测几乎每次返回 429，必须有 Key。

---

## Elsevier Scopus（7800 万篇论文，需机构授权）

**注册：** https://dev.elsevier.com/apikey/manage

**搜索端点：**
```
GET https://api.elsevier.com/content/search/scopus
  ?query=TITLE-ABS-KEY(styrene+polymer)&count=10
X-ELS-APIKey: <ELSEVIER_API_KEY>
```

---

## Springer Nature OA（免费 Key）

**注册：** https://dev.springernature.com/

**搜索端点：**
```
GET https://api.springernature.com/openaccess/json
  ?q=styrene+polymer&api_key=<SPRINGER_API_KEY>&p=10
```

覆盖 16,000+ 开放获取论文的全文元数据。

---

## Web of Science（付费授权）

**注册：** https://developer.clarivate.com/apis/wos（无免费版）

Gold-standard 引用指标。需机构购买 WoS 许可。
