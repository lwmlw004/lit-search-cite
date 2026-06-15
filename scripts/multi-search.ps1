<#
.SYNOPSIS
    统一多源学术文献搜索 + DOI 去重 + 格式化输出。
    覆盖 OpenAlex、CrossRef、PubMed、arXiv 四个免费 API（零配置）。

.DESCRIPTION
    根据领域自动选择最佳数据源组合，并行搜索，按 DOI 去重，统一格式化输出。
    同时从本地 journal-ranks.json 查找期刊等级信息，可选 OneScholar API 在线查询。

.PARAMETER Query
    搜索关键词（英文）

.PARAMETER Domain
    学科领域：cs | engineering | biomedicine | biology | physics | chemistry | social | humanities | general
    决定数据源组合策略。

.PARAMETER YearFrom
    起始年份过滤（如 2020）

.PARAMETER YearTo
    结束年份过滤（如 2025）

.PARAMETER Limit
    每个数据源最大返回数 (default: 15)

.PARAMETER TotalLimit
    去重后最多保留的论文数 (default: 30)

.PARAMETER Sources
    手动指定数据源（逗号分隔）: openalex,crossref,pubmed,arxiv
    如指定此参数则忽略 Domain。

.PARAMETER NoDedup
    跳过 DOI 去重步骤

.PARAMETER OnlineRank
    启用 OneScholar API 在线查询期刊等级（需配置 api_keys.onescholar，免费30次/天）

.EXAMPLE
    .\multi-search.ps1 -Query "styrene shape memory polymer" -Domain chemistry
    .\multi-search.ps1 -Query "transformer attention mechanism" -Domain cs -YearFrom 2022
    .\multi-search.ps1 -Query "cancer immunotherapy" -Domain biomedicine -TotalLimit 50 -OnlineRank
    .\multi-search.ps1 -Query "graphene battery" -Sources openalex,crossref -Limit 20
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$Query,

    [ValidateSet("cs","engineering","biomedicine","biology","physics","chemistry","social","humanities","general")]
    [string]$Domain = "general",

    [int]$YearFrom = 0,
    [int]$YearTo = 0,
    [int]$Limit = 15,
    [int]$TotalLimit = 30,
    [string]$Sources = "",
    [switch]$NoDedup,
    [switch]$OnlineRank
)

$ErrorActionPreference = "SilentlyContinue"

# ── Source routing by domain ───────────────────────────────────────────────────
$DefaultSources = @{
    "cs"          = @("openalex","arxiv")
    "engineering" = @("openalex","crossref")
    "biomedicine" = @("pubmed","openalex","crossref")
    "biology"     = @("pubmed","openalex")
    "physics"     = @("arxiv","openalex","crossref")
    "chemistry"   = @("openalex","crossref","pubmed")
    "social"      = @("openalex","crossref")
    "humanities"  = @("crossref")
    "general"     = @("openalex","crossref","pubmed")
}

$activeSources = if ($Sources) {
    $Sources -split ',' | ForEach-Object { $_.Trim().ToLower() }
} else {
    $DefaultSources[$Domain]
}

Write-Host "" -ForegroundColor DarkGray
Write-Host "=== lit-search-cite: Multi-Source Search ===" -ForegroundColor Cyan
Write-Host "  Query   : $Query" -ForegroundColor DarkGray
Write-Host "  Domain  : $Domain" -ForegroundColor DarkGray
Write-Host "  Sources : $($activeSources -join ', ')" -ForegroundColor DarkGray
Write-Host ""

# ── Load journal ranks ─────────────────────────────────────────────────────────
$RankFile = Join-Path $PSScriptRoot "..\references\journal-ranks.json"
$Ranks = $null
if (Test-Path $RankFile) {
    try { $Ranks = Get-Content $RankFile -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { Write-Warning "Could not parse journal-ranks.json" }
}

function Get-JournalTier($journalName) {
    if (-not $journalName) { return "" }
    $key = $journalName.Trim().ToLower() -replace '^the\s+',''
    
    # ASCII-safe transliteration for PS5.1 console
    function tr($s) {
        if (-not $s) { return $s }
        $s = $s -replace '1区','Q1' -replace '2区','Q2' -replace '3区','Q3' -replace '4区','Q4'
        $s = $s -replace '中科院 Top','CAS-Top' -replace '新锐 Top','XR-Top'
        $s = $s -replace '低风险','LowRisk' -replace '中风险','MedRisk' -replace '高风险','HighRisk'
        $s = $s -replace '综合性期刊','MULTI'
        return $s
    }
    
    # 1. Prefer OneScholar online data (most accurate)
    if ($onlineRanks.ContainsKey($key)) {
        $j = $onlineRanks[$key]
        $tier = @()
        if ($j.IF)    { $tier += "IF=$($j.IF)" }
        if ($j.JCR)   { $tier += "JCR-$($j.JCR)" }
        if ($j.CAS)   { $tier += "CAS-$(tr $j.CAS)" }
        if ($j.CASTop){ $tier += $(tr $j.CASTop) }
        return ($tier -join ' ')
    }
    
    # 2. Fallback to local journal-ranks.json
    if (-not $Ranks) { return "" }
    if ($Ranks.journals.PSObject.Properties[$key]) {
        $j = $Ranks.journals.$key
        return "[$($j.tier)-$($j.level)] IF=$($j.if)"
    }
    if ($Ranks._aliases.PSObject.Properties[$key]) {
        $alias = $Ranks._aliases.$key
        $j = $Ranks.journals.$alias
        if ($j) { return "[$($j.tier)-$($j.level)] IF=$($j.if)" }
    }
    return ""
}

# ── Normalize DOI for dedup ────────────────────────────────────────────────────
function Normalize-DOI($doi) {
    if (-not $doi) { return "" }
    $d = $doi.Trim().ToLower()
    if ($d -match '10\.\d{4,}/') { return $matches[0] + ($d -replace '.*?10\.\d{4,}/','') }
    return $d
}

# ── Build year filter for OpenAlex ─────────────────────────────────────────────
$oaFilters = @()
if ($YearFrom -gt 0) { $oaFilters += "publication_year:>$($YearFrom-1)" }
if ($YearTo -gt 0)   { $oaFilters += "publication_year:<$($YearTo+1)" }
$oaFilterStr = if ($oaFilters.Count -gt 0) { "&filter=" + ($oaFilters -join ',') } else { "" }

# ── Build category filter for arXiv ─────────────────────────────────────────────
$ArxivCats = @{
    "cs"     = "cat:cs.LG+OR+cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.CV"
    "physics"= "cat:cond-mat.mtrl-sci+OR+cat:physics.app-ph+OR+cat:physics.chem-ph"
    "chemistry" = "cat:cond-mat.mtrl-sci+OR+cat:physics.chem-ph"
    "biology"   = "cat:q-bio"
    "engineering" = "cat:cond-mat.mtrl-sci"
}
$arxivCat = if ($ArxivCats.ContainsKey($Domain)) { "+AND+($($ArxivCats[$Domain]))" } else { "" }

# ── Build CrossRef type filter ──────────────────────────────────────────────────
$crFilter = "&filter=type:journal-article,has-abstract:true"

$allResults = @()
$encoded = [uri]::EscapeDataString($Query)
$fields = "id,doi,title,publication_year,cited_by_count,authorships,primary_location,open_access"

# ═══════════════════════════════════════════════════════════════════════════════
# Source 1: OpenAlex (Path F) — 2.5亿篇，免费
# ═══════════════════════════════════════════════════════════════════════════════
if ($activeSources -contains "openalex") {
    Write-Host "[OpenAlex] Searching..." -ForegroundColor Yellow
    try {
        $oaUrl = "https://api.openalex.org/works?search=$encoded&per-page=$Limit&sort=cited_by_count:desc&select=$fields$oaFilterStr&mailto=lit-search-cite@opencode.ai"
        $oaResp = Invoke-RestMethod $oaUrl -TimeoutSec 20
        $count = 0
        foreach ($w in $oaResp.results) {
            $authors = ($w.authorships | Select-Object -First 3 | ForEach-Object { $_.author.display_name }) -join "; "
            $venue = if ($w.primary_location.source.display_name) { $w.primary_location.source.display_name } else { "N/A" }
            $allResults += [PSCustomObject]@{
                Title     = $w.title
                Authors   = $authors
                Year      = $w.publication_year
                Venue     = $venue
                DOI       = $w.doi
                Citations = $w.cited_by_count
                Source    = "OpenAlex"
                OaUrl     = $w.open_access.oa_url
                Relevance = ""
            }
            $count++
        }
        Write-Host "[OpenAlex] Found $count results" -ForegroundColor Green
    } catch {
        Write-Warning "[OpenAlex] Failed: $($_.Exception.Message)"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Source 2: CrossRef (Path G) — 1.5亿+ DOI注册论文
# ═══════════════════════════════════════════════════════════════════════════════
if ($activeSources -contains "crossref") {
    Write-Host "[CrossRef] Searching..." -ForegroundColor Yellow
    try {
        $crUrl = "https://api.crossref.org/works?query=$encoded&rows=$Limit&sort=relevance$crFilter&mailto=lit-search-cite@opencode.ai"
        $crResp = Invoke-RestMethod $crUrl -TimeoutSec 20
        $count = 0
        foreach ($w in $crResp.message.items) {
            if (-not $w.title -or -not $w.title[0]) { continue }
            $year = try { if ($w.published.'date-parts' -and $w.published.'date-parts'.Count -gt 0 -and $w.published.'date-parts'[0].Count -gt 0) { $w.published.'date-parts'[0][0] } else { 0 } } catch { 0 }
            if ($YearFrom -gt 0 -and $year -lt $YearFrom) { continue }
            if ($YearTo -gt 0 -and $year -gt $YearTo) { continue }
            $authors = try { ($w.author | Select-Object -First 3 | ForEach-Object { if ($_.family) { "$($_.family), $($_.given.substring(0,1))" } else { "" } } | Where-Object { $_ }) -join "; " } catch { "N/A" }
            $venue = if ($w.'container-title' -and $w.'container-title'.Count -gt 0) { $w.'container-title'[0] } else { "N/A" }
            $allResults += [PSCustomObject]@{
                Title     = $w.title[0]
                Authors   = $authors
                Year      = $year
                Venue     = $venue
                DOI       = $w.DOI
                Citations = $w.'is-referenced-by-count'
                Source    = "CrossRef"
                OaUrl     = ""
                Relevance = ""
            }
            $count++
        }
        Write-Host "[CrossRef] Found $count results" -ForegroundColor Green
    } catch {
        Write-Warning "[CrossRef] Failed: $($_.Exception.Message)"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Source 3: PubMed (Path C) — 3600万+ 生物医学
# ═══════════════════════════════════════════════════════════════════════════════
if ($activeSources -contains "pubmed") {
    Write-Host "[PubMed] Searching..." -ForegroundColor Yellow
    try {
        $pmDateFilter = ""
        if ($YearFrom -gt 0 -and $YearTo -gt 0) {
            $pmDateFilter = "+AND+($YearFrom/01/01[PDAT]:$YearTo/12/31[PDAT])"
        } elseif ($YearFrom -gt 0) {
            $pmDateFilter = "+AND+($YearFrom/01/01[PDAT]:3000[PDAT])"
        } elseif ($YearTo -gt 0) {
            $pmDateFilter = "+AND+(0001/01/01[PDAT]:$YearTo/12/31[PDAT])"
        }
        $pmQuery = [uri]::EscapeDataString("$Query$pmDateFilter")
        $pmSearch = Invoke-RestMethod "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=$pmQuery&retmax=$Limit&retmode=json&sort=relevance" -TimeoutSec 15
        if ($pmSearch.esearchresult.idlist.Count -gt 0) {
            $pmIds = $pmSearch.esearchresult.idlist -join ","
            $pmSum = Invoke-RestMethod "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=$pmIds&retmode=json" -TimeoutSec 15
            $count = 0
            foreach ($id in $pmSearch.esearchresult.idlist) {
                $d = $pmSum.result.$id
                if (-not $d) { continue }
                $authors = if ($d.authors) { ($d.authors | Select-Object -First 3 | ForEach-Object { $_.name }) -join "; " } else { "N/A" }
                $doiClean = if ($d.elocationid) { $d.elocationid -replace '^doi:\s*','' } else { "" }
                $allResults += [PSCustomObject]@{
                    Title     = $d.title
                    Authors   = $authors
                    Year      = [int]($d.pubdate -replace '\D','').Substring(0, [Math]::Min(4, ($d.pubdate -replace '\D','').Length))
                    Venue     = if ($d.source) { $d.source } else { "N/A" }
                    DOI       = $doiClean
                    Citations = 0
                    Source    = "PubMed"
                    OaUrl     = ""
                    Relevance = ""
                }
                $count++
            }
            Write-Host "[PubMed] Found $count results" -ForegroundColor Green
        } else {
            Write-Host "[PubMed] No results" -ForegroundColor DarkGray
        }
    } catch {
        Write-Warning "[PubMed] Failed: $($_.Exception.Message)"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Source 4: arXiv (Path D) — CS/物理/数学预印本
# ═══════════════════════════════════════════════════════════════════════════════
if ($activeSources -contains "arxiv") {
    Write-Host "[arXiv] Searching..." -ForegroundColor Yellow
    try {
        $axUrl = "https://export.arxiv.org/api/query?search_query=all:$encoded$arxivCat&max_results=$Limit&sortBy=relevance"
        $axResp = Invoke-WebRequest $axUrl -UseBasicParsing -TimeoutSec 20
        $axContent = $axResp.Content
        $titles = [regex]::Matches($axContent, '<entry>.*?<title>(.*?)</title>', 'Singleline')
        $sums   = [regex]::Matches($axContent, '<entry>.*?<summary>(.*?)</summary>', 'Singleline')
        $ids    = [regex]::Matches($axContent, '<entry>.*?<id>(.*?)</id>', 'Singleline')
        $yrs    = [regex]::Matches($axContent, '<entry>.*?<published>(.*?)</published>', 'Singleline')
        $authorsR = [regex]::Matches($axContent, '<entry>.*?<author>.*?<name>(.*?)</name>.*?</author>', 'Singleline')
        $count = 0
        for ($i=0; $i -lt [Math]::Min($titles.Count, $Limit); $i++) {
            $t = $titles[$i].Groups[1].Value -replace '\s+',' ' -replace '^\s+','' -replace '\s+$',''
            if ($t -match '^\s*$') { continue }
            $y = if ($i -lt $yrs.Count) { $yrs[$i].Groups[1].Value.Substring(0,4) } else { 0 }
            if ($YearFrom -gt 0 -and [int]$y -lt $YearFrom) { continue }
            if ($YearTo -gt 0 -and [int]$y -gt $YearTo) { continue }
            $aid = if ($i -lt $ids.Count) {
                $raw = $ids[$i].Groups[1].Value
                if ($raw -match 'arxiv.org/abs/([^v]+)') { $matches[1] } else { $raw }
            } else { "" }
            $s = if ($i -lt $sums.Count) { ($sums[$i].Groups[1].Value -replace '\s+',' ').Substring(0, [Math]::Min(200, $sums[$i].Groups[1].Value.Length)) } else { "" }
            $allResults += [PSCustomObject]@{
                Title     = $t
                Authors   = "N/A"
                Year      = [int]$y
                Venue     = "arXiv ($aid)"
                DOI       = ""
                Citations = 0
                Source    = "arXiv"
                OaUrl     = if ($aid) { "https://arxiv.org/pdf/$aid" } else { "" }
                Relevance = $s
            }
            $count++
        }
        Write-Host "[arXiv] Found $count results" -ForegroundColor Green
    } catch {
        Write-Warning "[arXiv] Failed: $($_.Exception.Message)"
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Deduplication by normalized DOI
# ═══════════════════════════════════════════════════════════════════════════════
if (-not $NoDedup) {
    $seenDoi = @{}
    $deduped = @()
    foreach ($r in $allResults) {
        $norm = Normalize-DOI $r.DOI
        if ($norm -and $seenDoi.ContainsKey($norm)) {
            $existing = $seenDoi[$norm]
            if ($r.Citations -gt $existing.Citations) {
                $idx = $deduped.IndexOf($existing)
                if ($idx -ge 0) { $deduped[$idx] = $r }
                $seenDoi[$norm] = $r
            }
            continue
        }
        if ($norm) { $seenDoi[$norm] = $r }
        $deduped += $r
    }
    $allResults = @($deduped)
    Write-Host "[Dedup] $($allResults.Count) unique papers retained (DOI-based)" -ForegroundColor DarkGray
}

# ═══════════════════════════════════════════════════════════════════════════════
# OnlineRank: OneScholar API 在线期刊等级查询（可选）
# ═══════════════════════════════════════════════════════════════════════════════
$onlineRanks = @{}
if ($OnlineRank) {
    $onescholarKey = ""
    try {
        $cfg = if (Test-Path (Join-Path $env:USERPROFILE ".lit-search-cite\config.json")) {
            Get-Content (Join-Path $env:USERPROFILE ".lit-search-cite\config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        } else { $null }
        $onescholarKey = $cfg.api_keys.onescholar
    } catch {}
    if (-not $onescholarKey) {
        $onescholarKey = [System.Environment]::GetEnvironmentVariable("ONESCHOLAR_API_KEY")
    }

    if ($onescholarKey -and $onescholarKey.StartsWith("sk_")) {
        $uniqueVenues = @($allResults | Where-Object { $_.Venue -ne "N/A" -and $_.Venue -ne "" } | Select-Object -ExpandProperty Venue -Unique)
        $maxOnlineQueries = [Math]::Min(10, $uniqueVenues.Count)
        Write-Host "[OneScholar] Looking up $maxOnlineQueries journal rankings (batch mode, up to 5 per call)..." -ForegroundColor Yellow
        
        $ohScript = Join-Path $PSScriptRoot "journal-rank.ps1"
        $journalsToQuery = @($uniqueVenues | Select-Object -First $maxOnlineQueries | ForEach-Object { $_ })
        
        if ($journalsToQuery.Count -gt 0) {
            try {
                $ohResults = & $ohScript -Journal $journalsToQuery -Quiet -ErrorAction Stop 2>$null
                if ($ohResults) {
                    foreach ($r in $ohResults) {
                        if ($r.IF) {
                            $onlineRanks[$r.Query.ToLower()] = $r
                        }
                    }
                }
            } catch {
                Write-Host "  [OneScholar] Query failed: $($_.Exception.Message.Substring(0, [Math]::Min(100, $_.Exception.Message.Length)))" -ForegroundColor DarkGray
            }
        }
        Write-Host "[OneScholar] Got $($onlineRanks.Count) live rankings" -ForegroundColor Green
    } else {
        Write-Host "[OneScholar] No API key configured (set api_keys.onescholar in config.json)" -ForegroundColor DarkGray
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# Sort: citations desc, then year desc
# ═══════════════════════════════════════════════════════════════════════════════
$allResults = @($allResults | Sort-Object -Property @{Expression="Citations"; Descending=$true}, @{Expression="Year"; Descending=$true})

# ═══════════════════════════════════════════════════════════════════════════════
# Output formatted results
# ═══════════════════════════════════════════════════════════════════════════════
$outputCount = [Math]::Min($allResults.Count, $TotalLimit)
Write-Host ""
Write-Host "=== Results ($outputCount of $($allResults.Count) papers) ===" -ForegroundColor Cyan
Write-Host ""

for ($i = 0; $i -lt $outputCount; $i++) {
    $r = $allResults[$i]
    $tier = Get-JournalTier $r.Venue
    $tierStr = if ($tier) { "  |  Tier: $tier" } else { "" }

    Write-Host "[$($i+1)] $($r.Title)" -ForegroundColor White
    Write-Host "    Authors   : $($r.Authors)"
    Write-Host "    Year      : $($r.Year)  |  Venue: $($r.Venue)  |  Source: $($r.Source)$tierStr"
    Write-Host "    Citations : $($r.Citations)"
    if ($r.DOI) { $doiDisplay = if ($r.DOI -match '^https?://') { $r.DOI } else { "https://doi.org/$($r.DOI)" }; Write-Host "    DOI       : $doiDisplay" -ForegroundColor DarkGray }
    if ($r.OaUrl) { Write-Host "    OA URL    : $($r.OaUrl)" -ForegroundColor DarkGray }
    Write-Host ""
}

Write-Host "---" -ForegroundColor DarkGray
Write-Host "Sources used: $($activeSources -join ', ')" -ForegroundColor DarkGray
Write-Host "Total unique: $($allResults.Count)  |  Shown: $outputCount" -ForegroundColor DarkGray
Write-Host ""
