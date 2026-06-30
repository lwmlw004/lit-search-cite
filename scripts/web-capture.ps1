<#
.SYNOPSIS
    Capture literature metadata from a URL, saved HTML file, or copied text file.

.EXAMPLE
    .\scripts\web-capture.ps1 -Url "https://example.com/article" -Out "references/captured" -Pdf legal

.EXAMPLE
    .\scripts\web-capture.ps1 -Html ".\page.html" -Format "bibtex,ris,csv,md"
#>
param(
    [string]$Url = "",
    [string]$Html = "",
    [string]$Text = "",
    [string]$Out = "references/captured",
    [string]$Format = "bibtex,ris,csv,md,json",
    [ValidateSet("none","legal")]
    [string]$Pdf = "none",
    [int]$Limit = 100,
    [int]$YearFrom = 0,
    [int]$YearTo = 0,
    [ValidateSet("doi","title")]
    [string]$Dedupe = "doi",
    [string]$Domain = "general",
    [string]$Python = "python",
    [switch]$OnlineRank,
    [switch]$Verbose,
    [Alias("h")]
    [switch]$Help
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

if ($Help) {
    @"
web-capture.ps1 - Capture literature metadata from URL, saved HTML, or copied text.

Usage:
  .\scripts\web-capture.ps1 -Url "https://example.com/article" -Out "references/captured" -Pdf legal
  .\scripts\web-capture.ps1 -Html ".\page.html" -Out "references/captured"
  .\scripts\web-capture.ps1 -Text ".\copied.txt" -Format "bibtex,ris,csv,md,json"

Options:
  -Url         Input web page URL
  -Html        Input local HTML file
  -Text        Input local plain text file
  -Out         Output root directory (default: references/captured)
  -Format      bibtex,ris,csv,md,json or all
  -Pdf         none or legal
  -Limit       Maximum extracted records
  -YearFrom    Minimum publication year
  -YearTo      Maximum publication year
  -Dedupe      doi or title
  -Domain      Domain hint such as chemistry, biomedicine, cs, materials
  -Python      Python executable (default: python)
  -OnlineRank  Use configured OneScholar ranking when available
  -Verbose     Print debug information
"@
    exit 0
}

$inputCount = 0
if ($Url) { $inputCount++ }
if ($Html) { $inputCount++ }
if ($Text) { $inputCount++ }
if ($inputCount -ne 1) {
    throw "Provide exactly one of -Url, -Html, or -Text."
}

$scriptPath = Join-Path $PSScriptRoot "web-capture.py"
$argsList = @($scriptPath, "--out", $Out, "--format", $Format, "--pdf", $Pdf, "--limit", $Limit, "--dedupe", $Dedupe, "--domain", $Domain)

if ($Url) { $argsList += @("--url", $Url) }
if ($Html) { $argsList += @("--html", $Html) }
if ($Text) { $argsList += @("--text", $Text) }
if ($YearFrom -gt 0) { $argsList += @("--year-from", $YearFrom) }
if ($YearTo -gt 0) { $argsList += @("--year-to", $YearTo) }
if ($OnlineRank) { $argsList += "--online-rank" }
if ($Verbose) { $argsList += "--verbose" }

& $Python @argsList
