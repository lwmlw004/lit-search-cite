# 各数据源查询策略

## 通用原则

- 窄查询 → 精确结果；宽查询 → 多但噪声大
- 始终运行 2 种以上的查询变体：精确概念 + 更宽泛的同义词
- 中文课题加中文翻译作为单独查询

---

## Google Scholar（ai4scholar MCP / Playwright）

```
"exact phrase search"              # 引号精确匹配
allintitle: styrene shape memory   # 标题中全部包含
author:Goodfellow deep learning    # 作者检索
```

用 `year_from` / `year_to` 参数过滤年份，比在查询里写年份更可靠。

---

## Semantic Scholar（ai4scholar / 直连）

自然语言查询效果好。年份过滤：
```
year = "2020-2024"   # 范围
year = "2020-"        # 2020 年起
```

---

## PubMed（E-utilities / ai4scholar MCP）

| 字段限定 | 示例 |
|----------------|---------|
| `[Title/Abstract]` | `"styrene"[Title/Abstract]` |
| `[MeSH Terms]` | `"Polymers"[MeSH]` |
| `[Author]` | `Smith[Author]` |
| 日期范围 | `2020/01/01[PDAT]:2025/12/31[PDAT]` |

布尔运算符（大写）：`styrene AND polymer NOT "case report"[PT]`

---

## arXiv（直连 API）

务必加分类限定，否则"smart"会匹配 smart grid、smart wheelchair 等无关论文：
```
# 好：限定到材料科学
search_query=all:styrene+polymer+AND+(cat:cond-mat.mtrl-sci)

# 差：无分类限定
search_query=all:smart+polymer
```

| 分类 | 用途 |
|----------|---------|
| `cond-mat.mtrl-sci` | 材料 / 化学 / 高分子 |
| `physics.chem-ph` | 化学物理 |
| `cs.LG` / `cs.AI` / `cs.CL` | 机器学习 / AI / NLP |
| `q-bio` | 生物学 |

---

## OpenAlex（免费，2.5 亿篇）— 精确关键词策略

OpenAlex 按引用数排序而非语义相关性。宽泛查询返回泛泛的高引用综述。

```
# 差 — 返回 Nature Materials 综述，非苯乙烯专项论文
styrene smart polymer

# 好 — 具体材料 + 功能
styrene-butadiene-styrene strain sensor carbon nanotube

# 加年份和类型过滤
SEBS dielectric elastomer&filter=publication_year:>2020,primary_location.source.type:journal
```

用 `&select=` 排除 `abstract_inverted_index`（会导致 PS5.1 `ConvertFrom-Json` 报错）。

---

## CrossRef（免费，1.5 亿篇）— 降噪过滤

始终组合 `type:journal-article,has-abstract:true`，否则可能混入补充材料和书籍章节：

```
filter=type:journal-article,has-abstract:true
```

---

## CNKI / 知网（Playwright）

自然语言即可。知网支持布尔检索：
```
SU=形状记忆 AND SU=苯乙烯        # 主题
TI=大语言模型                     # 仅标题
AU=张三 AND SU=量子计算           # 作者 + 主题
```

`SU=`（主题）用于广度覆盖；`TI=` 用于精确检索。

---

## 多数据源组合策略

```bash
# 快速上手 — 一条命令，3 个数据源，自动去重 + 等级标注
python scripts/multi-search.py -q "styrene smart material" -d chemistry

# 手动并行（精细控制时用）：
# Terminal 1: Invoke-RestMethod OpenAlex
# Terminal 2: Invoke-RestMethod CrossRef
# Terminal 3: Invoke-RestMethod PubMed E-utilities
```

---

## 查询扩展技巧

**结果太少：** 同义词 → 更广概念 → 相关领域 → 引文链追踪。  
**结果太多：** 加年份 → 加领域限定词 → 最小引用数过滤 → 切换更精准的数据源。
