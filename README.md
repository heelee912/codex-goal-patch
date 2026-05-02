<img width="778" height="180" alt="image" src="https://github.com/user-attachments/assets/a6694fed-78c3-49f3-b30d-82fa9cebc699" />

<img width="321" height="99" alt="image" src="https://github.com/user-attachments/assets/14425395-0a7e-4e1a-b3d2-578b2e0c4b10" />

<img width="761" height="202" alt="image" src="https://github.com/user-attachments/assets/0c4b3d38-d3fd-41f3-b37a-e894f6469e71" />


# Codex Desktop Patch

Unofficial local patch bundle for the Codex desktop app. It fixes the `/goal` workflow, adds a project path retarget action for moved local folders, and configures the bundled `browser-use` path used by the patched app.

This repository does not include OpenAI binaries, `app.asar`, extracted application files, user profiles, tokens, or cache files. Users apply the patch to their own local Codex installation at their own risk.

## What This Fixes

- `/goal <objective>` can be entered from the composer.
- Setting a new goal first clears the previous thread goal, so a completed or stale goal does not block the next one.
- Local project sidebar menu gets **Change project folder** / **프로젝트 경로 변경**.
- When a project folder was moved, the app can retarget existing chats to the new folder path instead of treating the old path as permanently missing.
- `browser-use` is configured to trust the patched app's bundled browser client when `node_repl` is launched from the patched copy.
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

If your Codex app is installed in a nonstandard folder:

```powershell
.\install_windows.ps1 -SourceApp "C:\Path\To\Codex\app"
```

The installer creates a separate patched copy at:

```text
%LOCALAPPDATA%\OpenAI\CodexPatched\app\Codex.exe
```

## Recommended Layout

The commands below create a separate patched app copy:

- Original app: `%LOCALAPPDATA%\OpenAI\Codex\app`
- Patched copy: `%LOCALAPPDATA%\OpenAI\CodexPatched\app`

Close Codex before patching. The easy installer above does these steps automatically. The manual commands below are kept for troubleshooting.

## Manual Install

Run PowerShell from this repository directory.

```powershell
$src = "$env:LOCALAPPDATA\OpenAI\Codex\app"
$dstRoot = "$env:LOCALAPPDATA\OpenAI\CodexPatched"
$dst = "$dstRoot\app"
$extract = "$env:TEMP\codex-desktop-patch-app-asar"

New-Item -ItemType Directory -Force $dstRoot | Out-Null
Copy-Item -Recurse -Force $src $dst

Copy-Item "$dst\resources\app.asar" "$dst\resources\app.asar.original-codexpatch"
Copy-Item "$dst\Codex.exe" "$dst\Codex.exe.original-codexpatch"

Remove-Item -Recurse -Force $extract -ErrorAction SilentlyContinue
npx --yes @electron/asar extract "$dst\resources\app.asar" $extract

py -3 .\codex_desktop_patch.py $extract

npx --yes @electron/asar pack $extract "$dst\resources\app.asar"

py -3 .\codex_desktop_patch.py --fix-integrity $dst
```

If `py -3` is not available, use `python`:

```powershell
python .\codex_desktop_patch.py $extract
python .\codex_desktop_patch.py --fix-integrity $dst
```

## Run

```powershell
& "$env:LOCALAPPDATA\OpenAI\CodexPatched\app\Codex.exe"
```

If the official Codex app is already running, close it first. Electron may forward launches to the already-running instance.

## Verify

For `/goal`, in a local Codex thread:

1. Type `/goal test goal one`.
2. Confirm the app reports that the goal was set.
3. Complete or leave that goal.
4. Type `/goal test goal two`.
5. The second goal should replace the previous one instead of failing because a goal already exists.

For moved project folders:

1. Launch the patched Codex copy.
2. Right-click a local project in the sidebar.
3. Click **Change project folder** or **프로젝트 경로 변경**.
4. Select the folder's new location.
5. The patch updates the sidebar project path, matching local thread cwd values, and session metadata. A backup is written under `%USERPROFILE%\.codex\backups\cwd-retarget-*`.

For `browser-use`:

1. Launch the patched Codex copy.
2. Start a local thread in the patched app.
3. Ask Codex to open or inspect a local page with browser-use.
4. The `iab` backend should connect through the patched app's bundled browser client.

## Restore

Close Codex, then restore the backed-up files. The easy installer writes timestamped backups next to the patched files:

```text
%LOCALAPPDATA%\OpenAI\CodexPatched\app\Codex.exe.original-codexpatch-*
%LOCALAPPDATA%\OpenAI\CodexPatched\app\resources\app.asar.original-codexpatch-*
```

For manual installs using the commands above, restore the fixed backup names:

```powershell
$dst = "$env:LOCALAPPDATA\OpenAI\CodexPatched\app"
Copy-Item "$dst\resources\app.asar.original-codexpatch" "$dst\resources\app.asar" -Force
Copy-Item "$dst\Codex.exe.original-codexpatch" "$dst\Codex.exe" -Force
```

Or delete `%LOCALAPPDATA%\OpenAI\CodexPatched` and keep using the official Codex install.

## Troubleshooting

### `expected 1 match, found 0`

The Codex desktop app bundle changed. Do not force the patch. Update the script for that Codex version.

### `Integrity check failed for asar archive`

Run:

```powershell
py -3 .\codex_desktop_patch.py --fix-integrity "$env:LOCALAPPDATA\OpenAI\CodexPatched\app"
```

### `/goal` does not appear

Make sure you launched the patched copy, not the official app. Close all Codex processes and launch:

```powershell
& "$env:LOCALAPPDATA\OpenAI\CodexPatched\app\Codex.exe"
```

### Project path change does not appear

Make sure you launched the patched copy. The project path action only appears for local workspace projects in the project action menu.

### Project path change fails

Check `%USERPROFILE%\.codex\backups` first. The retarget action backs up `state_5.sqlite`, its WAL/SHM sidecars when present, `.codex-global-state.json`, and affected rollout JSONL files before writing changes.

### `browser-use` says no Codex IAB backends were discovered

Rerun the installer with `-Force`, then fully close and reopen the patched app. The installer rewrites `%USERPROFILE%\.codex\config.toml` so `node_repl` trusts the browser-use client shipped inside `%LOCALAPPDATA%\OpenAI\CodexGoalPatched\app`.

## Security

Review the script before running it. It edits local application files, updates the Electron ASAR integrity hash in the copied `Codex.exe`, and updates local Codex config for the patched `node_repl`. The runtime project path action edits local Codex profile state for the selected moved project.
