#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import struct
from pathlib import Path


COMPOSER_PREFIX = "webview/assets/composer--"
MAIN_ENTRY_PREFIX = ".vite/build/main-"


def is_wsl() -> bool:
    return os.name != "nt" and (
        "microsoft" in platform.release().lower() or Path("/mnt/c").exists()
    )


def windows_path(raw: str) -> Path:
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if match and is_wsl():
        drive = match.group(1).lower()
        tail = [part for part in re.split(r"[\\/]+", match.group(2)) if part]
        return Path("/mnt") / drive / Path(*tail)
    return Path(raw)


def default_windows_home() -> Path:
    if os.name == "nt":
        return Path.home()

    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidate = windows_path(user_profile)
        if candidate.exists():
            return candidate

    for user_name in [os.environ.get("USERNAME"), "USER", os.environ.get("USER")]:
        if not user_name:
            continue
        candidate = Path("/mnt/c/Users") / user_name
        if candidate.exists():
            return candidate

    return Path.home()


def default_windows_apps_root() -> Path:
    if os.name == "nt":
        return Path("C:/Program Files/WindowsApps")
    return Path("/mnt/c/Program Files/WindowsApps")


def parse_codex_version(path: Path) -> tuple[int, ...]:
    match = re.search(r"OpenAI\.Codex_([0-9.]+)_", str(path))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split(".") if part.isdigit())


def find_latest_official_app_dir() -> Path | None:
    root = default_windows_apps_root()
    if not root.exists():
        return None
    candidates = []
    for app_dir in root.glob("OpenAI.Codex_*_x64__2p2nqsd0c76g0/app"):
        if (app_dir / "Codex.exe").exists() and (app_dir / "resources/app.asar").exists():
            candidates.append(app_dir)
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: (parse_codex_version(path), path.stat().st_mtime))[-1]


def portable_path(value: str) -> Path:
    return windows_path(value)


def parse_args() -> argparse.Namespace:
    home = default_windows_home()
    parser = argparse.ArgumentParser(
        description="Patch a separate CodexPatched copy with public Goal and browser UI extensions."
    )
    parser.add_argument(
        "--app-dir",
        type=portable_path,
        default=home / "AppData/Local/OpenAI/CodexPatched/app",
    )
    parser.add_argument(
        "--source-app-dir",
        type=portable_path,
        default=find_latest_official_app_dir(),
        help="Official Codex app directory used as a read-only source when --sync-from-source is set.",
    )
    parser.add_argument(
        "--sync-from-source",
        action="store_true",
        help="Move any existing patched app aside, copy the official app into --app-dir, then patch the copy.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--enable-browser-preview-window",
        action="store_true",
        help=(
            "Experimental: add a passive URL preview mini window. This is not a Browser Use "
            "controlled session and is intentionally disabled by default."
        ),
    )
    return parser.parse_args()


def require_existing_file(path: Path, description: str) -> None:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"{description} not found: {path}")


def require_existing_app(app_dir: Path) -> None:
    require_existing_file(app_dir / "Codex.exe", "Codex executable")
    require_existing_file(app_dir / "resources/app.asar", "Codex ASAR")


def ensure_writable_path(path: Path) -> None:
    if not path.exists():
        return
    current_mode = path.stat().st_mode
    os.chmod(path, current_mode | 0o600)


def move_existing_app_aside(app_dir: Path, stamp: str) -> Path | None:
    if not app_dir.exists():
        return None
    archived_dir = app_dir.with_name(f"{app_dir.name}.previous-{stamp}")
    counter = 1
    while archived_dir.exists():
        archived_dir = app_dir.with_name(f"{app_dir.name}.previous-{stamp}-{counter}")
        counter += 1
    shutil.move(str(app_dir), str(archived_dir))
    return archived_dir


def sync_app_from_source(source_app_dir: Path, app_dir: Path, stamp: str) -> Path | None:
    source_app_dir = source_app_dir.resolve()
    if source_app_dir == app_dir.resolve():
        raise RuntimeError("--source-app-dir and --app-dir must be different when syncing")
    require_existing_app(source_app_dir)
    archived_dir = move_existing_app_aside(app_dir, stamp)
    app_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_app_dir, app_dir, symlinks=True)
    return archived_dir


def read_asar_header(asar_path: Path) -> tuple[bytes, dict, int, int, int]:
    data = asar_path.read_bytes()
    json_start = data.find(b'{"files"')
    if json_start < 0:
        raise RuntimeError("ASAR header start not found")

    depth = 0
    in_string = False
    escaped = False
    json_end = None
    for index in range(json_start, min(len(data), json_start + 3_000_000)):
        char = data[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                in_string = False
        else:
            if char == 34:
                in_string = True
            elif char == 123:
                depth += 1
            elif char == 125:
                depth -= 1
                if depth == 0:
                    json_end = index + 1
                    break
    if json_end is None:
        raise RuntimeError("ASAR header end not found")

    header = json.loads(data[json_start:json_end].decode("utf-8"))
    data_start = (json_end + 3) & ~3
    return data, header, json_start, json_end, data_start


def iter_file_entries(node: dict, prefix: str = ""):
    for name, entry in (node.get("files") or {}).items():
        path = f"{prefix}/{name}" if prefix else name
        if "files" in entry:
            yield from iter_file_entries(entry, path)
        else:
            yield path, entry


def find_entry(header: dict, path: str) -> dict:
    node = header
    for part in path.split("/"):
        node = node["files"][part]
    return node


def find_single_entry(header: dict, description: str, pattern: str) -> str:
    matches = [
        path
        for path, entry in iter_file_entries(header)
        if "offset" in entry and path.startswith(pattern) and path.endswith(".js")
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {description} entry, found {matches}")
    return matches[0]


def read_entry_content(data: bytes, data_start: int, entry: dict) -> bytes:
    if "offset" not in entry or "size" not in entry:
        raise RuntimeError("ASAR entry is not stored in the archive payload")
    start = data_start + int(entry["offset"])
    end = start + int(entry["size"])
    return data[start:end]


def file_integrity(content: bytes) -> dict:
    block_size = 4 * 1024 * 1024
    blocks = [
        hashlib.sha256(content[index : index + block_size]).hexdigest()
        for index in range(0, len(content), block_size)
    ]
    if not blocks:
        blocks = [hashlib.sha256(b"").hexdigest()]
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(content).hexdigest(),
        "blockSize": block_size,
        "blocks": blocks,
    }


def make_asar_prefix(header: dict) -> tuple[bytes, bytes]:
    header_json = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padding = (4 - ((4 + len(header_json)) % 4)) % 4
    payload_size = 4 + len(header_json) + padding
    header_pickle_size = 4 + payload_size
    prefix = (
        struct.pack("<II", 4, header_pickle_size)
        + struct.pack("<II", payload_size, len(header_json))
        + header_json
        + (b"\0" * padding)
    )
    return prefix, header_json


def replace_asar_entries(asar_path: Path, replacements: dict[str, bytes]) -> bytes:
    data, header, _, _, data_start = read_asar_header(asar_path)
    files = []
    for path, entry in iter_file_entries(header):
        if "offset" not in entry:
            continue
        start = data_start + int(entry["offset"])
        end = start + int(entry["size"])
        files.append((path, entry, replacements.get(path, data[start:end])))

    offset = 0
    payload_parts = []
    for _, entry, content in files:
        entry["offset"] = str(offset)
        entry["size"] = len(content)
        entry["integrity"] = file_integrity(content)
        payload_parts.append(content)
        offset += len(content)

    for entry_path in replacements:
        find_entry(header, entry_path)
    prefix, header_json = make_asar_prefix(header)
    asar_path.write_bytes(prefix + b"".join(payload_parts))
    return hashlib.sha256(header_json).hexdigest().encode("ascii")


def refresh_exe_integrity(exe_path: Path, asar_header_hash: bytes) -> tuple[str, str]:
    marker = b':"resources\\\\app.asar","alg":"SHA256","value":"'
    exe_blob = exe_path.read_bytes()
    position = exe_blob.find(marker)
    if position < 0:
        raise RuntimeError("Embedded app.asar integrity marker not found")
    value_start = position + len(marker)
    value_end = value_start + 64
    old_hash = exe_blob[value_start:value_end]
    if len(old_hash) != 64:
        raise RuntimeError("Embedded hash slot is invalid")
    if old_hash != asar_header_hash:
        exe_path.write_bytes(exe_blob[:value_start] + asar_header_hash + exe_blob[value_end:])
    return old_hash.decode("ascii"), asar_header_hash.decode("ascii")


def patch_goal_slash_visibility(content: bytes) -> bytes:
    text = content.decode("utf-8")
    patched = "dr=x(ur?.config,`goals`)===!0&&Kn!==`cloud`"
    if patched in text and "composer.goalSlashCommand.title" in text:
        return content
    old = "dr=Qi(`3074100722`)&&x(ur?.config,`goals`)===!0&&Kn!==`cloud`"
    if old not in text:
        raise RuntimeError("Goal slash visibility gate target not found")
    text = text.replace(old, patched, 1)
    if "id:`goal`" not in text or "composer.goalSlashCommand.title" not in text:
        raise RuntimeError("Goal slash visibility verification failed")
    return text.encode("utf-8")


def patch_plan_after_goal(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "id:`codex-set-goal`,value:`Set as Goal`" in text:
        return content

    old_submit = (
        "l=e=>{En(c,{eventName:`codex_request_input_submitted`,metadata:{kind:`implement_plan`,"
        "question_count:1}});let t=e[0],s=t?.selectedOptionId??null;if(er(`remove-plan-"
        "implementation-request`,{conversationId:n,turnId:r.turnId}),s===lH){o(`default`),"
        "i(`${un}\\n${r.planContent}`,a.find(mH));return}let l=t?.freeformText?.trim();"
        "l==null||l.length===0||i(l)}"
    )
    new_submit = (
        "l=async e=>{En(c,{eventName:`codex_request_input_submitted`,metadata:{kind:"
        "`implement_plan`,question_count:1}});let t=e[0],s=t?.selectedOptionId??null;"
        "if(await er(`remove-plan-implementation-request`,{conversationId:n,turnId:r.turnId}),"
        "s===lH){o(`default`),i(`${un}\\n${r.planContent}`,a.find(mH));return}"
        "if(s===`codex-set-goal`){o(`default`),await er(`set-thread-goal`,{conversationId:n,"
        "objective:r.planContent}),i(`${un}\\n${r.planContent}`,a.find(mH));return}"
        "let l=t?.freeformText?.trim();l==null||l.length===0||i(l)}"
    )
    text, submit_count = re.subn(re.escape(old_submit), new_submit, text, count=1)
    text, option_count = re.subn(
        r"h=\[\{id:lH,value:m\}\]",
        "h=[{id:lH,value:m},{id:`codex-set-goal`,value:`Set as Goal`}]",
        text,
        count=1,
    )
    if submit_count != 1 or option_count != 1:
        raise RuntimeError("Plan-after-Goal patch target not found")
    return text.encode("utf-8")


def patch_browser_mini_window_main(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "openBrowserSidebarMiniWindow(" in text and "case`open-mini-window`" in text:
        return content

    old_case = (
        "case`capture-screenshot`:await this.browserSidebarManager.captureScreenshotToClipboard"
        "(r,i.conversationId);break;"
    )
    new_case = (
        old_case
        + "case`open-mini-window`:this.browserSidebarManager.openBrowserSidebarMiniWindow"
        "(i.conversationId,i.command.url);break;"
    )
    text, case_count = re.subn(re.escape(old_case), new_case, text, count=1)

    old_method = (
        "openBrowserSidebarUrlExternally(e,t){Promise.resolve(n.shell.openExternal(t)).catch(n=>"
        "{Q().warning(`failed to open browser sidebar url externally`,{safe:{conversationId:e},"
        "sensitive:{error:n,url:t}})})}"
    )
    new_method = old_method + (
        "openBrowserSidebarMiniWindow(e,t){if(typeof t!=`string`||!Op(t)){Q().warning("
        "`browser mini window received invalid url`,{safe:{conversationId:e},sensitive:{url:t}});"
        "return}try{let r=new n.BrowserWindow({width:960,height:720,title:`Codex Browser`,"
        "show:!0,...process.platform===`win32`?{autoHideMenuBar:!0}:{},webPreferences:{"
        "partition:wp(`app`),contextIsolation:!0,nodeIntegration:!1,spellcheck:!1,devTools:!0}});"
        "r.webContents.setWindowOpenHandler(({url:t})=>(Op(t)&&this.openBrowserSidebarUrlExternally"
        "(e,t),{action:`deny`})),r.loadURL(t).catch(t=>{Q().warning(`failed to load browser mini "
        "window`,{safe:{conversationId:e},sensitive:{error:t,url:r.webContents.getURL()}})})}"
        "catch(r){Q().warning(`failed to open browser mini window`,{safe:{conversationId:e},"
        "sensitive:{error:r,url:t}})}}"
    )
    text, method_count = re.subn(re.escape(old_method), new_method, text, count=1)
    if case_count != 1 or method_count != 1:
        raise RuntimeError("Browser mini window main patch target not found")
    return text.encode("utf-8")


def patch_browser_mini_window_composer(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "thread.browser.openMiniWindow" in text:
        return content

    old_handler = (
        "Wt=e=>{e.trim().length!==0&&(En(g,{eventName:`codex_in_app_browser_opened_in_external_browser`}),"
        "$r.dispatchMessage(`open-in-browser`,{url:sl(e),useExternalBrowser:!0}))},Gt=e=>{"
    )
    new_handler = (
        "Wt=e=>{e.trim().length!==0&&(En(g,{eventName:`codex_in_app_browser_opened_in_external_browser`}),"
        "$r.dispatchMessage(`open-in-browser`,{url:sl(e),useExternalBrowser:!0}))},Xt=e=>{e.trim().length!==0&&"
        "(En(g,{eventName:`codex_in_app_browser_opened_in_mini_window`}),$r.dispatchMessage("
        "`browser-sidebar-command`,{conversationId:t,command:{type:`open-mini-window`,url:sl(e)}}))},Gt=e=>{"
    )
    text, handler_count = re.subn(re.escape(old_handler), new_handler, text, count=1)

    old_button = (
        "children:(0,Q.jsx)(Js,{className:`icon-xs`})})})]})}),(0,Q.jsxs)(`div`,"
        "{className:`flex items-center justify-end gap-px`,children:["
    )
    new_button = (
        "children:(0,Q.jsx)(Js,{className:`icon-xs`})})}),(0,Q.jsx)(is,{tooltipContent:"
        "y.formatMessage({id:`thread.browser.openMiniWindow`,defaultMessage:`Open in mini window`,"
        "description:`Tooltip text for opening the browser in a mini window`}),disabled:!Lt,children:"
        "(0,Q.jsx)(`button`,{type:`button`,\"data-browser-sidebar-skip-address-commit\":`true`,"
        "\"aria-label\":y.formatMessage({id:`thread.browser.openMiniWindow`,defaultMessage:"
        "`Open in mini window`,description:`Tooltip text for opening the browser in a mini window`}),"
        "disabled:!Lt,onPointerDown:Gt,onMouseDown:Gt,onClick:e=>{e.stopPropagation(),Xt(Ae)},"
        "className:Y(`flex h-[28px] w-7 shrink-0 items-center justify-center rounded-[10px] "
        "text-token-description-foreground outline-none transition-[background-color]`,Ne?"
        "`opacity-100`:`opacity-0 group-hover/address-bar:opacity-100 group-focus-within/address-bar:"
        "opacity-100`,Lt?`cursor-interaction hover:bg-token-foreground/5 focus-visible:bg-token-"
        "foreground/5`:`cursor-default opacity-0`),children:(0,Q.jsx)(Js,{className:`icon-xs`})})})]"
        "})}),(0,Q.jsxs)(`div`,{className:`flex items-center justify-end gap-px`,children:["
    )
    text, button_count = re.subn(re.escape(old_button), new_button, text, count=1)
    if handler_count != 1 or button_count != 1:
        raise RuntimeError("Browser mini window composer patch target not found")
    return text.encode("utf-8")


def main() -> None:
    args = parse_args()
    target_app_dir = Path(args.app_dir)
    app_dir = target_app_dir
    source_app_dir = Path(args.source_app_dir) if args.source_app_dir else None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    archived_app_dir = None
    if args.sync_from_source:
        if source_app_dir is None:
            raise RuntimeError("No official Codex app directory found; pass --source-app-dir")
        if args.dry_run:
            app_dir = source_app_dir
        else:
            archived_app_dir = sync_app_from_source(source_app_dir, app_dir, stamp)

    require_existing_app(app_dir)
    exe_path = app_dir / "Codex.exe"
    asar_path = app_dir / "resources/app.asar"
    if not args.dry_run:
        ensure_writable_path(exe_path)
        ensure_writable_path(asar_path)
    backup_dir = target_app_dir / f"codexpatch-public-backup-{stamp}"

    data, header, _, _, data_start = read_asar_header(asar_path)
    composer_entry_path = find_single_entry(header, "composer bundle", COMPOSER_PREFIX)

    composer_payload = read_entry_content(data, data_start, find_entry(header, composer_entry_path))
    composer_payload = patch_goal_slash_visibility(composer_payload)
    composer_payload = patch_plan_after_goal(composer_payload)

    replacements = {composer_entry_path: composer_payload}
    main_entry_path = None
    if args.enable_browser_preview_window:
        main_entry_path = find_single_entry(header, "main bundle", MAIN_ENTRY_PREFIX)
        main_payload = read_entry_content(data, data_start, find_entry(header, main_entry_path))
        main_payload = patch_browser_mini_window_main(main_payload)
        composer_payload = patch_browser_mini_window_composer(composer_payload)
        replacements[main_entry_path] = main_payload
        replacements[composer_entry_path] = composer_payload

    if args.dry_run:
        print("dry_run=true")
        print(f"read_app_dir={app_dir}")
        print(f"target_app_dir={target_app_dir}")
        print(f"source_app_dir={source_app_dir}")
        print(f"sync_from_source={args.sync_from_source}")
        print(f"would_backup_dir={backup_dir}")
        print(f"replacement_entries={sorted(replacements)}")
        return

    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe_path, backup_dir / "Codex.exe.before-public-patch")
    shutil.copy2(asar_path, backup_dir / "app.asar.before-public-patch")
    header_hash = replace_asar_entries(asar_path, replacements)
    old_hash, new_hash = refresh_exe_integrity(exe_path, header_hash)

    print(f"archived_app_dir={archived_app_dir}")
    print(f"backup_dir={backup_dir}")
    print(f"main_entry={main_entry_path}")
    print(f"composer_entry={composer_entry_path}")
    print(f"old_exe_header_hash={old_hash}")
    print(f"new_exe_header_hash={new_hash}")


if __name__ == "__main__":
    main()
