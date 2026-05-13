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


BROWSER_CLIENT_RELATIVE_PATH = Path(
    "resources/plugins/openai-bundled/plugins/browser-use/scripts/browser-client.mjs"
)
BROWSER_CLIENT_DEFAULT_BACKEND_OLD = b'function CN(){return"chrome"}'
BROWSER_CLIENT_DEFAULT_BACKEND_NEW = b'function CN(){return"iab"   }'
COMPOSER_PREFIX = "webview/assets/composer--"
BOOTSTRAP_ENTRY_PATH = ".vite/build/bootstrap.js"
COMMENT_PRELOAD_PATH = ".vite/build/comment-preload.js"
KOREAN_LOCALE_PREFIX = "webview/assets/ko-KR-"
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

    user_names = [
        os.environ.get("USERNAME"),
        "USER",
        os.environ.get("USER"),
    ]
    for user_name in user_names:
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
    default_app = home / "AppData/Local/OpenAI/CodexPatched/app"
    default_source_app = find_latest_official_app_dir()
    parser = argparse.ArgumentParser(
        description=(
            "Build or patch a CodexPatched app copy from the official Codex app, "
            "keeping official Goal behavior and layering public UI extensions on top."
        )
    )
    parser.add_argument("--app-dir", type=portable_path, default=default_app)
    parser.add_argument(
        "--codex-home-dir",
        type=portable_path,
        default=None,
        help=(
            "Codex home to patch. Defaults to %USERPROFILE%\\.codex in shared mode, "
            "or the isolated app profile's codex-home in isolated mode."
        ),
    )
    parser.add_argument(
        "--source-app-dir",
        type=portable_path,
        default=default_source_app,
        help="Official Codex app directory used as a read-only source when --sync-from-source is set.",
    )
    parser.add_argument(
        "--sync-from-source",
        action="store_true",
        help="Move any existing patched app aside, copy the official app into --app-dir, then patch the copy.",
    )
    parser.add_argument(
        "--profile-mode",
        choices=("shared", "isolated"),
        default="shared",
        help=(
            "Profile/app identity mode. shared keeps the official Codex userData/CODEX_HOME; "
            "isolated gives the patched app its own userData, CODEX_HOME, app identity, and "
            "disables updater/system registration by default."
        ),
    )
    parser.add_argument(
        "--isolated-app-name",
        default="CodexPatched",
        help="Default Electron app/profile name used when --profile-mode isolated is selected.",
    )
    parser.add_argument(
        "--isolated-app-user-model-id",
        default="OpenAI.CodexPatched",
        help="Default Windows AppUserModelID used when --profile-mode isolated is selected.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and verify patch targets without writing app files.",
    )
    parser.add_argument(
        "--skip-goal-ui-extensions",
        action="store_true",
        help="Do not make Goal slash visibility and Plan-after-Goal UI adjustments.",
    )
    parser.add_argument(
        "--skip-browser-mini-window",
        action="store_true",
        help="Do not add the route-aware Browser Use mini-window button and command handler.",
    )
    parser.add_argument(
        "--enable-browser-preview-window",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


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


def find_single_entry_by_markers(
    header: dict,
    data: bytes,
    data_start: int,
    description: str,
    markers: list[str],
    prefixes: tuple[str, ...] = ("webview/assets/", ".vite/build/"),
) -> str:
    matches = []
    for path, entry in iter_file_entries(header):
        if "offset" not in entry or not path.endswith(".js"):
            continue
        if not path.startswith(prefixes):
            continue
        try:
            text = read_entry_content(data, data_start, entry).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if all(marker in text for marker in markers):
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {description} entry, found {matches}")
    return matches[0]


def read_entry_content(data: bytes, data_start: int, entry: dict) -> bytes:
    if "offset" not in entry or "size" not in entry:
        raise RuntimeError("ASAR entry is not stored in the archive payload")
    start = data_start + int(entry["offset"])
    end = start + int(entry["size"])
    return data[start:end]


def replace_once_text(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def js_template_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


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
    target_parent = app_dir.parent
    if source_app_dir == app_dir.resolve():
        raise RuntimeError("--source-app-dir and --app-dir must be different when syncing")
    require_existing_app(source_app_dir)
    archived_dir = move_existing_app_aside(app_dir, stamp)
    target_parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_app_dir, app_dir, symlinks=True)
    return archived_dir


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


def patch_goal_slash_visibility(content: bytes) -> bytes:
    text = content.decode("utf-8")
    changed = False

    current_patched_gate = (
        ",{data:pr}=fi(Ki,cr),{data:__codexGoalFeatures=[]}=fi(Ka,Xr),hr=(S(pr?.config,`goals`)===!0||"
        "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0))&&Jn!==`cloud`"
    )
    if (
        "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0)" in text
        and "fi(Ka,Xr)" in text
        and "composer.goalSlashCommand.title" in text
    ):
        return content

    current_replacements = [
        (
            ",{data:pr}=fi(Ki,cr),hr=Qi(`3074100722`)&&S(pr?.config,`goals`)===!0&&Jn!==`cloud`",
            current_patched_gate,
        ),
        (
            ",{data:pr}=fi(Ki,cr),hr=S(pr?.config,`goals`)===!0&&Jn!==`cloud`",
            current_patched_gate,
        ),
    ]
    for old, new in current_replacements:
        if old in text:
            text = text.replace(old, new, 1)
            changed = True
            if (
                "id:`goal`" not in text
                or "composer.goalSlashCommand.title" not in text
                or "fi(Ka,Xr)" not in text
                or "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0)" not in text
            ):
                raise RuntimeError("Goal slash visibility verification failed")
            return text.encode("utf-8")

    if "__codexFeatureQuery" not in text:
        text = replace_once_text(
            text,
            'import{c as Ga,n as Ka}from"./experimental-features-queries-',
            'import{c as Ga,n as Ka,n as __codexFeatureQuery}from"./experimental-features-queries-',
            "Goal feature query import alias",
        )
        changed = True

    patched_gate = (
        ",{data:__codexGoalFeatures=[]}=fi(__codexFeatureQuery,or),dr=(x(ur?.config,`goals`)===!0||"
        "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0))&&Kn!==`cloud`"
    )
    if (
        "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0)" in text
        and "fi(__codexFeatureQuery,or)" in text
        and "composer.goalSlashCommand.title" in text
    ):
        return text.encode("utf-8") if changed else content

    replacements = [
        (
            ",{data:ur}=fi(Ki,or),{data:__codexGoalFeatures=[]}=fi(Ka,or),dr=(x(ur?.config,`goals`)===!0||"
            "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0))&&Kn!==`cloud`",
            ",{data:ur}=fi(Ki,or)" + patched_gate,
        ),
        (
            ",{data:ur}=fi(Ki,or),dr=Qi(`3074100722`)&&x(ur?.config,`goals`)===!0&&Kn!==`cloud`",
            ",{data:ur}=fi(Ki,or)" + patched_gate,
        ),
        (
            ",{data:ur}=fi(Ki,or),dr=x(ur?.config,`goals`)===!0&&Kn!==`cloud`",
            ",{data:ur}=fi(Ki,or)" + patched_gate,
        ),
    ]
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
            changed = True
            break
    else:
        raise RuntimeError("Goal slash visibility gate target not found")

    if (
        "id:`goal`" not in text
        or "composer.goalSlashCommand.title" not in text
        or "n as __codexFeatureQuery" not in text
        or "fi(__codexFeatureQuery,or)" not in text
        or "__codexGoalFeatures?.some(e=>e.name===`goals`&&e.enabled===!0)" not in text
    ):
        raise RuntimeError("Goal slash visibility verification failed")
    return text.encode("utf-8")


def patch_plan_after_goal(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "id:`codex-set-goal`,value:`Set as Goal`" in text:
        return content

    submit_pattern = re.compile(
        r"l=e=>\{En\(c,\{eventName:`codex_request_input_submitted`,metadata:\{kind:`implement_plan`,"
        r"question_count:1\}\}\);let t=e\[0\],s=t\?\.selectedOptionId\?\?null;if\(er\(`remove-plan-"
        r"implementation-request`,\{conversationId:n,turnId:r\.turnId\}\),s===([A-Za-z_$][\w$]*)\)"
        r"\{o\(`default`\),i\(`\$\{un\}\\n\$\{r\.planContent\}`,a\.find\(([A-Za-z_$][\w$]*)\)\);return\}"
        r"let l=t\?\.freeformText\?\.trim\(\);l==null\|\|l\.length===0\|\|i\(l\)\}"
    )

    def replace_submit(match: re.Match[str]) -> str:
        option_id = match.group(1)
        default_mode_predicate = match.group(2)
        return (
            "l=async e=>{En(c,{eventName:`codex_request_input_submitted`,metadata:{kind:"
            "`implement_plan`,question_count:1}});let t=e[0],s=t?.selectedOptionId??null;"
            "if(await er(`remove-plan-implementation-request`,{conversationId:n,turnId:r.turnId}),"
            f"s==={option_id}){{o(`default`),i(`${{un}}\\n${{r.planContent}}`,a.find({default_mode_predicate}));return}}"
            "if(s===`codex-set-goal`){o(`default`),await er(`set-thread-goal`,{conversationId:n,"
            f"objective:r.planContent}}),i(`${{un}}\\n${{r.planContent}}`,a.find({default_mode_predicate}));return}}"
            "let l=t?.freeformText?.trim();l==null||l.length===0||i(l)}"
        )

    text, submit_count = submit_pattern.subn(replace_submit, text, count=1)
    text, option_count = re.subn(
        r"h=\[\{id:([A-Za-z_$][\w$]*),value:m\}\]",
        lambda match: f"h=[{{id:{match.group(1)},value:m}},{{id:`codex-set-goal`,value:`Set as Goal`}}]",
        text,
        count=1,
    )
    if submit_count != 1 or option_count != 1:
        raise RuntimeError("Plan-after-Goal patch target not found")
    required = [
        "id:`codex-set-goal`,value:`Set as Goal`",
        "await er(`set-thread-goal`,{conversationId:n,objective:r.planContent})",
        "await er(`remove-plan-implementation-request`",
    ]
    if any(item not in text for item in required):
        raise RuntimeError("Plan-after-Goal verification failed")
    return text.encode("utf-8")


CWD_RETARGET_MAIN_METHODS = r"""__codexCwdNorm(e){return String(e??``).trim().replace(/^\\\\\?\\/,"").replace(/\//g,`\\`).replace(/\\+$/g,``).toLowerCase()}__codexCwdReplacement(e,t){return String(e??``).startsWith(`\\\\?\\`)?`\\\\?\\${t}`:t}__codexCwdStatePath(){return i.join(i.dirname(this.globalState.getStateFilePath()),`state_5.sqlite`)}__codexCwdSidecars(e){return[``, `-wal`, `-shm`].map(t=>`${e}${t}`).filter(e=>(0,o.existsSync)(e))}__codexCwdDatabase(){let e=require(`better-sqlite3`);return new e(this.__codexCwdStatePath())}__codexCwdLoadThreads(e){let t=this.__codexCwdDatabase();try{return t.prepare(`select id,cwd,rollout_path,title from threads`).all().filter(t=>this.__codexCwdNorm(t.cwd)===this.__codexCwdNorm(e))}finally{t.close()}}__codexCwdUpdateThreads(e,t){let n=this.__codexCwdDatabase();try{let r=n.prepare(`update threads set cwd = ? where id = ? and cwd = ?`),i=n.transaction(()=>{for(let n of e)r.run(this.__codexCwdReplacement(n.cwd,t),n.id,n.cwd)});i()}finally{n.close()}}__codexCwdBackup(e){let t=i.dirname(this.globalState.getStateFilePath()),n=i.join(t,`backups`,`cwd-retarget-${Date.now()}`);(0,o.mkdirSync)(n,{recursive:!0});let r=[...this.__codexCwdSidecars(this.__codexCwdStatePath()),this.globalState.getStateFilePath(),...e.map(e=>String(e.rollout_path??``).replace(/^\\\\\?\\/,""))];for(let e of r){if(!e||(0,o.existsSync)(e)!==!0)continue;try{if(!(0,o.statSync)(e).isFile())continue;let t=e.replace(/^[A-Za-z]:[\\/]/,e=>`${e[0]}__/`).replace(/[<>:"|?*]/g,`_`).replace(/[\\/]+/g,`__`);(0,o.copyFileSync)(e,i.join(n,t))}catch(e){$().warning(`Failed to back up cwd retarget file`,{safe:{},sensitive:{error:e}})}}return n}__codexCwdRewriteSessionFiles(e,t,n){let r=0;for(let a of e){let e=String(a.rollout_path??``).replace(/^\\\\\?\\/,"");if(!e||(0,o.existsSync)(e)!==!0)continue;let s=(0,o.readFileSync)(e,`utf8`),c=s.split(/(\r?\n)/),l=!1;for(let e=0;e<c.length;e+=2){let i=c[e];if(!i)continue;try{let a=JSON.parse(i),o=a?.payload?.cwd;typeof o==`string`&&this.__codexCwdNorm(o)===this.__codexCwdNorm(t)&&(a.payload.cwd=this.__codexCwdReplacement(o,n),c[e]=JSON.stringify(a),l=!0,r++)}catch{}}l&&(0,o.writeFileSync)(e,c.join(``),`utf8`)}return r}__codexCwdReplaceJson(e,t,n){if(typeof e==`string`)return this.__codexCwdNorm(e)===this.__codexCwdNorm(t)?{value:this.__codexCwdReplacement(e,n),changed:1}:{value:e,changed:0};if(Array.isArray(e)){let r=0,i=e.map(e=>{let a=this.__codexCwdReplaceJson(e,t,n);return r+=a.changed,a.value});return{value:i,changed:r}}if(e&&typeof e==`object`){let r=0,i={};for(let[a,o]of Object.entries(e)){let e=a;if(this.__codexCwdNorm(a)===this.__codexCwdNorm(t)&&(e=this.__codexCwdReplacement(a,n),r++),o!==void 0){let a=this.__codexCwdReplaceJson(o,t,n);r+=a.changed,i[e]=a.value}}return{value:i,changed:r}}return{value:e,changed:0}}__codexCwdRetargetGlobal(t,n){let r=0;for(let i of[e.Vt.WORKSPACE_ROOT_OPTIONS,e.Vt.ACTIVE_WORKSPACE_ROOTS,e.Vt.PROJECT_ORDER,e.Vt.PINNED_PROJECT_IDS,e.Vt.WORKSPACE_ROOT_LABELS,e.Vt.OPEN_IN_TARGET_PREFERENCES,e.Vt.SIDEBAR_PROJECT_THREAD_ORDERS,e.Vt.THREAD_WORKSPACE_ROOT_HINTS])this.globalState.update(i,e=>{let i=this.__codexCwdReplaceJson(e,t,n);return r+=i.changed,i.changed?i.value:e??void 0});return r}async __codexCwdRetargetWorkspaceRootOption(e,t){try{if(this.host.id!==`local`)return;let n=oe(t,this.host),r=await this.pickLocalWorkspaceRoot();if(r==null||this.__codexCwdNorm(n)===this.__codexCwdNorm(r))return;let i=this.__codexCwdLoadThreads(n),a=this.__codexCwdBackup(i);this.__codexCwdUpdateThreads(i,r);let o=this.__codexCwdRewriteSessionFiles(i,n,r),s=this.__codexCwdRetargetGlobal(n,r);await this.globalState.flush?.(),e.send(L,{type:`workspace-root-options-updated`}),e.send(L,{type:`active-workspace-roots-updated`}),e.send(L,{type:`navigate-to-route`,path:`/`,state:{focusComposerNonce:Date.now()}}),$().info(`Retargeted workspace root`,{safe:{threadCount:i.length,sessionCwdCount:o,globalStateCount:s},sensitive:{oldRoot:n,newRoot:r,backup:a}})}catch(n){$().error(`Failed to retarget workspace root`,{safe:{},sensitive:{error:n,root:t}})}}"""


def patch_cwd_main(content: bytes) -> bytes:
    text = content.decode("utf-8")
    changed = False

    if "__codexCwdRetargetWorkspaceRootOption" not in text:
        text = replace_once_text(
            text,
            "async addWorkspaceRootOption(e,n=!0,r){",
            CWD_RETARGET_MAIN_METHODS + "async addWorkspaceRootOption(e,n=!0,r){",
            "main cwd retarget methods",
        )
        changed = True

    if "electron-retarget-workspace-root-option" not in text:
        text = replace_once_text(
            text,
            "case`electron-add-new-workspace-root-option`:await this.addWorkspaceRootOption(r,!0,i.root);break;",
            "case`electron-retarget-workspace-root-option`:await this.__codexCwdRetargetWorkspaceRootOption(r,i.root);break;"
            "case`electron-add-new-workspace-root-option`:await this.addWorkspaceRootOption(r,!0,i.root);break;",
            "main cwd retarget message",
        )
        changed = True

    return text.encode("utf-8") if changed else content


def patch_cwd_renderer(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "sidebarElectron.retargetWorkspaceRootOption" in text:
        return content

    legacy_old = "let _e;t[46]!==o||t[47]!==ee?"
    legacy_new = (
        "let __codexCwdRetarget=()=>{d(!1),J.dispatchMessage(`electron-retarget-workspace-root-option`,{root:n})},"
        "__codexCwdRetargetItem=(0,$.jsx)(ml.Item,{LeftIcon:Qt,onSelect:__codexCwdRetarget,"
        "children:(0,$.jsx)(Y,{id:`sidebarElectron.retargetWorkspaceRootOption`,"
        "defaultMessage:`Change project folder`,description:`Menu item to choose a new filesystem path for a moved local project`})});"
        "let _e;t[46]!==o||t[47]!==ee?"
    )
    current_old = "let Ae;t[68]===Symbol.for(`react.memo_cache_sentinel`)?"
    current_new = (
        "let __codexCwdRetarget=()=>{d(!1),G.dispatchMessage(`electron-retarget-workspace-root-option`,{root:n})},"
        "__codexCwdRetargetLabel=(0,$.jsx)(Y,{id:`sidebarElectron.retargetWorkspaceRootOption`,"
        "defaultMessage:`Change project folder`,description:`Menu item to choose a new filesystem path for a moved local project`}),"
        "__codexCwdRetargetItem=(0,$.jsx)(af.Item,{LeftIcon:Xi,onSelect:__codexCwdRetarget,children:__codexCwdRetargetLabel});"
        "let Ae;t[68]===Symbol.for(`react.memo_cache_sentinel`)?"
    )
    if legacy_old in text:
        text = replace_once_text(text, legacy_old, legacy_new, "renderer cwd retarget menu item")
        text = replace_once_text(
            text,
            "children:[me,ge,_e,be,we,De]",
            "children:[me,ge,__codexCwdRetargetItem,_e,be,we,De]",
            "renderer cwd retarget menu placement",
        )
    elif "let _e;t[46]!==o||t[47]!==H?" in text:
        text = replace_once_text(
            text,
            "let _e;t[46]!==o||t[47]!==H?",
            legacy_new.replace("t[47]!==ee?", "t[47]!==H?"),
            "renderer cwd retarget menu item",
        )
        text = replace_once_text(
            text,
            "children:[me,ge,_e,be,we,De]",
            "children:[me,ge,__codexCwdRetargetItem,_e,be,we,De]",
            "renderer cwd retarget menu placement",
        )
    else:
        text = replace_once_text(text, current_old, current_new, "renderer cwd retarget menu item")
        text = replace_once_text(
            text,
            "children:[ve,be,xe,we,Oe,je]",
            "children:[ve,be,xe,we,Oe,__codexCwdRetargetItem,je]",
            "renderer cwd retarget menu placement",
        )

    return text.encode("utf-8")


def patch_cwd_locale(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "sidebarElectron.retargetWorkspaceRootOption" in text:
        return content
    text = replace_once_text(
        text,
        '"sidebarElectron.removeWorkspaceRootOption":`제거하기`,',
        '"sidebarElectron.removeWorkspaceRootOption":`제거하기`,'
        '"sidebarElectron.retargetWorkspaceRootOption":`프로젝트 경로 변경`,',
        "Korean cwd retarget label",
    )
    return text.encode("utf-8")


def patch_browser_use_route_fallback(content: bytes) -> bytes:
    text = content.decode("utf-8")
    changed = False

    if "resolved browser use route from registered conversation fallback" not in text:
        latest_old = (
            "resolveBrowserRoute(e){let t=this.turnRoutes.get(HF(e));if(t==null)throw LF().warning(`IAB_LIFECYCLE missing browser use turn route`,"
            "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`);"
            "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
            "LF().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
            "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
        )
        latest_new = (
            "resolveBrowserRoute(e){let t=this.turnRoutes.get(HF(e));if(t==null){if(this.options.browserRoute!=null&&"
            "e.conversationId===this.options.browserRoute.conversationId){let t=this.options.browserRoute;return this.assertWindowAlive(t),"
            "LF().warning(`IAB_LIFECYCLE resolved browser use route from conversation fallback`,{safe:{conversationId:t.conversationId,"
            "turnId:e.turnId,windowId:t.windowId},sensitive:{}}),t}"
            "let n=null;for(let t of this.windows.values())if(t.conversations.has(e.conversationId)&&this.delegate?.isWindowAlive(t.windowId)===!0)"
            "{n={conversationId:e.conversationId,windowId:t.windowId};break}"
            "if(n!=null)return this.assertWindowAlive(n),LF().warning(`IAB_LIFECYCLE resolved browser use route from registered conversation fallback`,"
            "{safe:{conversationId:n.conversationId,turnId:e.turnId,windowId:n.windowId},sensitive:{}}),n;"
            "throw LF().warning(`IAB_LIFECYCLE missing browser use turn route`,"
            "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`)}"
            "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
            "LF().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
            "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
        )
        current_old = latest_old.replace("HF(e)", "XC(e)").replace("LF()", "Y()")
        current_new = latest_new.replace("HF(e)", "XC(e)").replace("LF()", "Y()")
        current_202605_old = latest_old.replace("HF(e)", "KF(e)").replace("LF()", "VF()")
        current_202605_new = latest_new.replace("HF(e)", "KF(e)").replace("LF()", "VF()")
        original_old = latest_old.replace("HF(e)", "JC(e)").replace("LF()", "J()")
        original_new = latest_new.replace("HF(e)", "JC(e)").replace("LF()", "J()")
        for old, new, label in (
            (latest_old, latest_new, "browser-use latest route fallback"),
            (current_old, current_new, "browser-use current route fallback"),
            (current_202605_old, current_202605_new, "browser-use 2026-05 route fallback"),
            (original_old, original_new, "browser-use original route fallback"),
        ):
            if old in text:
                text = replace_once_text(text, old, new, label)
                changed = True
                break
        else:
            raise RuntimeError("Browser-use route fallback target not found")

    if "e.conversationId===t.conversationId&&this.delegate?.isWindowAlive(t.windowId)===!0" not in text:
        latest_old = (
            "canServeTurnForBrowserRoute(e,t){let n=this.turnRoutes.get(HF(e));return n==null||"
            "this.delegate?.isWindowAlive(n.windowId)!==!0?!1:n.conversationId===t.conversationId&&n.windowId===t.windowId}"
        )
        latest_new = (
            "canServeTurnForBrowserRoute(e,t){let n=this.turnRoutes.get(HF(e));return n==null?"
            "e.conversationId===t.conversationId&&this.delegate?.isWindowAlive(t.windowId)===!0:"
            "this.delegate?.isWindowAlive(n.windowId)!==!0?!1:n.conversationId===t.conversationId&&n.windowId===t.windowId}"
        )
        current_old = latest_old.replace("HF(e)", "XC(e)")
        current_new = latest_new.replace("HF(e)", "XC(e)")
        current_202605_old = latest_old.replace("HF(e)", "KF(e)")
        current_202605_new = latest_new.replace("HF(e)", "KF(e)")
        original_old = latest_old.replace("HF(e)", "JC(e)")
        original_new = latest_new.replace("HF(e)", "JC(e)")
        for old, new, label in (
            (latest_old, latest_new, "browser-use latest canServe fallback"),
            (current_old, current_new, "browser-use current canServe fallback"),
            (current_202605_old, current_202605_new, "browser-use 2026-05 canServe fallback"),
            (original_old, original_new, "browser-use original canServe fallback"),
        ):
            if old in text:
                text = replace_once_text(text, old, new, label)
                changed = True
                break
        else:
            raise RuntimeError("Browser-use canServe fallback target not found")

    return text.encode("utf-8") if changed else content


def patch_browser_use_alert_shim(content: bytes) -> bytes:
    text = content.decode("utf-8")
    if "__codexDesktopPatchAlertShim" in text:
        return content
    variants = [
        ("lf", "var lf={interactionMode:`browse`,isAgentControllingBrowser:!1,comments:[],intlConfig:p,viewportScale:1,zoomPercent:100},uf=!1,df=null;"),
        ("Vl", "var Vl={interactionMode:`browse`,isAgentControllingBrowser:!1,comments:[],intlConfig:p,viewportScale:1,zoomPercent:100},Hl=!1,Ul=null;"),
    ]
    for state_var, old in variants:
        if old not in text:
            continue
        new = old + (
            "(()=>{try{if(window.__codexDesktopPatchAlertShim)return;"
            "Object.defineProperty(window,`__codexDesktopPatchAlertShim`,{value:!0});"
            "let e=window.alert;window.alert=function(t){if(" + state_var + "?.isAgentControllingBrowser===!0)"
            "{try{console.warn(`[CodexDesktopPatch] suppressed alert during browser-use`,String(t??``))}catch{}return}"
            "return e.call(window,t)}}catch{}})();"
        )
        return replace_once_text(text, old, new, "browser-use alert shim").encode("utf-8")
    raise RuntimeError("Browser-use alert shim target not found")


def patch_app_identity_isolation(
    content: bytes, default_app_name: str, default_app_user_model_id: str
) -> bytes:
    text = content.decode("utf-8")
    changed = False
    app_name_literal = js_template_literal(default_app_name)
    app_user_model_id_literal = js_template_literal(default_app_user_model_id)

    if "__codexPatchedAppName" not in text:
        anchor = "var b=process.platform===`darwin`,x=t.T.resolve();"
        injected = (
            "var b=process.platform===`darwin`,__codexPatchedAppName=process.env."
            f"CODEX_PATCHED_APP_NAME?.trim()||`{app_name_literal}`,__codexPatchedRoot=(0,r.join)"
            "(n.app.getPath(`appData`),__codexPatchedAppName);process.env."
            "CODEX_ELECTRON_USER_DATA_PATH??=__codexPatchedRoot;process.env.CODEX_HOME??="
            "(0,r.join)(__codexPatchedRoot,`codex-home`);process.env."
            "CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION??=`1`;process.env."
            "CODEX_PATCHED_DISABLE_UPDATER??=`1`;var x=t.T.resolve();"
        )
        text = replace_once_text(text, anchor, injected, "app identity isolation bootstrap")
        changed = True

    app_name_old = "n.app.setName(e.G(x)),"
    app_name_new = "n.app.setName(__codexPatchedAppName),"
    if app_name_new not in text:
        text = replace_once_text(text, app_name_old, app_name_new, "patched app name")
        changed = True

    app_id_old = "process.platform===`win32`&&n.app.setAppUserModelId(t.b(x));"
    app_id_new = (
        "process.platform===`win32`&&n.app.setAppUserModelId(process.env."
        f"CODEX_PATCHED_APP_USER_MODEL_ID?.trim()||`{app_user_model_id_literal}`);"
    )
    if app_id_new not in text:
        text = replace_once_text(text, app_id_old, app_id_new, "patched app user model id")
        changed = True

    updater_old = "await i.initialize();try{"
    updater_new = (
        "process.env.CODEX_PATCHED_DISABLE_UPDATER===`0`&&await i.initialize();try{"
    )
    if updater_new not in text:
        text = replace_once_text(text, updater_old, updater_new, "patched updater isolation")
        changed = True

    required = [
        "__codexPatchedAppName",
        "CODEX_ELECTRON_USER_DATA_PATH??=__codexPatchedRoot",
        "process.env.CODEX_HOME??=(0,r.join)(__codexPatchedRoot,`codex-home`)",
        "CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION??=`1`",
        "CODEX_PATCHED_DISABLE_UPDATER??=`1`",
        "n.app.setName(__codexPatchedAppName)",
        default_app_user_model_id,
        "CODEX_PATCHED_DISABLE_UPDATER===`0`&&await i.initialize()",
    ]
    if any(marker not in text for marker in required):
        raise RuntimeError("App identity isolation verification failed")
    return text.encode("utf-8") if changed else content


def patch_system_registration_isolation(content: bytes) -> bytes:
    text = content.decode("utf-8")
    changed = False

    protocol_old = "oe.deepLinks.registerProtocolClient(),t.t(t.m(process.argv))"
    protocol_new = (
        "process.env.CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION===`0`&&"
        "oe.deepLinks.registerProtocolClient(),t.t(t.m(process.argv))"
    )
    if protocol_new not in text:
        text = replace_once_text(
            text,
            protocol_old,
            protocol_new,
            "patched protocol registration isolation",
        )
        changed = True

    context_marker = (
        "CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION===`0`&&await "
    )
    if context_marker not in text:
        text, count = re.subn(
            r"await ([A-Za-z_$][\w$]*)\(\{isWindows:E,isPackaged:n\.app\.isPackaged,executablePath:process\.execPath\}\),w\(`windows folder context menu registered`,A,\{isWindows:E\}\),",
            r"process.env.CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION===`0`&&await \1({isWindows:E,isPackaged:n.app.isPackaged,executablePath:process.execPath}),w(`windows folder context menu registered`,A,{isWindows:E}),",
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError("patched Windows context menu isolation target not found")
        changed = True

    required = [
        "CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION===`0`&&oe.deepLinks.registerProtocolClient()",
        context_marker,
    ]
    if any(marker not in text for marker in required):
        raise RuntimeError("System registration isolation verification failed")
    return text.encode("utf-8") if changed else content


def patch_browser_route_mini_window_main(content: bytes) -> bytes:
    text = content.decode("utf-8")
    changed = False
    if "openBrowserRouteMiniWindow(" not in text:
        method_anchor = "}}refreshCursor(e,t){let n=this.getCurrentPageCommandContext(e,t);"
        mini_method = (
            "}}async openBrowserRouteMiniWindow(e,t,r){try{let i=n.BrowserWindow.fromWebContents(e);"
            "if(i==null||i.isDestroyed())return;let a=this.windowManager.getHostIdForWebContents(e)??this.hostId,"
            "o=typeof r==`string`&&r.length>0?r:`/`,s=await this.windowManager.createWindow({title:`Codex Browser`,"
            "width:960,height:720,appearance:`secondary`,initialRoute:o,hostId:a,show:!0});"
            "s.setMenuBarVisibility(!1),s.setMinimumSize?.(720,480);let c=()=>{s.isDestroyed()||"
            "(this.windowManager.sendMessageToWebContents(s.webContents,{type:`navigate-to-route`,path:o,state:{focusComposerNonce:Date.now()}}),"
            "setTimeout(()=>{s.isDestroyed()||this.windowManager.sendMessageToWebContents(s.webContents,{type:`toggle-browser-panel`,open:!0,"
            "source:`browser_use`,initiator:`user`,conversationId:t})},150))};"
            "this.windowManager.isWebContentsReady?.(s.webContents.id)?c():s.webContents.once(`did-finish-load`,c),"
            "s.show(),s.focus()}catch(i){Q().warning(`failed to open browser route mini window`,"
            "{safe:{conversationId:t},sensitive:{error:i,path:r}})}}refreshCursor(e,t){let n=this.getCurrentPageCommandContext(e,t);"
        )
        text = replace_once_text(text, method_anchor, mini_method, "browser route mini window manager method")
        changed = True

    if "case`open-mini-window`:await this.browserSidebarManager.openBrowserRouteMiniWindow" not in text:
        old_case = (
            "case`capture-screenshot`:await this.browserSidebarManager.captureScreenshotToClipboard"
            "(r,i.conversationId);break;"
        )
        new_case = (
            "case`capture-screenshot`:await this.browserSidebarManager.captureScreenshotToClipboard"
            "(r,i.conversationId);break;case`open-mini-window`:await this.browserSidebarManager."
            "openBrowserRouteMiniWindow(r,i.conversationId,i.command.path);break;"
        )
        text = replace_once_text(text, old_case, new_case, "browser route mini window command")
        changed = True

    required = [
        "case`open-mini-window`:await this.browserSidebarManager.openBrowserRouteMiniWindow",
        "openBrowserRouteMiniWindow(e,t,r)",
        "type:`toggle-browser-panel`,open:!0",
        "type:`navigate-to-route`,path:o",
    ]
    if any(marker not in text for marker in required):
        raise RuntimeError("Browser route mini window main verification failed")
    return text.encode("utf-8") if changed else content


def patch_browser_route_mini_window_composer(content: bytes) -> bytes:
    text = content.decode("utf-8")
    hidden_mini_button = (
        "(0,Q.jsx)(is,{tooltipContent:y.formatMessage({id:`thread.browser.openMiniWindow`,"
        "defaultMessage:`Open in mini window`,description:`Tooltip text for opening the browser "
        "in a route-aware mini window`}),disabled:!Lt,children:(0,Q.jsx)(`button`,{type:`button`,"
        "\"data-browser-sidebar-skip-address-commit\":`true`,\"aria-label\":y.formatMessage({id:"
        "`thread.browser.openMiniWindow`,defaultMessage:`Open in mini window`,description:"
        "`Tooltip text for opening the browser in a route-aware mini window`}),disabled:!Lt,"
        "onPointerDown:Gt,onMouseDown:Gt,onClick:e=>{e.stopPropagation(),Xt()},className:Y("
        "`flex h-[28px] w-7 shrink-0 items-center justify-center rounded-[10px] text-token-"
        "description-foreground outline-none transition-[background-color]`,Ne?`opacity-100`:"
        "`opacity-0 group-hover/address-bar:opacity-100 group-focus-within/address-bar:"
        "opacity-100`,Lt?`cursor-interaction hover:bg-token-foreground/5 focus-visible:bg-token-"
        "foreground/5`:`cursor-default opacity-0`),children:(0,Q.jsx)(Js,{className:`icon-xs`})})})"
    )
    visible_mini_button = (
        "(0,Q.jsx)(is,{tooltipContent:y.formatMessage({id:`thread.browser.openMiniWindow`,"
        "defaultMessage:`Open in mini window`,description:`Tooltip text for opening the browser "
        "in a route-aware mini window`}),disabled:!Lt,children:(0,Q.jsx)(`button`,{type:`button`,"
        "\"data-browser-sidebar-skip-address-commit\":`true`,\"aria-label\":y.formatMessage({id:"
        "`thread.browser.openMiniWindow`,defaultMessage:`Open in mini window`,description:"
        "`Tooltip text for opening the browser in a route-aware mini window`}),disabled:!Lt,"
        "onPointerDown:Gt,onMouseDown:Gt,onClick:e=>{e.stopPropagation(),Xt()},className:Y("
        "`flex h-[28px] w-11 shrink-0 items-center justify-center rounded-[10px] px-2 text-[11px] "
        "font-medium text-token-description-foreground outline-none transition-[background-color]`,"
        "`opacity-100`,Lt?`cursor-interaction hover:bg-token-foreground/5 focus-visible:bg-token-"
        "foreground/5`:`cursor-default opacity-50`),children:`Mini`})})"
    )
    if "thread.browser.openMiniWindow" in text and "command:{type:`open-mini-window`,path:" in text:
        if "children:`Mini`" in text:
            return content
        if hidden_mini_button not in text:
            raise RuntimeError("Browser route mini window existing button target not found")
        text = replace_once_text(
            text,
            hidden_mini_button,
            visible_mini_button,
            "browser route mini window visible button",
        )
        return text.encode("utf-8")

    old_handler = (
        "Wt=e=>{e.trim().length!==0&&(En(g,{eventName:`codex_in_app_browser_opened_in_external_browser`}),"
        "$r.dispatchMessage(`open-in-browser`,{url:sl(e),useExternalBrowser:!0}))},Gt=e=>{"
    )
    new_handler = (
        "Wt=e=>{e.trim().length!==0&&(En(g,{eventName:`codex_in_app_browser_opened_in_external_browser`}),"
        "$r.dispatchMessage(`open-in-browser`,{url:sl(e),useExternalBrowser:!0}))},Xt=()=>{"
        "En(g,{eventName:`codex_in_app_browser_opened_in_route_mini_window`}),$r.dispatchMessage("
        "`browser-sidebar-command`,{conversationId:t,command:{type:`open-mini-window`,"
        "path:window.location.pathname+window.location.search}})},Gt=e=>{"
    )
    text = replace_once_text(text, old_handler, new_handler, "browser route mini window handler")

    old_button = (
        "children:(0,Q.jsx)(Js,{className:`icon-xs`})})})]})}),(0,Q.jsxs)(`div`,"
        "{className:`flex items-center justify-end gap-px`,children:["
    )
    mini_button = (
        "children:(0,Q.jsx)(Js,{className:`icon-xs`})})}),"
        + visible_mini_button
        + "]})}),(0,Q.jsxs)(`div`,{className:`flex items-center justify-end gap-px`,children:["
    )
    text = replace_once_text(text, old_button, mini_button, "browser route mini window button")
    required = [
        "thread.browser.openMiniWindow",
        "codex_in_app_browser_opened_in_route_mini_window",
        "command:{type:`open-mini-window`,path:window.location.pathname+window.location.search}",
        "onClick:e=>{e.stopPropagation(),Xt()}",
        "children:`Mini`",
    ]
    if any(item not in text for item in required):
        raise RuntimeError("Browser route mini window composer verification failed")
    return text.encode("utf-8")


def replace_asar_entries(asar_path: Path, replacements: dict[str, bytes]) -> bytes:
    data, header, _, _, data_start = read_asar_header(asar_path)
    files = []
    for path, entry in iter_file_entries(header):
        if "offset" not in entry:
            continue
        start = data_start + int(entry["offset"])
        end = start + int(entry["size"])
        content = replacements.get(path, data[start:end])
        files.append((path, entry, content))

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

def upsert_boolean_feature_config(
    config_path: Path,
    feature_name: str,
    enabled: bool,
    backup_dir: Path,
    dry_run: bool,
    backup_name: str,
) -> bool:
    config_text = config_path.read_text("utf-8") if config_path.exists() else ""
    value = "true" if enabled else "false"
    section_re = re.compile(r"^\[features\]\r?\n([\s\S]*?)(?=^\[[^\n]+\]\s*$|\Z)", re.M)
    feature_re = re.compile(
        rf"^(\s*{re.escape(feature_name)}\s*=\s*)(true|false)(\s*(?:#.*)?)$",
        re.M,
    )

    if section_re.search(config_text):
        def replace_section(match: re.Match[str]) -> str:
            section = match.group(0).rstrip()
            if feature_re.search(section):
                return feature_re.sub(rf"\g<1>{value}\g<3>", section, count=1) + "\n\n"
            return section + f"\n{feature_name} = {value}\n\n"

        new_text = section_re.sub(replace_section, config_text, count=1)
    else:
        section = f"[features]\n{feature_name} = {value}\n"
        first_section = re.search(r"^\[", config_text, re.M)
        if first_section:
            start = first_section.start()
            new_text = config_text[:start].rstrip() + "\n\n" + section + "\n" + config_text[start:]
        else:
            new_text = config_text.rstrip() + "\n\n" + section

    if new_text == config_text:
        return False
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            shutil.copy2(config_path, backup_dir / backup_name)
        config_path.write_text(new_text, "utf-8")
    return True


def verify_browser_client_default_backend(path: Path) -> None:
    require_existing_file(path, "Browser Use client")
    data = path.read_bytes()
    if BROWSER_CLIENT_DEFAULT_BACKEND_NEW in data or BROWSER_CLIENT_DEFAULT_BACKEND_OLD in data:
        return
    if b'var FO={cdp:"cdp",extension:"chrome",iab:"iab"}' in data and b'return"iab"' in data:
        return
    raise RuntimeError("Browser Use default backend marker not found")


def patch_browser_client_default_backend(path: Path, backup_dir: Path) -> bool:
    verify_browser_client_default_backend(path)
    data = path.read_bytes()
    if BROWSER_CLIENT_DEFAULT_BACKEND_NEW in data:
        return False
    if b'var FO={cdp:"cdp",extension:"chrome",iab:"iab"}' in data and b'return"iab"' in data:
        return False
    if data.count(BROWSER_CLIENT_DEFAULT_BACKEND_OLD) != 1:
        raise RuntimeError("Browser Use default backend marker is ambiguous")
    shutil.copy2(path, backup_dir / "browser-client.mjs.before-default-backend")
    ensure_writable_path(path)
    with path.open("r+b") as handle:
        position = data.find(BROWSER_CLIENT_DEFAULT_BACKEND_OLD)
        handle.seek(position)
        handle.write(BROWSER_CLIENT_DEFAULT_BACKEND_NEW)
    return True


def main() -> None:
    args = parse_args()
    home = default_windows_home()
    target_app_dir = Path(args.app_dir)
    app_dir = target_app_dir
    profile_mode = args.profile_mode
    if args.codex_home_dir is not None:
        codex_home_dir = Path(args.codex_home_dir)
    elif profile_mode == "isolated":
        codex_home_dir = home / "AppData/Roaming" / args.isolated_app_name / "codex-home"
    else:
        codex_home_dir = home / ".codex"
    source_app_dir = Path(args.source_app_dir) if args.source_app_dir else None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    synced_from_source = False
    archived_app_dir = None
    if args.sync_from_source:
        if source_app_dir is None:
            raise RuntimeError("No official Codex app directory found; pass --source-app-dir")
        if args.dry_run:
            app_dir = source_app_dir
        else:
            archived_app_dir = sync_app_from_source(source_app_dir, app_dir, stamp)
            synced_from_source = True

    exe_path = app_dir / "Codex.exe"
    asar_path = app_dir / "resources/app.asar"
    require_existing_app(app_dir)
    if not args.dry_run:
        ensure_writable_path(exe_path)
        ensure_writable_path(asar_path)

    backup_dir = target_app_dir / f"codexpatch-public-backup-{stamp}"
    if not args.dry_run:
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exe_path, backup_dir / "Codex.exe.before-public-patch")
        shutil.copy2(asar_path, backup_dir / "app.asar.before-public-patch")

    browser_target = app_dir / BROWSER_CLIENT_RELATIVE_PATH
    browser_backend_patched = False
    if args.dry_run:
        verify_browser_client_default_backend(browser_target)
    else:
        browser_backend_patched = patch_browser_client_default_backend(
            browser_target, backup_dir
        )

    data, header, _, _, data_start = read_asar_header(asar_path)
    replacements: dict[str, bytes] = {}
    touched_features = ["browser_client_default_iab_backend"]
    if upsert_boolean_feature_config(
        codex_home_dir / "config.toml",
        "goals",
        True,
        backup_dir,
        args.dry_run,
        "codex-home-config.toml.before-goals-feature",
    ):
        touched_features.append("codex_home_goals_feature_flag")

    bootstrap_entry_path = None
    bootstrap_payload = read_entry_content(
        data, data_start, find_entry(header, BOOTSTRAP_ENTRY_PATH)
    )
    if profile_mode == "isolated":
        bootstrap_entry_path = BOOTSTRAP_ENTRY_PATH
        bootstrap_payload = patch_app_identity_isolation(
            bootstrap_payload,
            args.isolated_app_name,
            args.isolated_app_user_model_id,
        )
        replacements[bootstrap_entry_path] = bootstrap_payload
        touched_features.append("app_identity_isolation")
    elif any(
        marker in bootstrap_payload.decode("utf-8", errors="ignore")
        for marker in (
            "CODEX_PATCHED_APP_NAME",
            "CODEX_ELECTRON_USER_DATA_PATH??=",
            "CODEX_HOME??=",
        )
    ):
        raise RuntimeError(
            "Shared profile mode cannot be applied to an already isolated app; "
            "use --sync-from-source or --profile-mode isolated."
        )

    main_entry_path = find_single_entry(header, "main bundle", MAIN_ENTRY_PREFIX)
    main_payload = read_entry_content(data, data_start, find_entry(header, main_entry_path))
    if profile_mode == "isolated":
        main_payload = patch_system_registration_isolation(main_payload)
        touched_features.append("system_registration_isolation")
    elif "CODEX_PATCHED_DISABLE_SYSTEM_REGISTRATION===`0`" in main_payload.decode(
        "utf-8", errors="ignore"
    ):
        raise RuntimeError(
            "Shared profile mode cannot be applied to an already isolated app; "
            "use --sync-from-source or --profile-mode isolated."
        )
    main_payload = patch_cwd_main(main_payload)
    touched_features.append("cwd_retarget_main")
    main_payload = patch_browser_use_route_fallback(main_payload)
    touched_features.append("browser_use_route_fallback")
    if not args.skip_browser_mini_window:
        main_payload = patch_browser_route_mini_window_main(main_payload)
        touched_features.append("browser_route_mini_window_main")
    replacements[main_entry_path] = main_payload

    renderer_entry_path = find_single_entry_by_markers(
        header,
        data,
        data_start,
        "renderer project sidebar bundle",
        ["sidebarElectron.removeWorkspaceRootOption", "electron-update-workspace-root-options"],
    )
    renderer_payload = read_entry_content(data, data_start, find_entry(header, renderer_entry_path))
    renderer_payload = patch_cwd_renderer(renderer_payload)
    replacements[renderer_entry_path] = renderer_payload
    touched_features.append("cwd_retarget_renderer")

    locale_entry_path = find_single_entry(header, "Korean locale bundle", KOREAN_LOCALE_PREFIX)
    locale_payload = read_entry_content(data, data_start, find_entry(header, locale_entry_path))
    locale_payload = patch_cwd_locale(locale_payload)
    replacements[locale_entry_path] = locale_payload
    touched_features.append("cwd_retarget_ko_locale")

    comment_preload_entry_path = COMMENT_PRELOAD_PATH
    comment_preload_payload = read_entry_content(
        data, data_start, find_entry(header, comment_preload_entry_path)
    )
    comment_preload_payload = patch_browser_use_alert_shim(comment_preload_payload)
    replacements[comment_preload_entry_path] = comment_preload_payload
    touched_features.append("browser_use_alert_shim")

    composer_entry_path = None
    if not args.skip_goal_ui_extensions or not args.skip_browser_mini_window:
        composer_entry_path = find_single_entry_by_markers(
            header,
            data,
            data_start,
            "composer bundle",
            ["codex_in_app_browser_opened_in_external_browser", "browser-sidebar-command"],
        )
        composer_payload = read_entry_content(data, data_start, find_entry(header, composer_entry_path))
        if not args.skip_goal_ui_extensions:
            composer_payload = patch_goal_slash_visibility(composer_payload)
            composer_payload = patch_plan_after_goal(composer_payload)
            touched_features.extend(
                [
                    "goal_slash_visibility",
                    "plan_after_goal",
                ]
            )
        if not args.skip_browser_mini_window:
            composer_payload = patch_browser_route_mini_window_composer(composer_payload)
            touched_features.append("browser_route_mini_window_composer")
        replacements[composer_entry_path] = composer_payload

    # Kept as a hidden backwards-compatible flag. It no longer enables the removed passive URL preview.
    if args.enable_browser_preview_window and args.skip_browser_mini_window:
        touched_features.append("deprecated_browser_preview_flag_ignored")

    if args.dry_run:
        print("dry_run=true")
        print(f"read_app_dir={app_dir}")
        print(f"target_app_dir={target_app_dir}")
        print(f"source_app_dir={source_app_dir}")
        print(f"sync_from_source={args.sync_from_source}")
        print(f"profile_mode={profile_mode}")
        if profile_mode == "isolated":
            print(f"isolated_app_name={args.isolated_app_name}")
            print(f"isolated_app_user_model_id={args.isolated_app_user_model_id}")
        print(f"would_backup_dir={backup_dir}")
        print("would_patch_browser_client_default_backend=True")
        print(f"replacement_entries={sorted(replacements)}")
        print(f"touched_features={touched_features}")
        return

    header_hash = replace_asar_entries(asar_path, replacements)
    old_hash, new_hash = refresh_exe_integrity(exe_path, header_hash)

    print(f"synced_from_source={synced_from_source}")
    print(f"archived_app_dir={archived_app_dir}")
    print(f"backup_dir={backup_dir}")
    print(f"browser_client_default_backend_patched={browser_backend_patched}")
    print(f"profile_mode={profile_mode}")
    if profile_mode == "isolated":
        print(f"isolated_app_name={args.isolated_app_name}")
        print(f"isolated_app_user_model_id={args.isolated_app_user_model_id}")
    print(f"bootstrap_entry={bootstrap_entry_path}")
    print(f"main_entry={main_entry_path}")
    print(f"renderer_entry={renderer_entry_path}")
    print(f"locale_entry={locale_entry_path}")
    print(f"comment_preload_entry={comment_preload_entry_path}")
    print(f"composer_entry={composer_entry_path}")
    print(f"touched_features={touched_features}")
    print(f"old_exe_header_hash={old_hash}")
    print(f"new_exe_header_hash={new_hash}")


if __name__ == "__main__":
    main()
