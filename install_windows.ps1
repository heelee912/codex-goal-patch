#Requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Launch,
    [string]$SourceApp,
    [switch]$RepairBrowserUseOnly,
    [switch]$PurgeFullAccessMcp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-Tool {
    param(
        [string[]]$Names,
        [string]$InstallHint
    )

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "Missing required tool: $($Names -join ', '). $InstallHint"
}

function Resolve-Python {
    $candidates = @(
        @{ Command = "py"; Args = @("-3") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $command) {
            continue
        }

        try {
            & $candidate.Command @($candidate.Args + @("--version")) *> $null
            return $candidate
        } catch {
            continue
        }
    }

    throw "Python 3.11 or newer is required. Install Python from https://www.python.org/downloads/windows/ and rerun this script."
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )

    & $Python.Command @($Python.Args + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed."
    }
}

function Invoke-Npx {
    param([string[]]$Arguments)

    & npx @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "npx command failed."
    }
}

function ConvertTo-TomlLiteral {
    param([string]$Value)

    return "'" + ($Value -replace "'", "''") + "'"
}

function Get-OptionalBrowserUseRoot {
    param([string]$Root)

    if ((Test-Path (Join-Path $Root "scripts\browser-client.mjs")) -and
        (Test-Path (Join-Path $Root "skills\browser\SKILL.md"))) {
        return [IO.Path]::GetFullPath($Root)
    }

    return $null
}

function Get-BrowserClientSha256 {
    param([string]$BrowserUseRoot)

    $client = Join-Path $BrowserUseRoot "scripts\browser-client.mjs"
    if (-not (Test-Path $client)) {
        return $null
    }

    return (Get-FileHash -Algorithm SHA256 $client).Hash.ToLowerInvariant()
}

function Update-CodexNodeReplBrowserUseConfig {
    param([string]$PatchedApp)

    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $codexDir = Join-Path $userProfile ".codex"
    $configPath = Join-Path $codexDir "config.toml"
    $nodeReplExe = Join-Path $PatchedApp "resources\node_repl.exe"
    $bundledBrowserUseRoots = @(
        (Join-Path $PatchedApp "resources\plugins\openai-bundled\plugins\browser-use"),
        (Join-Path $localAppData "OpenAI\CodexPatched\app\resources\plugins\openai-bundled\plugins\browser-use"),
        (Join-Path $localAppData "OpenAI\CodexGoalPatchedIntegrated\app\resources\plugins\openai-bundled\plugins\browser-use"),
        (Join-Path $localAppData "OpenAI\CodexGoalPatched\app\resources\plugins\openai-bundled\plugins\browser-use"),
        (Join-Path $localAppData "Programs\Codex\resources\plugins\openai-bundled\plugins\browser-use"),
        (Join-Path $localAppData "OpenAI\Codex\app\resources\plugins\openai-bundled\plugins\browser-use")
    ) | ForEach-Object { Get-OptionalBrowserUseRoot $_ } | Where-Object { $_ }
    $cacheBrowserUseRoot = $null
    $cacheRoot = Join-Path $codexDir "plugins\cache\openai-bundled\browser-use"

    if (Test-Path $cacheRoot) {
        $cacheBrowserUseRoot = Get-ChildItem $cacheRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            ForEach-Object { Get-OptionalBrowserUseRoot $_.FullName } |
            Where-Object { $_ } |
            Select-Object -First 1
    }

    $trustedRoots = @(@($bundledBrowserUseRoots + @($cacheBrowserUseRoot)) |
        Where-Object { $_ } |
        Select-Object -Unique)
    $trustedHashes = @($trustedRoots |
        ForEach-Object { Get-BrowserClientSha256 $_ } |
        Where-Object { $_ } |
        Select-Object -Unique)

    if (-not (Test-Path $nodeReplExe)) {
        throw "Cannot find patched node_repl.exe at $nodeReplExe"
    }
    if ($trustedRoots.Count -eq 0 -or $trustedHashes.Count -eq 0) {
        throw "Cannot find a browser-use browser-client.mjs to trust for node_repl."
    }

    New-Item -ItemType Directory -Force $codexDir | Out-Null

    $envTable = "env = { NODE_REPL_TRUSTED_CODE_PATHS = " +
        (ConvertTo-TomlLiteral ($trustedRoots -join [IO.Path]::PathSeparator)) +
        ", NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S = " +
        (ConvertTo-TomlLiteral ($trustedHashes -join " ")) + " }"
    $section = @(
        "[mcp_servers.node_repl]",
        "command = $(ConvertTo-TomlLiteral $nodeReplExe)",
        $envTable,
        ""
    ) -join [Environment]::NewLine

    $text = if (Test-Path $configPath) {
        Get-Content -Raw -Encoding UTF8 $configPath
    } else {
        ""
    }

    $pattern = "(?ms)^\[mcp_servers\.node_repl\]\r?\n.*?(?=^\[|\z)"
    if ($text -match $pattern) {
        $text = [regex]::Replace($text, $pattern, $section)
    } else {
        if ($text.Length -gt 0 -and -not $text.EndsWith([Environment]::NewLine)) {
            $text += [Environment]::NewLine
        }
        $text += [Environment]::NewLine + $section
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($configPath, $text, $utf8NoBom)
}

function Get-JsonProperty {
    param(
        [object]$Object,
        [string]$Name
    )

    if (-not $Object) {
        return $null
    }

    $property = $Object.PSObject.Properties[$Name]
    if (-not $property) {
        return $null
    }

    return $property.Value
}

function Test-FullAccessMcpTool {
    param([object]$Tool)

    $connectorName = Get-JsonProperty $Tool "connector_name"
    $toolNamespace = Get-JsonProperty $Tool "tool_namespace"

    if ($connectorName -eq "Full Access MCP") {
        return $true
    }
    if ($toolNamespace -eq "mcp__codex_apps__full_access_mcp") {
        return $true
    }

    $serialized = $Tool | ConvertTo-Json -Depth 60 -Compress
    return ($serialized -like "*Full Access MCP*" -or $serialized -like "*full_access_mcp*")
}

function Remove-FullAccessMcpToolCache {
    $userProfile = [Environment]::GetFolderPath("UserProfile")
    $codexCacheRoot = Join-Path $userProfile ".codex\cache"

    if (-not (Test-Path $codexCacheRoot)) {
        Write-Host "No Codex cache directory found at $codexCacheRoot"
        return 0
    }

    $jsonFiles = @(Get-ChildItem -Path $codexCacheRoot -Directory -Filter "codex_apps_tools*" -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -Path $_.FullName -File -Filter "*.json" -ErrorAction SilentlyContinue })

    if ($jsonFiles.Count -eq 0) {
        Write-Host "No Codex app tool cache JSON files found."
        return 0
    }

    $totalRemoved = 0
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)

    foreach ($jsonFile in $jsonFiles) {
        $raw = Get-Content -Raw -Encoding UTF8 $jsonFile.FullName
        $data = $raw | ConvertFrom-Json
        $toolsProperty = $data.PSObject.Properties["tools"]

        if (-not $toolsProperty) {
            continue
        }

        $tools = @($toolsProperty.Value)
        $keptTools = @($tools | Where-Object { -not (Test-FullAccessMcpTool $_) })
        $removed = $tools.Count - $keptTools.Count

        if ($removed -le 0) {
            continue
        }

        $data.tools = @($keptTools)
        $updated = $data | ConvertTo-Json -Depth 100
        [System.IO.File]::WriteAllText($jsonFile.FullName, $updated + [Environment]::NewLine, $utf8NoBom)
        $totalRemoved += $removed
        Write-Host "Removed $removed Full Access MCP tool cache entries from $($jsonFile.FullName)"
    }

    return $totalRemoved
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$patchScript = Join-Path $repoRoot "codex_desktop_patch.py"
$localAppData = [Environment]::GetFolderPath("LocalApplicationData")
$targetRoot = Join-Path $localAppData "OpenAI\CodexPatched"
$targetApp = Join-Path $targetRoot "app"
$extractDir = Join-Path ([IO.Path]::GetTempPath()) "codex-desktop-patch-app-asar"

$sourceCandidates = if ($SourceApp) {
    @($SourceApp)
} else {
    @(
        (Join-Path $localAppData "OpenAI\Codex\app"),
        (Join-Path $localAppData "Programs\Codex"),
        (Join-Path $localAppData "OpenAI\CodexGoalPatched\app"),
        $targetApp
    )
}

$repairCandidates = if ($SourceApp) {
    @($SourceApp)
} else {
    @(
        $targetApp,
        (Join-Path $localAppData "OpenAI\CodexGoalPatched\app"),
        (Join-Path $localAppData "Programs\Codex"),
        (Join-Path $localAppData "OpenAI\Codex\app")
    )
}

$repairApp = $null
foreach ($candidate in $repairCandidates) {
    if (
        (Test-Path (Join-Path $candidate "resources\node_repl.exe")) -and
        (Test-Path (Join-Path $candidate "resources\plugins\openai-bundled\plugins\browser-use\scripts\browser-client.mjs"))
    ) {
        $repairApp = [IO.Path]::GetFullPath($candidate)
        break
    }
}

$sourceApp = $null
foreach ($candidate in $sourceCandidates) {
    if (
        (Test-Path (Join-Path $candidate "Codex.exe")) -and
        (Test-Path (Join-Path $candidate "resources\app.asar"))
    ) {
        $sourceApp = [IO.Path]::GetFullPath($candidate)
        break
    }
}

if (-not (Test-Path $patchScript)) {
    throw "Cannot find codex_desktop_patch.py next to this installer."
}

if ($PurgeFullAccessMcp) {
    Write-Step "Purging Full Access MCP from Codex app tool cache"
    $removedFullAccessMcpTools = Remove-FullAccessMcpToolCache
    if ($removedFullAccessMcpTools -eq 0) {
        Write-Host "No Full Access MCP cache entries were found."
    } else {
        Write-Host "Removed $removedFullAccessMcpTools Full Access MCP cache entries." -ForegroundColor Green
    }
}

if ($RepairBrowserUseOnly) {
    if (-not $repairApp) {
        throw "Cannot find a Codex app with resources\node_repl.exe and bundled browser-use. Rerun with -SourceApp <path-to-app-folder>."
    }

    Write-Step "Repairing browser-use node_repl configuration"
    Update-CodexNodeReplBrowserUseConfig $repairApp
    Write-Host ""
    Write-Host "Done. browser-use node_repl config now points at:" -ForegroundColor Green
    Write-Host "  $(Join-Path $repairApp "resources\node_repl.exe")"
    Write-Host ""
    Write-Host "Fully close and reopen Codex for this config to be picked up."
    exit 0
}

if (-not $sourceApp) {
    throw "Cannot find a Codex desktop app directory. Install Codex desktop first, or rerun with -SourceApp <path-to-app-folder>."
}

$runningCodex = Get-Process -Name Codex,codex -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like (Join-Path $localAppData "OpenAI\Codex*") }

if ($runningCodex) {
    throw "Close all Codex windows and background Codex processes, then rerun this script."
}

$targetFullPath = [IO.Path]::GetFullPath($targetApp)
$patchInPlace = $sourceApp.TrimEnd("\") -ieq $targetFullPath.TrimEnd("\")

Write-Step "Checking requirements"
$python = Resolve-Python
Resolve-Tool -Names @("npx", "npx.cmd") -InstallHint "Install Node.js from https://nodejs.org/ and rerun this script." | Out-Null

if ((Test-Path $targetApp) -and -not $Force) {
    throw "Patched copy already exists at $targetApp. Rerun with -Force to replace it."
}

New-Item -ItemType Directory -Force $targetRoot | Out-Null

if ($patchInPlace) {
    Write-Step "Patching existing CodexPatched app in place"
} else {
    Write-Step "Copying Codex app to a separate patched folder"
    if (Test-Path $targetApp) {
        Remove-Item -Recurse -Force $targetApp
    }
    Copy-Item -Recurse -Force $sourceApp $targetApp
}

$targetAsar = Join-Path $targetApp "resources\app.asar"
$targetExe = Join-Path $targetApp "Codex.exe"
$backupStamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $targetAsar "$targetAsar.original-codexpatch-$backupStamp" -Force
Copy-Item $targetExe "$targetExe.original-codexpatch-$backupStamp" -Force

Write-Step "Extracting app.asar"
Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
Invoke-Npx @("--yes", "@electron/asar", "extract", $targetAsar, $extractDir)

Write-Step "Applying /goal and project path patch"
Invoke-Python $python @($patchScript, $extractDir)

Write-Step "Repacking app.asar"
Invoke-Npx @("--yes", "@electron/asar", "pack", $extractDir, $targetAsar)

Write-Step "Updating Electron ASAR integrity"
Invoke-Python $python @($patchScript, "--fix-integrity", $targetApp)

Write-Step "Configuring browser-use for patched node_repl"
Update-CodexNodeReplBrowserUseConfig $targetApp

Write-Step "Cleaning temporary files"
Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done. Patched Codex is installed at:" -ForegroundColor Green
Write-Host "  $targetExe"
Write-Host ""
Write-Host "Run it with:"
Write-Host "  & `"$targetExe`""

if ($Launch) {
    Write-Step "Launching patched Codex"
    Start-Process $targetExe
}
