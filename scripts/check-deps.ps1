<#
.SYNOPSIS
    lit-search-cite: dependency and configuration checker.

    Run this after first-time setup to verify everything is installed and configured.
    Checks Python, Playwright, MCP config (ai4scholar + scansci-pdf), API keys,
    CNKI session cookies, and scansci-pdf cookie files.

.EXAMPLE
    .\scripts\check-deps.ps1
#>

$ConfigFile  = Join-Path $env:USERPROFILE ".lit-search-cite\config.json"
$SessionFile = Join-Path $env:USERPROFILE ".lit-search-cite\cnki_session.json"
$McpFile     = Join-Path $env:USERPROFILE ".claude\mcp.json"
$ScansciDir  = Join-Path $env:USERPROFILE ".scansci-pdf"

$ok    = @()
$warn  = @()
$errors = @()

function Check($label, $pass, $msg, $fix) {
    if ($pass) {
        $script:ok += "  [OK]   $label"
    } elseif ($fix) {
        $script:warn += "  [WARN] $label — $msg`n         Fix: $fix"
    } else {
        $script:errors +="  [FAIL] $label — $msg"
    }
}

Write-Host ""
Write-Host "=== lit-search-cite: Dependency & Config Check ===" -ForegroundColor Cyan
Write-Host ""

# ── 1. Python ─────────────────────────────────────────────────────────────────
$pyVer = $null
try {
    $pyVer = (python --version 2>&1) -replace 'Python ',''
    $pyMajor = [int]($pyVer.Split('.')[0])
    $pyMinor = [int]($pyVer.Split('.')[1])
    Check "Python $pyVer" ($pyMajor -ge 3 -and $pyMinor -ge 10) `
        "Python 3.10+ required (found $pyVer)" `
        "winget install Python.Python.3.11"
} catch {
    Check "Python" $false "not found" "winget install Python.Python.3.11"
}

# ── 2. Playwright ─────────────────────────────────────────────────────────────
$pwOk = $false
try {
    $pwOut = python -c "from playwright.sync_api import sync_playwright; print('ok')" 2>&1
    $pwOk = ($pwOut -match 'ok')
} catch {}
Check "Playwright (Python)" $pwOk "not installed" `
    "pip install playwright && playwright install chromium"

# ── 3. Node.js / npx ─────────────────────────────────────────────────────────
$nodeVer = $null
try {
    $nodeVer = (node --version 2>&1) -replace 'v',''
    $nodeMajor = [int]($nodeVer.Split('.')[0])
    Check "Node.js v$nodeVer" ($nodeMajor -ge 18) `
        "Node.js 18+ required (found v$nodeVer)" `
        "winget install OpenJS.NodeJS"
} catch {
    Check "Node.js" $false "not found (required for ai4scholar MCP)" `
        "winget install OpenJS.NodeJS"
}

# ── 4. uv ─────────────────────────────────────────────────────────────────────
$uvOk = $false
try { $uvOk = ((uvx --version 2>&1) -match '\d+\.\d+') } catch {}
Check "uv / uvx" $uvOk "not found (required for scansci-pdf MCP)" `
    "pip install uv  OR  winget install astral-sh.uv"

# ── 5. mcp.json — ai4scholar ─────────────────────────────────────────────────
$mcpJson = $null
$ai4scholarInMcp = $false
$scansciInMcp    = $false
if (Test-Path $McpFile) {
    try {
        $mcpJson = Get-Content $McpFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $servers = $mcpJson.mcpServers
        $ai4scholarInMcp = $null -ne $servers.ai4scholar
        $scansciInMcp    = $null -ne $servers.'scansci-pdf'
    } catch {
        Check "mcp.json parse" $false "JSON parse error in $McpFile" "Fix JSON syntax errors"
    }
} else {
    Check "mcp.json" $false "not found at $McpFile" `
        "Create $McpFile with ai4scholar + scansci-pdf entries (see Prerequisites in SKILL.md)"
}
Check "ai4scholar MCP entry in mcp.json" $ai4scholarInMcp `
    "missing" "Add ai4scholar server block to $McpFile then restart Claude Code"
Check "scansci-pdf MCP entry in mcp.json" $scansciInMcp `
    "missing" "Add scansci-pdf server block to $McpFile then restart Claude Code"

# ── 6. ai4scholar API key ─────────────────────────────────────────────────────
$ai4Key = ""
if ($ai4scholarInMcp -and $mcpJson.mcpServers.ai4scholar.env) {
    $ai4Key = $mcpJson.mcpServers.ai4scholar.env.AI4SCHOLAR_API_KEY
}
if (-not $ai4Key) {
    $ai4Key = [System.Environment]::GetEnvironmentVariable("AI4SCHOLAR_API_KEY")
}
if (-not $ai4Key) {
    try {
        $cfg = Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $ai4Key = $cfg.api_keys.ai4scholar
    } catch {}
}
Check "AI4SCHOLAR_API_KEY set" ($ai4Key -and $ai4Key.StartsWith("sk-")) `
    "not set or wrong format" `
    "Get key at https://ai4scholar.net → Dashboard → Open Platform; add to mcp.json env block"

# ── 7. Config file ────────────────────────────────────────────────────────────
$cfgOk = Test-Path $ConfigFile
Check "Config file (~/.lit-search-cite/config.json)" $cfgOk `
    "not found" "Run: .\scripts\setup.ps1"

$cfg = $null
if ($cfgOk) {
    try { $cfg = Get-Content $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
}

# ── 8. Unpaywall email ────────────────────────────────────────────────────────
$upEmail = ""
if ($cfg) { $upEmail = $cfg.api_keys.unpaywall_email }
if (-not $upEmail) { $upEmail = [System.Environment]::GetEnvironmentVariable("UNPAYWALL_EMAIL") }
Check "UNPAYWALL_EMAIL set" ($upEmail -and $upEmail -match '@') `
    "not set (PDF discovery via Unpaywall disabled)" `
    "Run .\scripts\setup.ps1 and enter any valid email (required by Unpaywall ToS)"

# ── 9. CNKI VPN config ────────────────────────────────────────────────────────
$vpnOk     = $cfg -and $cfg.vpn_url -and $cfg.vpn_url.StartsWith("http")
$cnkiOk    = $cfg -and $cfg.cnki_vpn_base -and $cfg.cnki_vpn_base.StartsWith("http")
Check "CNKI VPN URL configured" $vpnOk `
    "not configured" `
    "Run: python scripts/cnki-playwright.py --setup --school <your-school>"
Check "CNKI WebVPN base URL configured" $cnkiOk `
    "not configured" `
    "Run: python scripts/cnki-playwright.py --setup --school <your-school>"

# ── 10. CNKI session cookies ──────────────────────────────────────────────────
$sessionOk = Test-Path $SessionFile
if ($sessionOk) {
    $sessionAge = (Get-Date) - (Get-Item $SessionFile).LastWriteTime
    $fresh = $sessionAge.TotalDays -lt 7
    Check "CNKI session cookies (age: $([int]$sessionAge.TotalDays)d)" $fresh `
        "cookies are >7 days old — may need refresh" `
        "Run: python scripts/cnki-playwright.py --login-only --no-headless"
} else {
    Check "CNKI session cookies" $false "not found — headless CNKI search won't work" `
        "Run: python scripts/cnki-playwright.py --login-only --no-headless"
}

# ── 11. scansci-pdf cookie dir ────────────────────────────────────────────────
$scansciCookies = Test-Path $ScansciDir
Check "scansci-pdf data dir (~/.scansci-pdf/)" $scansciCookies `
    "not found — publisher cookies not yet configured" `
    "Tell Claude: 'set up scansci-pdf browser cookies for ScienceDirect'"

# ── 12. Wanfang key (optional) ────────────────────────────────────────────────
$wfKey = ""
if ($cfg) { $wfKey = $cfg.api_keys.wanfang }
if (-not $wfKey) { $wfKey = [System.Environment]::GetEnvironmentVariable("WANFANG_API_KEY") }
if (-not $wfKey) {
    $warn += "  [WARN] WANFANG_API_KEY not set — Chinese 万方 API results unavailable`n         Fix: Register at https://open.wanfangdata.com.cn/ then run .\scripts\setup.ps1"
} else {
    $ok += "  [OK]   WANFANG_API_KEY set"
}

# ── Output ────────────────────────────────────────────────────────────────────
Write-Host "PASSED ($($ok.Count)):" -ForegroundColor Green
$ok | ForEach-Object { Write-Host $_ -ForegroundColor Green }

if ($warn.Count -gt 0) {
    Write-Host ""
    Write-Host "WARNINGS ($($warn.Count)):" -ForegroundColor Yellow
    $warn | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
}

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "FAILED ($($errors.Count)):" -ForegroundColor Red
    $errors | ForEach-Object { Write-Host $_ -ForegroundColor Red }
}

Write-Host ""
if ($errors.Count -eq 0 -and $warn.Count -le 2) {
    Write-Host "Status: READY — all critical components configured." -ForegroundColor Green
} elseif ($errors.Count -eq 0) {
    Write-Host "Status: PARTIAL — some optional components not configured (see warnings)." -ForegroundColor Yellow
} else {
    Write-Host "Status: NOT READY — fix FAILED items before using this skill." -ForegroundColor Red
}
Write-Host ""
Write-Host "Full setup guide: references/api-setup.md" -ForegroundColor DarkGray
Write-Host "Quick config:     .\scripts\setup.ps1" -ForegroundColor DarkGray
Write-Host "CNKI setup:       python scripts/cnki-playwright.py --setup" -ForegroundColor DarkGray
Write-Host ""
