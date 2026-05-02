<img width="778" height="180" alt="image" src="https://github.com/user-attachments/assets/a6694fed-78c3-49f3-b30d-82fa9cebc699" />

<img width="321" height="99" alt="image" src="https://github.com/user-attachments/assets/14425395-0a7e-4e1a-b3d2-578b2e0c4b10" />

<img width="761" height="202" alt="image" src="https://github.com/user-attachments/assets/0c4b3d38-d3fd-41f3-b37a-e894f6469e71" />


# Codex Goal Patch

Unofficial local patch for the Codex desktop app. It adds a `/goal` slash command path and replaces an existing thread goal before setting a new one.

This repository does not include OpenAI binaries, `app.asar`, extracted application files, user profiles, tokens, or cache files. Users apply the patch to their own local Codex installation at their own risk.

## What This Fixes

- `/goal <objective>` can be entered from the composer.
- Setting a new goal first clears the previous thread goal, so a completed or stale goal does not block the next one.
- Electron ASAR integrity in `Codex.exe` can be updated after repacking `app.asar`.

## Important Notes

- This is not an official OpenAI project.
- Do not publish or redistribute `Codex.exe`, `app.asar`, extracted app bundles, `.codex` profiles, auth files, logs, or caches.
- Codex updates can change the minified bundle names and code patterns. If the script cannot find exactly one match, it stops instead of guessing.
- Patch a copied app directory, not your only Codex install.

## Requirements

- Windows Codex desktop app installed.
- Python 3.11 or newer.
- Node.js/npm for `npx @electron/asar`.

## Easy Install

1. Click **Code** -> **Download ZIP** on this GitHub repository.
2. Extract the ZIP.
3. Close Codex completely.
4. Open PowerShell in the extracted folder.
5. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1
```

If you already installed a patched copy and want to replace it:

```powershell
.\install_windows.ps1 -Force
```

The installer creates a separate patched copy at:

```text
%LOCALAPPDATA%\OpenAI\CodexGoalPatched\app\Codex.exe
```

## Recommended Layout

The commands below create a separate patched app copy:

- Original app: `%LOCALAPPDATA%\OpenAI\Codex\app`
- Patched copy: `%LOCALAPPDATA%\OpenAI\CodexGoalPatched\app`

Close Codex before patching. The easy installer above does these steps automatically. The manual commands below are kept for troubleshooting.

## Manual Install

Run PowerShell from this repository directory.

```powershell
$src = "$env:LOCALAPPDATA\OpenAI\Codex\app"
$dstRoot = "$env:LOCALAPPDATA\OpenAI\CodexGoalPatched"
$dst = "$dstRoot\app"
$extract = "$env:TEMP\codex-goal-patch-app-asar"

New-Item -ItemType Directory -Force $dstRoot | Out-Null
Copy-Item -Recurse -Force $src $dst

Copy-Item "$dst\resources\app.asar" "$dst\resources\app.asar.original-goalpatch"
Copy-Item "$dst\Codex.exe" "$dst\Codex.exe.original-goalpatch"

Remove-Item -Recurse -Force $extract -ErrorAction SilentlyContinue
npx --yes @electron/asar extract "$dst\resources\app.asar" $extract

py -3 .\codex_goal_patch.py $extract

npx --yes @electron/asar pack $extract "$dst\resources\app.asar"

py -3 .\codex_goal_patch.py --fix-integrity $dst
```

If `py -3` is not available, use `python`:

```powershell
python .\codex_goal_patch.py $extract
python .\codex_goal_patch.py --fix-integrity $dst
```

## Run

```powershell
& "$env:LOCALAPPDATA\OpenAI\CodexGoalPatched\app\Codex.exe"
```

If the official Codex app is already running, close it first. Electron may forward launches to the already-running instance.

## Verify

In a local Codex thread:

1. Type `/goal test goal one`.
2. Confirm the app reports that the goal was set.
3. Complete or leave that goal.
4. Type `/goal test goal two`.
5. The second goal should replace the previous one instead of failing because a goal already exists.

## Restore

Close Codex, then restore the backed-up files:

```powershell
$dst = "$env:LOCALAPPDATA\OpenAI\CodexGoalPatched\app"
Copy-Item "$dst\resources\app.asar.original-goalpatch" "$dst\resources\app.asar" -Force
Copy-Item "$dst\Codex.exe.original-goalpatch" "$dst\Codex.exe" -Force
```

Or delete `%LOCALAPPDATA%\OpenAI\CodexGoalPatched` and keep using the official Codex install.

## Troubleshooting

### `expected 1 match, found 0`

The Codex desktop app bundle changed. Do not force the patch. Update the script for that Codex version.

### `Integrity check failed for asar archive`

Run:

```powershell
py -3 .\codex_goal_patch.py --fix-integrity "$env:LOCALAPPDATA\OpenAI\CodexGoalPatched\app"
```

### `/goal` does not appear

Make sure you launched the patched copy, not the official app. Close all Codex processes and launch:

```powershell
& "$env:LOCALAPPDATA\OpenAI\CodexGoalPatched\app\Codex.exe"
```

## Security

Review the script before running it. It edits local application files and updates the Electron ASAR integrity hash in the copied `Codex.exe`.
