<#
.SYNOPSIS
    Query journal rankings via OneScholar API (SciGreat).
    Returns JCR quartile, CAS zone, Impact Factor, and university-specific rankings.

.DESCRIPTION
    Uses OneScholar API to get live journal ranking data. Supports query by ISSN or journal name.
    Free tier: 30 queries/day, 1 req/sec. Results are cached locally to minimize API calls.

.PARAMETER Issn
    Journal ISSN(s). Max 1 per call for free tier (batch not supported by API).

.PARAMETER Journal
    Journal name(s). Max 1 per call.

.PARAMETER NoCache
    Skip local cache, always query API.

.PARAMETER Quiet
    Suppress verbose output (only return data object).

.EXAMPLE
    .\journal-rank.ps1 -Issn "0028-0836"
    .\journal-rank.ps1 -Journal "Advanced Materials"
    .\journal-rank.ps1 -Journal "Nature,Science,Cell" -Quiet
#>
param(
    [string[]]$Issn = @(),
    [string[]]$Journal = @(),
    [switch]$NoCache,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

# ── Load config ────────────────────────────────────────────────────────────────
$ConfigFile = Join-Path $env:USERPROFILE ".lit-search-cite\config.json"
$key = ""
if (Test-Path $ConfigFile) {
    try {
        $cfg = Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $key = $cfg.api_keys.onescholar
    } catch {}
}
if (-not $key) {
    $key = [System.Environment]::GetEnvironmentVariable("ONESCHOLAR_API_KEY")
}
if (-not $key -or -not $key.StartsWith("sk_")) {
    Write-Error "OneScholar API key not found. Set it in ~/.lit-search-cite/config.json (key: api_keys.onescholar) or ONESCHOLAR_API_KEY env var."
    exit 1
}

# ── Cache setup ────────────────────────────────────────────────────────────────
$CacheDir = Join-Path $env:USERPROFILE ".lit-search-cite\cache"
if (-not (Test-Path $CacheDir)) { New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null }
$CacheFile = Join-Path $CacheDir "journal-ranks.json"
$cache = @{}
if (-not $NoCache -and (Test-Path $CacheFile)) {
    try {
        $cache = Get-Content $CacheFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $cache) { $cache = @{} }
    } catch { $cache = @{} }
}

function Get-CachedOrFetch {
    param($queryType, $queryValue)
    $cacheKey = "$queryType`:$queryValue"
    
    # Return cached if exists and not forced refresh
    if (-not $NoCache -and $cache.ContainsKey($cacheKey)) {
        $cached = $cache[$cacheKey]
        $age = if ($cached.fetched_at) { (Get-Date) - [DateTime]$cached.fetched_at } else { [TimeSpan]::MaxValue }
        if ($age.TotalDays -lt 30) {
            return $cached.data
        }
    }
    return $null
}

function Set-Cache {
    param($queryType, $queryValue, $data)
    $cacheKey = "$queryType`:$queryValue"
    $cache[$cacheKey] = @{ fetched_at = (Get-Date).ToString("o"); data = $data }
}

function Save-Cache {
    try {
        $cacheClone = @{}
        foreach ($k in $cache.Keys) { $cacheClone[$k] = $cache[$k] }
        $cacheClone | ConvertTo-Json -Depth 10 | Set-Content $CacheFile -Encoding UTF8
    } catch {
        # Cache save is best-effort; don't fail on write errors
    }
}

# ── Query OneScholar API ───────────────────────────────────────────────────────
function Get-BatchedRanks {
    param($Queries)
    
    $results = @()
    $batchSize = 5
    $queryList = @($Queries)
    
    for ($batchStart = 0; $batchStart -lt $queryList.Count; $batchStart += $batchSize) {
        $batchEnd = [Math]::Min($batchStart + $batchSize, $queryList.Count)
        
        # Build JSON array body
        $bodyParts = @()
        for ($j = $batchStart; $j -lt $batchEnd; $j++) {
            $q = $queryList[$j]
            if ($q.Type -eq "issn") {
                $bodyParts += [PSCustomObject]@{ issn = @($q.Value) }
            } else {
                $bodyParts += [PSCustomObject]@{ journal = @($q.Value) }
            }
        }
        $body = ConvertTo-Json -InputObject @($bodyParts) -Compress -Depth 3
        
        $headers = @{
            "Authorization" = "Bearer $key"
            "Content-Type"  = "application/json"
        }
        
        try {
            $resp = Invoke-WebRequest -Uri "https://api.scigreat.com/info/getrank" -Method Post -Headers $headers -Body $body -TimeoutSec 15 -UseBasicParsing
            $r = $resp.Content | ConvertFrom-Json
            
            if ($r.code -eq 200 -and $r.status -eq "success") {
                for ($i = 0; $i -lt $r.results.Count; $i++) {
                    $resultItem = $r.results[$i]
                    $q = $queryList[$batchStart + $i]
                    $data = $resultItem.data
                    
                    if ($data) {
                        $cacheKey = "$($q.Type):$($q.Value)"
                        $cache[$cacheKey] = @{ fetched_at = (Get-Date).ToString("o"); data = $data }
                        
                        $results += [PSCustomObject]@{
                            Query       = $q.Value
                            Type        = $q.Type
                            IF          = $data.imf
                            IF5         = $data.if5
                            JCR         = $data.jcr
                            CAS         = $data.cas
                            CASTop      = $data.cas_top
                            CASUpgrade  = $data.xr
                            CiteScore   = $data.citescore
                            Title       = $data.title
                            WosCore     = $data.wos_core
                            NatureIndex = $data.nij
                            JcarRisk    = $data.jcar_risk
                            HUST        = $data.hust
                            SJTU        = $data.sjtu
                            Raw         = $data
                        }
                        
                        if (-not $Quiet) {
                            Write-Host "[$($q.Type):$($q.Value)] IF=$($data.imf) JCR=$($data.jcr) CAS=$($data.cas)" -ForegroundColor Green
                        }
                    } else {
                        if (-not $Quiet) { Write-Host "[$($q.Type):$($q.Value)] Not found" -ForegroundColor Yellow }
                    }
                }
            } else {
                if (-not $Quiet) { Write-Warning "OneScholar returned: code=$($r.code) status=$($r.status)" }
            }
        } catch {
            if ($_.Exception.Message -match "429") {
                if (-not $Quiet) { Write-Warning "OneScholar rate limit reached" }
            } else {
                if (-not $Quiet) { Write-Warning "OneScholar error: $($_.Exception.Message)" }
            }
            break
        }
        
        Save-Cache
        
        # Rate limit delay between batches
        if ($batchStart + $batchSize -lt $Queries.Count) {
            Start-Sleep -Seconds 1.5
        }
    }
    
    return $results
}

# ── Process queries ────────────────────────────────────────────────────────────
$allQueries = @()
foreach ($i in $Issn) { if ($i.Trim()) { $allQueries += @{ Type = "issn"; Value = $i.Trim() } } }
foreach ($j in $Journal) { if ($j.Trim()) { $allQueries += @{ Type = "journal"; Value = $j.Trim() } } }

if ($allQueries.Count -eq 0) {
    Write-Error "Provide at least one -Issn or -Journal"
    exit 1
}

$results = Get-BatchedRanks -Queries $allQueries

# ── Output ─────────────────────────────────────────────────────────────────────
if ($results.Count -eq 1 -and -not $Quiet) {
    $r = $results[0]
    Write-Host ""
    Write-Host "=== $($r.Query) ===" -ForegroundColor Cyan
    Write-Host "  Impact Factor : $($r.IF) (5yr: $($r.IF5))"
    Write-Host "  JCR           : $($r.JCR)"
    Write-Host "  CAS           : $($r.CAS) ($($r.CASTop))  |  Upgrade: $($r.CASUpgrade)"
    Write-Host "  CiteScore     : $($r.CiteScore)"
    Write-Host "  WoS Core      : $($r.WosCore)  |  Nature Index: $($r.NatureIndex)"
    Write-Host "  Risk          : $($r.JcarRisk)"
    Write-Host "  HUST          : $($r.HUST)  |  SJTU: $($r.SJTU)"
}

return $results
