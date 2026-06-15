<#
.SYNOPSIS
    PDF download chain: Unpaywall → OpenAlex → EuropePMC → Sci-Hub
    Returns the PDF URL (and optionally saves the file).

.PARAMETER DOI
    Paper DOI, e.g. "10.1038/s41586-021-03819-2" or full "https://doi.org/..."

.PARAMETER Email
    Email for Unpaywall ToS (falls back to $env:UNPAYWALL_EMAIL)

.PARAMETER OutputPath
    Directory to save PDF. If omitted, only prints the URL (no download).

.PARAMETER DownloadOnly
    Skip URL printing and only download silently.

.EXAMPLE
    .\pdf-fetch.ps1 -DOI "10.1038/s41586-021-03819-2"
    .\pdf-fetch.ps1 -DOI "10.1016/j.cell.2023.01.001" -OutputPath "C:\Papers"
#>
param(
    [Parameter(Mandatory)][string]$DOI,
    [string]$Email = $env:UNPAYWALL_EMAIL,
    [string]$OutputPath = "",
    [switch]$DownloadOnly
)

$ErrorActionPreference = "SilentlyContinue"

# Normalize DOI
$doi = $DOI.Trim() -replace '^https?://doi\.org/', ''

$pdfUrl = $null
$source  = $null

# ── 1. Unpaywall ────────────────────────────────────────────────────────────
if ($Email) {
    try {
        $r = Invoke-RestMethod "https://api.unpaywall.org/v2/$doi?email=$Email" -TimeoutSec 12
        $loc = $r.best_oa_location
        if ($loc -and $loc.url_for_pdf) {
            $pdfUrl = $loc.url_for_pdf
            $source  = "Unpaywall ($($r.oa_status))"
        }
    } catch {}
}

# ── 2. OpenAlex ─────────────────────────────────────────────────────────────
if (-not $pdfUrl) {
    try {
        $r = Invoke-RestMethod "https://api.openalex.org/works/https://doi.org/$doi" -TimeoutSec 12
        $url = $r.open_access.oa_url
        if ($url -and $url -match '\.pdf') {
            $pdfUrl = $url
            $source  = "OpenAlex"
        } elseif ($url) {
            # OA landing page, not direct PDF — store as fallback
            $oaLanding = $url
        }
    } catch {}
}

# ── 3. EuropePMC (biomedical) ───────────────────────────────────────────────
if (-not $pdfUrl) {
    try {
        $enc = [System.Uri]::EscapeDataString("DOI:$doi")
        $r = Invoke-RestMethod "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=$enc&resultType=core&format=json" -TimeoutSec 12
        $hit = $r.resultList.result | Where-Object { $_.isOpenAccess -eq "Y" -and $_.pmcid } | Select-Object -First 1
        if ($hit) {
            $pdfUrl = "https://europepmc.org/articles/$($hit.pmcid)/pdf"
            $source  = "EuropePMC (PMC:$($hit.pmcid))"
        }
    } catch {}
}

# ── 4. Sci-Hub ──────────────────────────────────────────────────────────────
# NOTE: Sci-Hub domains use DDoS-Guard which blocks non-browser HTTP clients.
# PowerShell scraping returns the challenge page (no PDF URL extractable).
# We output the Sci-Hub URL so the user can open it manually in a browser.
$scihubDomains = @("https://sci-hub.st", "https://sci-hub.do", "https://sci-hub.ee", "https://sci-hub.shop")
$scihubUrl = "$($scihubDomains[0])/$doi"

# ── Result ───────────────────────────────────────────────────────────────────
if (-not $pdfUrl) {
    Write-Warning "No OA PDF found for DOI: $doi"
    if ($oaLanding) {
        Write-Host "OA landing page (open in browser): $oaLanding"
    }
    Write-Host "Sci-Hub (open in browser, DDoS-Guard blocks scripts): $scihubUrl"
    Write-Host "Publisher page: https://doi.org/$doi"
    exit 1
}

if (-not $DownloadOnly) {
    Write-Host "PDF found via $source"
    Write-Host "URL: $pdfUrl"
}

if ($OutputPath) {
    $safe = $doi -replace '[/\\:*?"<>|]', '_'
    $file = Join-Path $OutputPath "$safe.pdf"
    try {
        Invoke-WebRequest $pdfUrl -OutFile $file -UseBasicParsing -TimeoutSec 60
        Write-Host "Saved: $file"
        return $file
    } catch {
        Write-Warning "Download failed: $_"
        Write-Host "URL: $pdfUrl"
    }
} else {
    return $pdfUrl
}
