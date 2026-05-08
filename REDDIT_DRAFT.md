# Reddit Draft

Suggested title:

```text
Codex Desktop patch: /goal slash UI and Plan Mode "Set as Goal"
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

- Shows the official `/goal` command in the slash-command popup when `[features] goals = true`
- Adds a Plan Mode follow-up option named `Set as Goal`
- Uses Codex's official persisted thread goal route instead of inventing a separate goal system
- Rebuilds a separate `%LOCALAPPDATA%\OpenAI\CodexPatched\app` copy from the currently installed official Codex app
- Leaves the Microsoft Store Codex app untouched
- Keeps the browser mini-window prototype disabled by default because a passive URL clone is not the same as the Browser Use controlled route

The current release is intentionally conservative. The goal is to expose and smooth the official Goal path, not replace it.

Install summary:

```powershell
.\install_windows.ps1 -Force
```

After install, launch:

```powershell
%LOCALAPPDATA%\OpenAI\CodexPatched\app\Codex.exe
```

Then enable goals in Codex config if needed:

```toml
[features]
goals = true
```

Known limitations:

- This edits minified Electron bundles, so future Codex Desktop updates can break patch anchors.
- The patched app is a separate local copy, not an official OpenAI build.
- The mini-window experiment is not enabled by default because it is not route-aware yet.
- Private runtime payloads are not included in the public repo.

This is for people who are already comfortable running local desktop patches and inspecting the code before installing.
```

Do not click Reddit's final submit/post button until the text, subreddit, and title have been reviewed.
