#Requires -Version 5.1

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Launch
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

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$patchScript = Join-Path $repoRoot "codex_goal_patch.py"
$localAppData = [Environment]::GetFolderPath("LocalApplicationData")
$sourceApp = Join-Path $localAppData "OpenAI\Codex\app"
$targetRoot = Join-Path $localAppData "OpenAI\CodexGoalPatched"
$targetApp = Join-Path $targetRoot "app"
$extractDir = Join-Path ([IO.Path]::GetTempPath()) "codex-goal-patch-app-asar"

if (-not (Test-Path $patchScript)) {
    throw "Cannot find codex_goal_patch.py next to this installer."
}

if (-not (Test-Path (Join-Path $sourceApp "Codex.exe"))) {
    throw "Cannot find Codex.exe at $sourceApp. Install the Codex desktop app first."
}

if (-not (Test-Path (Join-Path $sourceApp "resources\app.asar"))) {
    throw "Cannot find app.asar at $sourceApp\resources. The Codex install layout may have changed."
}

$runningCodex = Get-Process -Name Codex,codex -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like (Join-Path $localAppData "OpenAI\Codex*") }

if ($runningCodex) {
    throw "Close all Codex windows and background Codex processes, then rerun this script."
}

Write-Step "Checking requirements"
$python = Resolve-Python
Resolve-Tool -Names @("npx", "npx.cmd") -InstallHint "Install Node.js from https://nodejs.org/ and rerun this script." | Out-Null

if ((Test-Path $targetApp) -and -not $Force) {
    throw "Patched copy already exists at $targetApp. Rerun with -Force to replace it."
}

Write-Step "Copying Codex app to a separate patched folder"
New-Item -ItemType Directory -Force $targetRoot | Out-Null
if (Test-Path $targetApp) {
    Remove-Item -Recurse -Force $targetApp
}
Copy-Item -Recurse -Force $sourceApp $targetApp

$targetAsar = Join-Path $targetApp "resources\app.asar"
$targetExe = Join-Path $targetApp "Codex.exe"
Copy-Item $targetAsar "$targetAsar.original-goalpatch" -Force
Copy-Item $targetExe "$targetExe.original-goalpatch" -Force

Write-Step "Extracting app.asar"
Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
Invoke-Npx @("--yes", "@electron/asar", "extract", $targetAsar, $extractDir)

Write-Step "Applying /goal patch"
Invoke-Python $python @($patchScript, $extractDir)

Write-Step "Repacking app.asar"
Invoke-Npx @("--yes", "@electron/asar", "pack", $extractDir, $targetAsar)

Write-Step "Updating Electron ASAR integrity"
Invoke-Python $python @($patchScript, "--fix-integrity", $targetApp)

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
