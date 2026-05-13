# Reddit Draft

Suggested title:

```text
Codex Desktop patch: /goal slash UI, Plan Mode "Set as Goal", cwd retarget, and Browser mini window
```

Suggested subreddits:

```text
r/OpenAI
r/ChatGPTCoding
```

Suggested body:

```markdown
I published a small unofficial Codex Desktop patch for local users who want the newer Goal workflow to be easier to use from the desktop app.

Repository:
https://github.com/heelee912/codex-desktop-patch

What it does:

- Shows the official `/goal` command in the slash-command popup when local Goal is enabled
- Adds a Plan Mode follow-up option named `Set as Goal`
- Uses Codex's official persisted thread goal route instead of inventing a separate goal system
- Adds a project sidebar action to retarget moved local project folders
- Adds a route-aware Browser Use mini-window button that opens a secondary Codex window on the current route
- Adds Browser Use route fallback and simple `alert()` suppression during automation
- Rebuilds a separate `%LOCALAPPDATA%\OpenAI\CodexPatched\app` copy from the currently installed official Codex app
- Leaves the Microsoft Store Codex app untouched

The current release is intentionally conservative around Goal. It exposes and smooths the official Goal path; it does not replace it.

Install summary:

```powershell
.\install_windows.ps1 -Force
```

After install, launch:

```powershell
%LOCALAPPDATA%\OpenAI\CodexPatched\app\Codex.exe
```

The patcher enables goals in the selected Codex config:

```toml
[features]
goals = true
```

Known limitations:

- This edits minified Electron bundles, so future Codex Desktop updates can break patch anchors.
- The patcher now uses marker-based bundle discovery, so filename changes are less fragile, but code-shape changes can still require a patch update.
- The patched app is a separate local copy, not an official OpenAI build.
- Private runtime payloads are not included in the public repo.

This is for people who are already comfortable running local desktop patches and inspecting the code before installing.
```

Do not click Reddit's final submit/post button until the text, subreddit, and title have been reviewed.
