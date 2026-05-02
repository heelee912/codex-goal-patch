#!/usr/bin/env python3
from __future__ import annotations

import sys
import hashlib
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def find_asset(root: Path, pattern: str, marker: str, label: str) -> Path:
    assets = root / "webview/assets"
    matches = []
    for path in sorted(assets.glob(pattern)):
        try:
            if marker in path.read_text(encoding="utf-8"):
                matches.append(path)
        except UnicodeDecodeError:
            continue
    if len(matches) != 1:
        raise RuntimeError(f"{label}: expected 1 asset match, found {len(matches)}")
    return matches[0]


def patch_composer(root: Path) -> bool:
    path = find_asset(
        root,
        "composer-*.js",
        "function cU(e){let t=/^\\s*\\/side",
        "composer asset",
    )
    text = path.read_text(encoding="utf-8")
    changed = False

    old = "function cU(e){let t=/^\\s*\\/side(?:\\s+([\\s\\S]*?))?\\s*$/.exec(e);return t==null?null:t[1]?.trim()??``}"
    new = old + (
        "function __codexGoalParse(e){let t=/^\\s*\\/goal(?:\\s+([\\s\\S]*?))?\\s*$/.exec(e);"
        "return t==null?null:t[1]?.trim()??``}"
        "function __CodexGoalSlashCommand(){let e=(0,$.c)(17),t=Ci(Lv),n=t?.type===`local`?t.localConversationId:null,"
        "r=Ne(),i=Xo(),a;e[0]===i?a=e[1]:(a=i.formatMessage({id:`composer.goalSlashCommand.title`,"
        "defaultMessage:`Goal`,description:`Title for the goal slash command`}),e[0]=i,e[1]=a);"
        "let o;e[2]===i?o=e[3]:(o=i.formatMessage({id:`composer.goalSlashCommand.description`,"
        "defaultMessage:`Set this thread's goal`,description:`Description for the goal slash command`}),e[2]=i,e[3]=o);"
        "let s=n!=null,c,l;e[4]===r?(c=e[5],l=e[6]):(c=async()=>{r.setText(`/goal `),r.focus()},l=[r],e[4]=r,e[5]=c,e[6]=l);"
        "let u;return e[7]!==a||e[8]!==o||e[9]!==s||e[10]!==c||e[11]!==l?"
        "(u={id:`goal`,title:a,description:o,requiresEmptyComposer:!1,Icon:Kf,enabled:s,onSelect:c,dependencies:l},"
        "e[7]=a,e[8]=o,e[9]=s,e[10]=c,e[11]=l,e[12]=u):u=e[12],rx(u),null}"
    )
    if "__codexGoalParse" not in text:
        text = replace_once(text, old, new, "composer goal command insertion")
        changed = True

    old = (
        "let i=Mn.getText(),o=W&&n?.type===`local`?cU(i):null;"
        "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
    )
    new = (
        "let i=Mn.getText(),__goal=W&&n?.type===`local`?__codexGoalParse(i):null;"
        "if(__goal!=null){Ln(i),Rn();if(__goal.length===0){I.get(Il).danger(`Usage: /goal <objective>`),Di();return}"
        "Pt(!0);try{await ya(`set-thread-goal`,{conversationId:G,objective:__goal,status:`active`,tokenBudget:null}),"
        "I.get(Il).success(`Goal set`),Ro(),C?.()}catch(e){$o(e)}finally{Pt(!1),Di()}return}"
        "let o=W&&n?.type===`local`?cU(i):null;"
        "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
    )
    if "ya(`set-thread-goal`" not in text:
        text = replace_once(text, old, new, "composer submit parser insertion")
        changed = True

    old = (
        "return(0,Q.jsxs)(Q.Fragment,{children:[(0,Q.jsx)(tV,{composerMode:Jn,currentLocalExecutionCwd:hr,"
        "currentLocalExecutionHostId:or,effectiveIdeContextStatus:qr,effectiveIsAutoContextOn:Ur,resolvedCwd:Cn,"
        "setIsAutoContextOn:Br,setIsStatusMenuOpen:at,skillLookupRoots:Wi}),"
        "(0,Q.jsx)(sU,{enabled:Ko,onOpenSideChat:async()=>{try{await Jo(null)}catch(e){qo(e)}}}),"
    )
    new = (
        "return(0,Q.jsxs)(Q.Fragment,{children:[(0,Q.jsx)(tV,{composerMode:Jn,currentLocalExecutionCwd:hr,"
        "currentLocalExecutionHostId:or,effectiveIdeContextStatus:qr,effectiveIsAutoContextOn:Ur,resolvedCwd:Cn,"
        "setIsAutoContextOn:Br,setIsStatusMenuOpen:at,skillLookupRoots:Wi}),"
        "(0,Q.jsx)(__CodexGoalSlashCommand,{}),"
        "(0,Q.jsx)(sU,{enabled:Ko,onOpenSideChat:async()=>{try{await Jo(null)}catch(e){qo(e)}}}),"
    )
    if "(0,Q.jsx)(__CodexGoalSlashCommand,{})" not in text:
        text = replace_once(text, old, new, "composer command component render insertion")
        changed = True

    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_index(root: Path) -> bool:
    path = find_asset(
        root,
        "index-*.js",
        '"set-latest-collaboration-mode-for-conversation":dT',
        "index asset",
    )
    text = path.read_text(encoding="utf-8")
    if '"set-thread-goal":dT' in text:
        return False

    old = (
        '"set-latest-collaboration-mode-for-conversation":dT(async(e,{conversationId:t,collaborationMode:n})=>'
        "{await e.setLatestCollaborationModeForConversation(t,n)}),"
    )
    new = old + (
        '"set-thread-goal":dT(async(e,{conversationId:t,objective:n,status:r,tokenBudget:i})=>'
        "{try{await e.sendRequest(`thread/goal/clear`,{threadId:t})}catch{}"
        "await e.sendRequest(`thread/goal/set`,{threadId:t,objective:n,status:r??`active`,tokenBudget:i??null})}),"
    )
    text = replace_once(text, old, new, "index app action insertion")

    path.write_text(text, encoding="utf-8")
    return True


def asar_header_hash(path: Path) -> str:
    with path.open("rb") as f:
        header = f.read(16)
        if len(header) != 16:
            raise RuntimeError(f"{path}: too small to be an asar archive")
        header_json_size = int.from_bytes(header[12:16], "little")
        header_json = f.read(header_json_size)
        if len(header_json) != header_json_size:
            raise RuntimeError(f"{path}: truncated asar header")
    return hashlib.sha256(header_json).hexdigest()


def patch_exe_integrity(exe_path: Path, asar_path: Path) -> bool:
    expected = asar_header_hash(asar_path).encode("ascii")
    marker = b'"file":"resources\\\\app.asar","alg":"SHA256","value":"'
    data = exe_path.read_bytes()
    marker_index = data.find(marker)
    if marker_index < 0:
        raise RuntimeError(f"{exe_path}: could not find Electron asar integrity resource")
    hash_start = marker_index + len(marker)
    current = data[hash_start : hash_start + 64]
    if len(current) != 64 or data[hash_start + 64 : hash_start + 65] != b'"':
        raise RuntimeError(f"{exe_path}: malformed Electron asar integrity resource")
    if current == expected:
        return False

    backup_path = exe_path.with_name(exe_path.name + ".before-goalpatch-integrity")
    if not backup_path.exists():
        shutil.copy2(exe_path, backup_path)

    patched = data[:hash_start] + expected + data[hash_start + 64 :]
    exe_path.write_bytes(patched)
    return True


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--fix-integrity":
        app_root = Path(sys.argv[2]).resolve()
        changed = patch_exe_integrity(app_root / "Codex.exe", app_root / "resources/app.asar")
        print("updated Codex.exe asar integrity" if changed else "Codex.exe asar integrity already current")
        return 0

    if len(sys.argv) == 4 and sys.argv[1] == "--fix-integrity":
        changed = patch_exe_integrity(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
        print("updated Codex.exe asar integrity" if changed else "Codex.exe asar integrity already current")
        return 0

    if len(sys.argv) != 2:
        print(
            "usage: codex_goal_patch.py <extracted-app-asar-dir>\n"
            "       codex_goal_patch.py --fix-integrity <electron-app-dir>\n"
            "       codex_goal_patch.py --fix-integrity <codex-exe> <app-asar>",
            file=sys.stderr,
        )
        return 2
    root = Path(sys.argv[1]).resolve()
    changed = patch_composer(root) | patch_index(root)
    print("patched /goal command and set-thread-goal app action" if changed else "goal patch already applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
