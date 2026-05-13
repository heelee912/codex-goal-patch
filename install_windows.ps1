#Requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Launch,
    [string]$SourceApp,
    [switch]$RepairBrowserUseOnly,
    [switch]$StopNodeRepl,
    [ValidateSet("shared", "isolated")]
    [string]$ProfileMode = "shared",
    [string]$AppDir,
    [string]$CodexHomeDir,
    [string]$IsolatedAppName = "CodexPatched",
    [string]$IsolatedAppUserModelId = "OpenAI.CodexPatched"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
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

function ConvertTo-CodexAppDir {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    $fullPath = [IO.Path]::GetFullPath($expanded)
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

if ($StopNodeRepl) {
    Write-Step "Stopping patched node_repl processes"
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -ieq "node_repl.exe" -and
            ($_.CommandLine -like "*CodexPatched*" -or $_.CommandLine -like "*OpenAI\CodexPatched*")
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$patchScript = Join-Path $repoRoot "scripts\apply_codexpatched_public.py"
if (-not (Test-Path -LiteralPath $patchScript)) {
    throw "Cannot find scripts\apply_codexpatched_public.py next to this installer."
}

if ([string]::IsNullOrWhiteSpace($AppDir)) {
    $AppDir = Join-Path $env:LOCALAPPDATA "OpenAI\CodexPatched\app"
}
$AppDir = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($AppDir))

if ((Test-Path -LiteralPath $AppDir) -and -not $Force -and -not $RepairBrowserUseOnly) {
    throw "Patched copy already exists at $AppDir. Rerun with -Force to replace it, or use -RepairBrowserUseOnly to patch the existing copy."
}

$python = Resolve-Python
$arguments = @(
    $patchScript,
    "--profile-mode", $ProfileMode,
    "--app-dir", $AppDir,
    "--isolated-app-name", $IsolatedAppName,
    "--isolated-app-user-model-id", $IsolatedAppUserModelId
)

if (-not $RepairBrowserUseOnly) {
    $arguments += "--sync-from-source"
}
if (-not [string]::IsNullOrWhiteSpace($SourceApp)) {
    $arguments += @("--source-app-dir", (ConvertTo-CodexAppDir $SourceApp))
}
if (-not [string]::IsNullOrWhiteSpace($CodexHomeDir)) {
    $arguments += @("--codex-home-dir", [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($CodexHomeDir)))
}

Write-Step "Applying Codex desktop public patch"
& $python.Command @($python.Args + $arguments)
if ($LASTEXITCODE -ne 0) {
    throw "Patch script failed."
}

if ($Launch) {
    $exe = Join-Path $AppDir "Codex.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Patched Codex.exe was not found: $exe"
    }
    Write-Step "Launching patched Codex"
    Start-Process -FilePath $exe
}

Write-Host ""
Write-Host "Done. Patched app: $AppDir" -ForegroundColor Green
