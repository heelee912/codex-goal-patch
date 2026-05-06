#Requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Launch,
    [string]$SourceApp,
    [switch]$RepairBrowserUseOnly,
    [switch]$StopNodeRepl
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

function Set-CodexTomlFeatureFlag {
    param(
        [string]$Text,
        [string]$Name,
        [bool]$Enabled
    )

    $line = "$Name = $($Enabled.ToString().ToLowerInvariant())"
    $featuresPattern = "(?ms)^\[features\]\r?\n.*?(?=^\[|\z)"
    $featuresMatch = [regex]::Match($Text, $featuresPattern)

    if ($featuresMatch.Success) {
        $section = $featuresMatch.Value
        $linePattern = "(?m)^[ `t]*$([regex]::Escape($Name))[ `t]*=[ `t]*(true|false)[ `t]*`r?$"
        if ($section -match $linePattern) {
            $section = [regex]::Replace($section, $linePattern, $line)
        } else {
            if (-not $section.EndsWith([Environment]::NewLine)) {
                $section = $section.TrimEnd("`r", "`n") + [Environment]::NewLine
            }
            $section += $line + [Environment]::NewLine
        }

        return $Text.Substring(0, $featuresMatch.Index) +
            $section +
            $Text.Substring($featuresMatch.Index + $featuresMatch.Length)
    }

    if ($Text.Length -gt 0 -and -not $Text.EndsWith([Environment]::NewLine)) {
        $Text += [Environment]::NewLine
    }

    return $Text + [Environment]::NewLine + "[features]" + [Environment]::NewLine + $line + [Environment]::NewLine
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

function ConvertTo-CodexAppCandidate {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    try {
        $fullPath = [IO.Path]::GetFullPath($expanded)
    } catch {
        return $expanded
    }

    $leaf = Split-Path -Leaf $fullPath
    if ($leaf -ieq "Codex.exe") {
        return [IO.Path]::GetFullPath((Split-Path -Parent $fullPath))
    }
    if ($leaf -ieq "app.asar") {
        $resourcesDir = Split-Path -Parent $fullPath
        return [IO.Path]::GetFullPath((Split-Path -Parent $resourcesDir))
    }

    $nestedApp = Join-Path $fullPath "app"
    if ((Test-Path (Join-Path $nestedApp "Codex.exe")) -and
        (Test-Path (Join-Path $nestedApp "resources\app.asar"))) {
        return [IO.Path]::GetFullPath($nestedApp)
    }

    return $fullPath
}

function Add-CodexAppCandidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$Path
    )

    $candidate = ConvertTo-CodexAppCandidate $Path
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        return
    }

    foreach ($existing in $Candidates) {
        if ($existing -ieq $candidate) {
            return
        }
    }

    [void]$Candidates.Add($candidate)
}

function Add-CodexRegistryCandidates {
    param([System.Collections.Generic.List[string]]$Candidates)

    $roots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )

    foreach ($root in $roots) {
        if (-not (Test-Path $root)) {
            continue
        }

        Get-ChildItem $root -ErrorAction SilentlyContinue | ForEach-Object {
            $entry = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
            if (-not $entry) {
                return
            }

            $displayNameProperty = $entry.PSObject.Properties["DisplayName"]
            $displayName = if ($displayNameProperty) { [string]$displayNameProperty.Value } else { "" }
            if ($displayName -notmatch "Codex") {
                return
            }

            $installLocationProperty = $entry.PSObject.Properties["InstallLocation"]
            if ($installLocationProperty) {
                Add-CodexAppCandidate $Candidates $installLocationProperty.Value
            }

            $displayIconProperty = $entry.PSObject.Properties["DisplayIcon"]
            $displayIcon = if ($displayIconProperty) { [string]$displayIconProperty.Value } else { "" }
            if (-not [string]::IsNullOrWhiteSpace($displayIcon)) {
                $iconPath = $displayIcon.Trim()
                if ($iconPath.StartsWith('"')) {
                    $endQuote = $iconPath.IndexOf('"', 1)
                    if ($endQuote -gt 1) {
                        $iconPath = $iconPath.Substring(1, $endQuote - 1)
                    }
                } else {
                    $iconPath = ($iconPath -split ",")[0]
                }
                Add-CodexAppCandidate $Candidates $iconPath
            }
        }
    }
}

function Add-CodexAppxCandidates {
    param([System.Collections.Generic.List[string]]$Candidates)

    $packages = @()
    if (Get-Command Get-AppxPackage -ErrorAction SilentlyContinue) {
        $packages = @(Get-AppxPackage -Name "OpenAI.Codex" -ErrorAction SilentlyContinue)
        if ($packages.Count -eq 0) {
            $packages = @(Get-AppxPackage -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match "Codex" -or $_.PackageFamilyName -match "Codex" })
        }
    }

    foreach ($package in $packages) {
        $installLocationProperty = $package.PSObject.Properties["InstallLocation"]
        if ($installLocationProperty) {
            Add-CodexAppCandidate $Candidates $installLocationProperty.Value
            Add-CodexAppCandidate $Candidates (Join-Path $installLocationProperty.Value "app")
        }
    }

    $windowsApps = Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "WindowsApps"
    if (Test-Path $windowsApps) {
        Get-ChildItem $windowsApps -Directory -Filter "OpenAI.Codex_*" -ErrorAction SilentlyContinue |
            ForEach-Object {
                Add-CodexAppCandidate $Candidates $_.FullName
                Add-CodexAppCandidate $Candidates (Join-Path $_.FullName "app")
            }
    }
}

function Get-CodexAppCandidates {
    param(
        [string]$SourceApp,
        [string]$TargetApp
    )

    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $programFilesX86 = ${env:ProgramFiles(x86)}
    $candidates = New-Object "System.Collections.Generic.List[string]"

    if ($SourceApp) {
        Add-CodexAppCandidate $candidates $SourceApp
        return @($candidates)
    }

    Add-CodexAppCandidate $candidates (Join-Path $localAppData "OpenAI\Codex\app")
    Add-CodexAppCandidate $candidates (Join-Path $localAppData "OpenAI\Codex")
    Add-CodexAppCandidate $candidates (Join-Path $localAppData "Programs\Codex")
    Add-CodexAppCandidate $candidates (Join-Path $localAppData "Programs\Codex\app")
    Add-CodexAppCandidate $candidates (Join-Path $localAppData "Programs\OpenAI Codex")
    Add-CodexAppCandidate $candidates (Join-Path $programFiles "Codex")
    Add-CodexAppCandidate $candidates (Join-Path $programFiles "OpenAI\Codex")
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        Add-CodexAppCandidate $candidates (Join-Path $programFilesX86 "Codex")
        Add-CodexAppCandidate $candidates (Join-Path $programFilesX86 "OpenAI\Codex")
    }

    foreach ($root in @((Join-Path $localAppData "Programs"), (Join-Path $localAppData "OpenAI"), $programFiles, $programFilesX86)) {
        if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path $root)) {
            continue
        }

        Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "Codex" } |
            ForEach-Object {
                Add-CodexAppCandidate $candidates $_.FullName
                Add-CodexAppCandidate $candidates (Join-Path $_.FullName "app")
            }
    }

    Add-CodexRegistryCandidates $candidates
    Add-CodexAppxCandidates $candidates
    Add-CodexAppCandidate $candidates $TargetApp

    return @($candidates)
}

function Test-CodexDesktopApp {
    param([string]$Path)

    return (
        -not [string]::IsNullOrWhiteSpace($Path) -and
        (Test-Path (Join-Path $Path "Codex.exe")) -and
        (Test-Path (Join-Path $Path "resources\app.asar"))
    )
}

function Test-CodexBrowserUseApp {
    param([string]$Path)

    return (
        -not [string]::IsNullOrWhiteSpace($Path) -and
        (Test-Path (Join-Path $Path "resources\node_repl.exe")) -and
        (Test-Path (Join-Path $Path "resources\plugins\openai-bundled\plugins\browser-use\scripts\browser-client.mjs"))
    )
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

    $text = Set-CodexTomlFeatureFlag $text "goals" $true

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($configPath, $text, $utf8NoBom)
}

function Stop-CodexPatchedNodeReplProcesses {
    param([string]$PatchedApp)

    $nodeReplExe = [IO.Path]::GetFullPath((Join-Path $PatchedApp "resources\node_repl.exe"))
    $stopped = 0
    $processes = @(Get-Process -Name node_repl -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $_.Path -and ([IO.Path]::GetFullPath($_.Path) -ieq $nodeReplExe)
            } catch {
                $false
            }
        })

    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
            $stopped += 1
        } catch {
            Write-Warning "Could not stop stale node_repl process $($process.Id): $($_.Exception.Message)"
        }
    }

    return $stopped
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$patchScript = Join-Path $repoRoot "codex_desktop_patch.py"
$localAppData = [Environment]::GetFolderPath("LocalApplicationData")
$targetRoot = Join-Path $localAppData "OpenAI\CodexPatched"
$targetApp = Join-Path $targetRoot "app"
$extractDir = Join-Path ([IO.Path]::GetTempPath()) "codex-desktop-patch-app-asar"

$sourceCandidates = Get-CodexAppCandidates -SourceApp $SourceApp -TargetApp $targetApp
$repairCandidates = @($targetApp) + $sourceCandidates | Select-Object -Unique

$repairApp = $null
foreach ($candidate in $repairCandidates) {
    if (Test-CodexBrowserUseApp $candidate) {
        $repairApp = [IO.Path]::GetFullPath($candidate)
        break
    }
}

$sourceApp = $null
foreach ($candidate in $sourceCandidates) {
    if (Test-CodexDesktopApp $candidate) {
        $sourceApp = [IO.Path]::GetFullPath($candidate)
        break
    }
}

if (-not (Test-Path $patchScript)) {
    throw "Cannot find codex_desktop_patch.py next to this installer."
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
    if ($StopNodeRepl) {
        $stoppedNodeReplCount = Stop-CodexPatchedNodeReplProcesses $repairApp
        Write-Host ""
        Write-Host "Stopped stale patched node_repl process(es): $stoppedNodeReplCount"
    } else {
        Write-Host ""
        Write-Host "No running node_repl process was stopped. Add -StopNodeRepl only when you are not relying on active browser-use sessions."
    }
    Write-Host ""
    Write-Host "Retry browser-use. If the same error persists, reset Node REPL or fully close and reopen Codex."
    exit 0
}

if (-not $sourceApp) {
    $candidateList = ($sourceCandidates | ForEach-Object { "  $_" }) -join [Environment]::NewLine
    throw "Cannot find a Codex desktop app directory. Install Codex desktop first, or rerun with -SourceApp <path-to-app-folder>. Checked:$([Environment]::NewLine)$candidateList"
}

$runningCodex = Get-Process -Name Codex,codex -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Path -and (
            $_.Path -like (Join-Path $localAppData "OpenAI\Codex*") -or
            $_.Path -like (Join-Path $localAppData "Programs\Codex*") -or
            $_.Path -like "$sourceApp*" -or
            $_.Path -like "$targetApp*"
        )
    }

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

Write-Step "Using Codex app paths"
Write-Host "Source app:  $sourceApp"
Write-Host "Patched app: $targetApp"

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

Write-Step "Repairing goal runtime state database"
Invoke-Python $python @($patchScript, "--repair-state-db")

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
