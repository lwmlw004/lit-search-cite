# Query Strategies by Source

## General Principles

- Narrow query → specific results; broad query → many but noisy
- Always run 2+ variants: one exact concept, one broader synonym
- For Chinese topics, add the Chinese translation as a separate query

---

## Google Scholar (ai4scholar MCP / Playwright)

```
"exact phrase search"              # quotes
allintitle: styrene shape memory   # all words in title
author:Goodfellow deep learning    # author search
```

Use `year_from` / `year_to` parameters — more reliable than in-query years.

---

## Semantic Scholar (ai4scholar / direct)

Natural language works well. Year filtering:
```
year = "2020-2024"   # range
year = "2020-"       # from 2020
```

---

## PubMed (E-utilities / ai4scholar MCP)

| Field qualifier | Example |
|----------------|---------|
| `[Title/Abstract]` | `"styrene"[Title/Abstract]` |
| `[MeSH Terms]` | `"Polymers"[MeSH]` |
| `[Author]` | `Smith[Author]` |
| Date range | `2020/01/01[PDAT]:2025/12/31[PDAT]` |

Boolean (uppercase): `styrene AND polymer NOT "case report"[PT]`

---

## arXiv (direct API)

Always add category filter to avoid noise:
```
# Good: category-limited
search_query=all:styrene+polymer+AND+(cat:cond-mat.mtrl-sci)

# Bad: no category → returns smart grid, smart wheelchair, etc.
search_query=all:smart+polymer
```

| Category | Use for |
|----------|---------|
| `cond-mat.mtrl-sci` | Materials / Chemistry / Polymers |
| `physics.chem-ph` | Chemical Physics |
| `cs.LG` / `cs.AI` / `cs.CL` | ML / AI / NLP |
| `q-bio` | Biology |

---

## OpenAlex (Path F) — Precision Keyword Strategy

OpenAlex sorts by citation count, not semantic relevance. Broad queries return generic high-citation reviews.

```
# Bad — returns Nature Materials reviews, not styrene-specific papers
styrene smart polymer

# Good — specific material + function
styrene-butadiene-styrene strain sensor carbon nanotube

# With year + type filter
SEBS dielectric elastomer&filter=publication_year:>2020,primary_location.source.type:journal
```

Use `&select=` to exclude `abstract_inverted_index` (breaks PS5.1 `ConvertFrom-Json`).

---

## CrossRef (Path G) — Noise Filtering

Always combine `type:journal-article,has-abstract:true` — CrossRef may return supplementary files and book chapters without it.

```
filter=type:journal-article,has-abstract:true
```

---

## CNKI / 知网 (Playwright)

Natural language works. CNKI supports Boolean field codes:
```
SU=形状记忆 AND SU=苯乙烯        # Topic
TI=大语言模型                     # Title only
AU=张三 AND SU=量子计算           # Author + topic
```

`SU=` (主题) for broad coverage; `TI=` for precision.

---

## Multi-Source Strategy

```powershell
# Quick start — one command, 3 sources, auto dedup + tier
.\scripts\multi-search.ps1 -Query "styrene smart material" -Domain chemistry

# Manual parallel (fine-grained control):
# Terminal 1: Invoke-RestMethod OpenAlex
# Terminal 2: Invoke-RestMethod CrossRef
# Terminal 3: Invoke-RestMethod PubMed E-utilities
```

---

## Query Expansion

**Too few results:** synonym → broader concept → related domain → citation chaining.  
**Too many:** add year range → domain qualifier → minimum citation filter → switch to more precise source.
