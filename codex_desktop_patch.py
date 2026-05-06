#!/usr/bin/env python3
from __future__ import annotations

import sys
import hashlib
import shutil
import sqlite3
import time
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


def find_build_file(root: Path, pattern: str, marker: str, label: str) -> Path:
    assets = root / ".vite/build"
    matches = []
    for path in sorted(assets.glob(pattern)):
        try:
            if marker in path.read_text(encoding="utf-8"):
                matches.append(path)
        except UnicodeDecodeError:
            continue
    if len(matches) != 1:
        raise RuntimeError(f"{label}: expected 1 build file match, found {len(matches)}")
    return matches[0]


def patch_composer(root: Path) -> bool:
    path = find_asset(
        root,
        "composer-*.js",
        "/^\\s*\\/side",
        "composer asset",
    )
    text = path.read_text(encoding="utf-8")
    changed = False

    old = "function cU(e){let t=/^\\s*\\/side(?:\\s+([\\s\\S]*?))?\\s*$/.exec(e);return t==null?null:t[1]?.trim()??``}"
    current_side_parser = "function lU(e){let t=/^\\s*\\/side(?:\\s+([\\s\\S]*?))?\\s*$/.exec(e);return t==null?null:t[1]?.trim()??``}"
    goal_helpers = (
        "function __codexGoalParse(e){let t=/^\\s*\\/goal(?:\\s+([\\s\\S]*?))?\\s*$/.exec(e);"
        "return t==null?null:t[1]?.trim()??``}"
        "function __codexGoalPendingKey(){return`codexDesktopPatch.pendingGoal`}"
        "function __codexGoalNormCwd(e){return String(e??``).trim().replace(/^\\\\\\\\\\?\\\\/,``).replace(/\\//g,`\\\\`).replace(/\\\\+$/g,``).toLowerCase()}"
        "function __codexGoalSetPending(e,t){try{window.localStorage?.setItem(__codexGoalPendingKey(),JSON.stringify({objective:e,cwd:t??null,ts:Date.now()}))}catch{}}"
        "async function __codexGoalApplyPending(e,t){try{let n=__codexGoalPendingKey(),r=window.localStorage?.getItem(n);"
        "if(r==null)return!1;let i=JSON.parse(r),a=String(i?.objective??``).trim();if(!a)return window.localStorage?.removeItem(n),!1;"
        "if(Number.isFinite(i?.ts)&&Date.now()-i.ts>864e5)return window.localStorage?.removeItem(n),!1;"
        "if(i?.cwd&&t&&__codexGoalNormCwd(i.cwd)!==__codexGoalNormCwd(t))return!1;window.localStorage?.removeItem(n);"
        "await ya(`set-thread-goal`,{conversationId:e,objective:a,status:`active`,tokenBudget:null});return!0}catch(e){throw e}}"
        "function __CodexGoalSlashCommand({composerMode:e,resolvedCwd:t}={}){let n=(0,$.c)(20),r=Ci(Lv),i=r?.type===`local`?r.localConversationId:null,"
        "a=Ne(),o=Xo(),s;n[0]===o?s=n[1]:(s=o.formatMessage({id:`composer.goalSlashCommand.title`,"
        "defaultMessage:`Goal`,description:`Title for the goal slash command`}),n[0]=o,n[1]=s);"
        "let c;n[2]===o?c=n[3]:(c=o.formatMessage({id:`composer.goalSlashCommand.description`,"
        "defaultMessage:`Set this thread's goal`,description:`Description for the goal slash command`}),n[2]=o,n[3]=c);"
        "let l=i!=null||e===`local`,u,d;n[4]===a?(u=n[5],d=n[6]):(u=async()=>{a.setText(`/goal `),a.focus()},d=[a],n[4]=a,n[5]=u,n[6]=d);"
        "let f;return n[7]!==s||n[8]!==c||n[9]!==l||n[10]!==u||n[11]!==d||n[12]!==e||n[13]!==t?"
        "(f={id:`goal`,title:s,description:c,requiresEmptyComposer:!1,Icon:Kf,enabled:l,onSelect:u,dependencies:[...d,e,t]},"
        "n[7]=s,n[8]=c,n[9]=l,n[10]=u,n[11]=d,n[12]=e,n[13]=t,n[14]=f):f=n[14],rx(f),null}"
    )
    current_goal_helpers = goal_helpers.replace("Ci(Lv)", "Ci(Rv)").replace("Icon:Kf", "Icon:B_").replace("rx(f)", "ix(f)")
    new = old + goal_helpers
    if "__codexGoalParse" not in text:
        if old in text:
            text = replace_once(text, old, new, "composer goal command insertion")
        elif current_side_parser in text:
            text = replace_once(
                text,
                current_side_parser,
                current_side_parser + current_goal_helpers,
                "composer goal command insertion",
            )
        else:
            raise RuntimeError("composer side slash parser: expected 1 known parser match, found 0")
        changed = True
    elif "__codexGoalPendingKey" not in text:
        old_goal_helpers = (
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
        text = replace_once(text, old_goal_helpers, goal_helpers, "composer goal home support upgrade")
        changed = True
    if "let f;n[7]!==s||n[8]!==c||n[9]!==l||n[10]!==u||n[11]!==d||n[12]!==e||n[13]!==t?" in text:
        text = replace_once(
            text,
            "let f;n[7]!==s||n[8]!==c||n[9]!==l||n[10]!==u||n[11]!==d||n[12]!==e||n[13]!==t?",
            "let f;return n[7]!==s||n[8]!==c||n[9]!==l||n[10]!==u||n[11]!==d||n[12]!==e||n[13]!==t?",
            "composer goal command return upgrade",
        )
        changed = True

    old = (
        "let i=Mn.getText(),o=W&&n?.type===`local`?cU(i):null;"
        "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
    )
    new = (
        "let i=Mn.getText(),__goal=W&&(n?.type===`local`||Jn===`local`)?__codexGoalParse(i):null;"
        "if(__goal!=null){Ln(i),Rn();if(__goal.length===0){I.get(Il).danger(`Usage: /goal <objective>`),Di();return}"
        "if(G==null){__codexGoalSetPending(__goal,hr),I.get(Il).success(`Goal queued for next chat`),Ro(),Di();return}"
        "Pt(!0);try{await ya(`set-thread-goal`,{conversationId:G,objective:__goal,status:`active`,tokenBudget:null}),"
        "I.get(Il).success(`Goal set`),Ro(),C?.()}catch(e){$o(e)}finally{Pt(!1),Di()}return}"
        "let o=W&&n?.type===`local`?cU(i):null;"
        "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
    )
    old_goal_submit_set_only = (
        "let i=Mn.getText(),__goal=W&&(n?.type===`local`||Jn===`local`)?__codexGoalParse(i):null;"
        "if(__goal!=null){Ln(i),Rn();if(__goal.length===0){I.get(Il).danger(`Usage: /goal <objective>`),Di();return}"
        "if(G==null){__codexGoalSetPending(__goal,hr),I.get(Il).success(`Goal queued for next chat`),Ro(),Di();return}"
        "Pt(!0);try{await ya(`set-thread-goal`,{conversationId:G,objective:__goal,status:`active`,tokenBudget:null}),"
        "I.get(Il).success(`Goal set`),Ro(),C?.()}catch(e){$o(e)}finally{Pt(!1),Di()}return}"
        "let o=W&&n?.type===`local`?cU(i):null;"
        "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
    )
    if "Usage: /goal <objective>" not in text:
        if old in text:
            text = replace_once(text, old, new, "composer submit parser insertion")
        else:
            old_current = (
                "let i=Mn.getText(),o=W&&n?.type===`local`?lU(i):null;"
                "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
            )
            new_current = new.replace("?cU(i):null;", "?lU(i):null;")
            text = replace_once(text, old_current, new_current, "composer submit parser insertion")
        changed = True
    elif "i=__goal}else{Pt(!0);try" in text:
        autostart_goal_submit = (
            "let i=Mn.getText(),__goal=W&&(n?.type===`local`||Jn===`local`)?__codexGoalParse(i):null;"
            "if(__goal!=null){if(__goal.length===0){I.get(Il).danger(`Usage: /goal <objective>`),Di();return}"
            "if(G==null){__codexGoalSetPending(__goal,hr),I.get(Il).success(`Goal queued for next chat`),i=__goal}"
            "else{Pt(!0);try{await ya(`set-thread-goal`,{conversationId:G,objective:__goal,status:`active`,tokenBudget:null}),"
            "I.get(Il).success(`Goal set`),i=__goal}catch(e){$o(e),Di();return}finally{Pt(!1)}}}"
            "let o=W&&n?.type===`local`?cU(i):null;"
            "if(o!=null){Ln(i),Rn(),Pt(!0);try{await Jo(o)&&(Ro(),C?.())}catch(e){qo(e)}finally{Pt(!1),Di()}return}"
        )
        autostart_goal_submit_current = autostart_goal_submit.replace("?cU(i):null;", "?lU(i):null;")
        new_current = new.replace("?cU(i):null;", "?lU(i):null;")
        if autostart_goal_submit_current in text:
            text = replace_once(
                text,
                autostart_goal_submit_current,
                new_current,
                "composer goal submit real runtime restore",
            )
        else:
            text = replace_once(
                text,
                autostart_goal_submit,
                new,
                "composer goal submit real runtime restore",
            )
        changed = True
    elif "Goal queued for next chat" not in text:
        old_goal_submit = (
            "let i=Mn.getText(),__goal=W&&n?.type===`local`?__codexGoalParse(i):null;"
            "if(__goal!=null){Ln(i),Rn();if(__goal.length===0){I.get(Il).danger(`Usage: /goal <objective>`),Di();return}"
            "Pt(!0);try{await ya(`set-thread-goal`,{conversationId:G,objective:__goal,status:`active`,tokenBudget:null}),"
            "I.get(Il).success(`Goal set`),Ro(),C?.()}catch(e){$o(e)}finally{Pt(!1),Di()}return}"
        )
        new_goal_submit = (
            "let i=Mn.getText(),__goal=W&&(n?.type===`local`||Jn===`local`)?__codexGoalParse(i):null;"
            "if(__goal!=null){Ln(i),Rn();if(__goal.length===0){I.get(Il).danger(`Usage: /goal <objective>`),Di();return}"
            "if(G==null){__codexGoalSetPending(__goal,hr),I.get(Il).success(`Goal queued for next chat`),Ro(),Di();return}"
            "Pt(!0);try{await ya(`set-thread-goal`,{conversationId:G,objective:__goal,status:`active`,tokenBudget:null}),"
            "I.get(Il).success(`Goal set`),Ro(),C?.()}catch(e){$o(e)}finally{Pt(!1),Di()}return}"
        )
        text = replace_once(text, old_goal_submit, new_goal_submit, "composer goal submit home support")
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
    if (
        "(0,Q.jsx)(__CodexGoalSlashCommand,{})" not in text
        and "(0,Q.jsx)(__CodexGoalSlashCommand,{composerMode:Jn,resolvedCwd:hr})" not in text
    ):
        if old in text:
            text = replace_once(text, old, new, "composer command component render insertion")
        else:
            old_current = (
                "return(0,Q.jsxs)(Q.Fragment,{children:[(0,Q.jsx)(nV,{composerMode:Jn,currentLocalExecutionCwd:hr,"
                "currentLocalExecutionHostId:or,effectiveIdeContextStatus:qr,effectiveIsAutoContextOn:Ur,resolvedCwd:Cn,"
                "setIsAutoContextOn:Br,setIsStatusMenuOpen:at,skillLookupRoots:Wi}),"
                "(0,Q.jsx)(cU,{enabled:Ko,onOpenSideChat:async()=>{try{await Jo(null)}catch(e){qo(e)}}}),"
            )
            new_current = (
                "return(0,Q.jsxs)(Q.Fragment,{children:[(0,Q.jsx)(nV,{composerMode:Jn,currentLocalExecutionCwd:hr,"
                "currentLocalExecutionHostId:or,effectiveIdeContextStatus:qr,effectiveIsAutoContextOn:Ur,resolvedCwd:Cn,"
                "setIsAutoContextOn:Br,setIsStatusMenuOpen:at,skillLookupRoots:Wi}),"
                "(0,Q.jsx)(__CodexGoalSlashCommand,{composerMode:Jn,resolvedCwd:hr}),"
                "(0,Q.jsx)(cU,{enabled:Ko,onOpenSideChat:async()=>{try{await Jo(null)}catch(e){qo(e)}}}),"
            )
            text = replace_once(text, old_current, new_current, "composer command component render insertion")
        changed = True
    elif "(0,Q.jsx)(__CodexGoalSlashCommand,{composerMode:Jn,resolvedCwd:hr})" not in text:
        text = replace_once(
            text,
            "(0,Q.jsx)(__CodexGoalSlashCommand,{}),",
            "(0,Q.jsx)(__CodexGoalSlashCommand,{composerMode:Jn,resolvedCwd:hr}),",
            "composer goal command home props",
        )
        changed = True

    if "__codexGoalApplyPending(p,u)" not in text:
        old_pending = "p=await q({attachments:Ka([...f.attachments??[],...s]),baseParams:f,hostId:o});wI(D,p,G,d.config),Xu(K,p,o,d.agentMode),"
        new_pending = (
            "p=await q({attachments:Ka([...f.attachments??[],...s]),baseParams:f,hostId:o});"
            "try{await __codexGoalApplyPending(p,u)&&D.get(Il).success(`Goal set`)}catch(e){Ho.warning(`[Composer] failed to apply queued goal`,{safe:{},sensitive:{error:e}}),D.get(Il).danger(`Failed to set queued goal`)}"
            "wI(D,p,G,d.config),Xu(K,p,o,d.agentMode),"
        )
        if old_pending in text:
            text = replace_once(text, old_pending, new_pending, "composer apply pending goal after new conversation")
        else:
            old_pending_current = "p=await ee({attachments:Ka([...f.attachments??[],...s]),baseParams:f,hostId:o});TI(D,p,G,d.config),Xu(K,p,o,d.agentMode),"
            new_pending_current = (
                "p=await ee({attachments:Ka([...f.attachments??[],...s]),baseParams:f,hostId:o});"
                "try{await __codexGoalApplyPending(p,u)&&D.get(Il).success(`Goal set`)}catch(e){Ho.warning(`[Composer] failed to apply queued goal`,{safe:{},sensitive:{error:e}}),D.get(Il).danger(`Failed to set queued goal`)}"
                "TI(D,p,G,d.config),Xu(K,p,o,d.agentMode),"
            )
            text = replace_once(text, old_pending_current, new_pending_current, "composer apply pending goal after new conversation")
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

    old = (
        '"set-latest-collaboration-mode-for-conversation":dT(async(e,{conversationId:t,collaborationMode:n})=>'
        "{await e.setLatestCollaborationModeForConversation(t,n)}),"
    )
    goal_action_old = (
        '"set-thread-goal":dT(async(e,{conversationId:t,objective:n,status:r,tokenBudget:i})=>'
        "{try{await e.sendRequest(`thread/goal/clear`,{threadId:t})}catch{}"
        "await e.sendRequest(`thread/goal/set`,{threadId:t,objective:n,status:r??`active`,tokenBudget:i??null})}),"
    )
    goal_action_new = (
        '"set-thread-goal":dT(async(e,{conversationId:t,objective:n,status:r,tokenBudget:i})=>'
        "{try{await e.sendRequest(`thread/goal/clear`,{threadId:t})}catch{}"
        "await e.sendRequest(`thread/goal/set`,{threadId:t,objective:n,status:r??`active`,tokenBudget:i??null});"
        "await e.sendRequest(`thread/resume`,{threadId:t})}),"
    )

    if goal_action_new in text:
        return False
    if goal_action_old in text:
        text = replace_once(text, goal_action_old, goal_action_new, "index goal action resume upgrade")
    else:
        text = replace_once(text, old, old + goal_action_new, "index app action insertion")

    path.write_text(text, encoding="utf-8")
    return True


CWD_RETARGET_MAIN_METHODS = r"""__codexCwdNorm(e){return String(e??``).trim().replace(/^\\\\\?\\/,"").replace(/\//g,`\\`).replace(/\\+$/g,``).toLowerCase()}__codexCwdReplacement(e,t){return String(e??``).startsWith(`\\\\?\\`)?`\\\\?\\${t}`:t}__codexCwdStatePath(){return i.join(i.dirname(this.globalState.getStateFilePath()),`state_5.sqlite`)}__codexCwdSidecars(e){return[``, `-wal`, `-shm`].map(t=>`${e}${t}`).filter(e=>o.existsSync(e))}__codexCwdDatabase(){let e=require(`better-sqlite3`);return new e(this.__codexCwdStatePath())}__codexCwdLoadThreads(e){let t=this.__codexCwdDatabase();try{return t.prepare(`select id,cwd,rollout_path,title from threads`).all().filter(t=>this.__codexCwdNorm(t.cwd)===this.__codexCwdNorm(e))}finally{t.close()}}__codexCwdUpdateThreads(e,t){let n=this.__codexCwdDatabase();try{let r=n.prepare(`update threads set cwd = ? where id = ? and cwd = ?`),i=n.transaction(()=>{for(let n of e)r.run(this.__codexCwdReplacement(n.cwd,t),n.id,n.cwd)});i()}finally{n.close()}}__codexCwdBackup(e){let t=i.dirname(this.globalState.getStateFilePath()),n=i.join(t,`backups`,`cwd-retarget-${Date.now()}`);o.mkdirSync(n,{recursive:!0});let r=[...this.__codexCwdSidecars(this.__codexCwdStatePath()),this.globalState.getStateFilePath(),...e.map(e=>String(e.rollout_path??``).replace(/^\\\\\?\\/,""))];for(let e of r){if(!e||!o.existsSync(e))continue;try{if(!o.statSync(e).isFile())continue;let t=e.replace(/^[A-Za-z]:[\\/]/,e=>`${e[0]}__/`).replace(/[<>:"|?*]/g,`_`).replace(/[\\/]+/g,`__`);o.copyFileSync(e,i.join(n,t))}catch(e){X().warning(`Failed to back up cwd retarget file`,{safe:{},sensitive:{error:e}})}}return n}__codexCwdRewriteSessionFiles(e,t,n){let r=0;for(let a of e){let e=String(a.rollout_path??``).replace(/^\\\\\?\\/,"");if(!e||!o.existsSync(e))continue;let s=o.readFileSync(e,`utf8`),c=s.split(/(\r?\n)/),l=!1;for(let e=0;e<c.length;e+=2){let i=c[e];if(!i)continue;try{let a=JSON.parse(i),o=a?.payload?.cwd;typeof o==`string`&&this.__codexCwdNorm(o)===this.__codexCwdNorm(t)&&(a.payload.cwd=this.__codexCwdReplacement(o,n),c[e]=JSON.stringify(a),l=!0,r++)}catch{}}l&&o.writeFileSync(e,c.join(``),`utf8`)}return r}__codexCwdReplaceJson(e,t,n){if(typeof e==`string`)return this.__codexCwdNorm(e)===this.__codexCwdNorm(t)?{value:this.__codexCwdReplacement(e,n),changed:1}:{value:e,changed:0};if(Array.isArray(e)){let r=0,i=e.map(e=>{let a=this.__codexCwdReplaceJson(e,t,n);return r+=a.changed,a.value});return{value:i,changed:r}}if(e&&typeof e==`object`){let r=0,i={};for(let[a,o]of Object.entries(e)){let e=a;if(this.__codexCwdNorm(a)===this.__codexCwdNorm(t)&&(e=this.__codexCwdReplacement(a,n),r++),o!==void 0){let a=this.__codexCwdReplaceJson(o,t,n);r+=a.changed,i[e]=a.value}}return{value:i,changed:r}}return{value:e,changed:0}}__codexCwdRetargetGlobal(t,n){let r=0;for(let i of[e.Rt.WORKSPACE_ROOT_OPTIONS,e.Rt.ACTIVE_WORKSPACE_ROOTS,e.Rt.PROJECT_ORDER,e.Rt.PINNED_PROJECT_IDS,e.Rt.WORKSPACE_ROOT_LABELS,e.Rt.OPEN_IN_TARGET_PREFERENCES,e.Rt.SIDEBAR_PROJECT_THREAD_ORDERS,e.Rt.THREAD_WORKSPACE_ROOT_HINTS])this.globalState.update(i,e=>{let i=this.__codexCwdReplaceJson(e,t,n);return r+=i.changed,i.changed?i.value:e??void 0});return r}async __codexCwdRetargetWorkspaceRootOption(e,t){try{if(this.host.id!==`local`)return;let n=re(t,this.host),r=await this.pickLocalWorkspaceRoot();if(r==null||this.__codexCwdNorm(n)===this.__codexCwdNorm(r))return;let i=this.__codexCwdLoadThreads(n),a=this.__codexCwdBackup(i);this.__codexCwdUpdateThreads(i,r);let o=this.__codexCwdRewriteSessionFiles(i,n,r),s=this.__codexCwdRetargetGlobal(n,r);await this.globalState.flush?.(),e.send(H,{type:`workspace-root-options-updated`}),e.send(H,{type:`active-workspace-roots-updated`}),e.send(H,{type:`navigate-to-route`,path:`/`,state:{focusComposerNonce:Date.now()}}),X().info(`Retargeted workspace root`,{safe:{threadCount:i.length,sessionCwdCount:o,globalStateCount:s},sensitive:{oldRoot:n,newRoot:r,backup:a}})}catch(n){X().error(`Failed to retarget workspace root`,{safe:{},sensitive:{error:n,root:t}})}}"""


def patch_cwd_main(root: Path) -> bool:
    path = find_build_file(
        root,
        "main-*.js",
        "async addWorkspaceRootOption(e,n=!0,r){",
        "main asset",
    )
    text = path.read_text(encoding="utf-8")
    changed = False

    if "__codexCwdRetargetWorkspaceRootOption" not in text:
        text = replace_once(
            text,
            "async addWorkspaceRootOption(e,n=!0,r){",
            CWD_RETARGET_MAIN_METHODS + "async addWorkspaceRootOption(e,n=!0,r){",
            "main cwd retarget methods",
        )
        changed = True

    if "electron-retarget-workspace-root-option" not in text:
        text = replace_once(
            text,
            "case`electron-add-new-workspace-root-option`:await this.addWorkspaceRootOption(r,!0,i.root);break;",
            "case`electron-retarget-workspace-root-option`:await this.__codexCwdRetargetWorkspaceRootOption(r,i.root);break;"
            "case`electron-add-new-workspace-root-option`:await this.addWorkspaceRootOption(r,!0,i.root);break;",
            "main cwd retarget message",
        )
        changed = True

    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_cwd_renderer(root: Path) -> bool:
    path = find_asset(
        root,
        "index-*.js",
        "sidebarElectron.removeWorkspaceRootOption",
        "renderer index asset",
    )
    text = path.read_text(encoding="utf-8")
    if "sidebarElectron.retargetWorkspaceRootOption" in text:
        return False

    old = "let _e;t[46]!==o||t[47]!==ee?"
    new = (
        "let __codexCwdRetarget=()=>{d(!1),J.dispatchMessage(`electron-retarget-workspace-root-option`,{root:n})},"
        "__codexCwdRetargetItem=(0,$.jsx)(ml.Item,{LeftIcon:Qt,onSelect:__codexCwdRetarget,"
        "children:(0,$.jsx)(Y,{id:`sidebarElectron.retargetWorkspaceRootOption`,"
        "defaultMessage:`Change project folder`,description:`Menu item to choose a new filesystem path for a moved local project`})});"
        "let _e;t[46]!==o||t[47]!==ee?"
    )
    if old in text:
        text = replace_once(text, old, new, "renderer cwd retarget menu item")
    else:
        old_current = "let _e;t[46]!==o||t[47]!==H?"
        new_current = new.replace("t[47]!==ee?", "t[47]!==H?")
        text = replace_once(text, old_current, new_current, "renderer cwd retarget menu item")
    text = replace_once(
        text,
        "children:[me,ge,_e,be,we,De]",
        "children:[me,ge,__codexCwdRetargetItem,_e,be,we,De]",
        "renderer cwd retarget menu placement",
    )

    path.write_text(text, encoding="utf-8")
    return True


def patch_cwd_locale(root: Path) -> bool:
    path = find_asset(
        root,
        "ko-KR-*.js",
        "sidebarElectron.removeWorkspaceRootOption",
        "Korean locale asset",
    )
    text = path.read_text(encoding="utf-8")
    if "sidebarElectron.retargetWorkspaceRootOption" in text:
        return False

    text = replace_once(
        text,
        '"sidebarElectron.removeWorkspaceRootOption":`제거하기`,',
        '"sidebarElectron.removeWorkspaceRootOption":`제거하기`,'
        '"sidebarElectron.retargetWorkspaceRootOption":`프로젝트 경로 변경`,',
        "Korean cwd retarget label",
    )
    path.write_text(text, encoding="utf-8")
    return True


def patch_cwd_retarget(root: Path) -> bool:
    return patch_cwd_main(root) | patch_cwd_renderer(root) | patch_cwd_locale(root)


def patch_browser_use_iab_route_fallback(root: Path) -> bool:
    path = find_build_file(
        root,
        "main-*.js",
        "resolveBrowserRoute(e){let t=this.turnRoutes.get(",
        "main browser-use asset",
    )
    text = path.read_text(encoding="utf-8")
    changed = False

    original_old = (
        "resolveBrowserRoute(e){let t=this.turnRoutes.get(JC(e));if(t==null)throw J().warning(`IAB_LIFECYCLE missing browser use turn route`,"
        "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`);"
        "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
        "J().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
        "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
    )
    previous_fallback = (
        "resolveBrowserRoute(e){let t=this.turnRoutes.get(JC(e));if(t==null){if(this.options.browserRoute!=null&&"
        "e.conversationId===this.options.browserRoute.conversationId){let t=this.options.browserRoute;return this.assertWindowAlive(t),"
        "J().warning(`IAB_LIFECYCLE resolved browser use route from conversation fallback`,{safe:{conversationId:t.conversationId,"
        "turnId:e.turnId,windowId:t.windowId},sensitive:{}}),t}throw J().warning(`IAB_LIFECYCLE missing browser use turn route`,"
        "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`)}"
        "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
        "J().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
        "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
    )
    new = (
        "resolveBrowserRoute(e){let t=this.turnRoutes.get(JC(e));if(t==null){if(this.options.browserRoute!=null&&"
        "e.conversationId===this.options.browserRoute.conversationId){let t=this.options.browserRoute;return this.assertWindowAlive(t),"
        "J().warning(`IAB_LIFECYCLE resolved browser use route from conversation fallback`,{safe:{conversationId:t.conversationId,"
        "turnId:e.turnId,windowId:t.windowId},sensitive:{}}),t}"
        "let n=null;for(let t of this.windows.values())if(t.conversations.has(e.conversationId)&&this.delegate?.isWindowAlive(t.windowId)===!0)"
        "{n={conversationId:e.conversationId,windowId:t.windowId};break}"
        "if(n!=null)return this.assertWindowAlive(n),J().warning(`IAB_LIFECYCLE resolved browser use route from registered conversation fallback`,"
        "{safe:{conversationId:n.conversationId,turnId:e.turnId,windowId:n.windowId},sensitive:{}}),n;"
        "throw J().warning(`IAB_LIFECYCLE missing browser use turn route`,"
        "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`)}"
        "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
        "J().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
        "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
    )
    if "resolved browser use route from registered conversation fallback" not in text:
        if "resolved browser use route from conversation fallback" in text:
            text = replace_once(text, previous_fallback, new, "browser-use IAB route fallback upgrade")
            changed = True
        elif original_old in text:
            text = replace_once(text, original_old, new, "browser-use IAB route fallback")
            changed = True
        else:
            current_old = (
                "resolveBrowserRoute(e){let t=this.turnRoutes.get(XC(e));if(t==null)throw Y().warning(`IAB_LIFECYCLE missing browser use turn route`,"
                "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`);"
                "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
                "Y().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
                "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
            )
            current_new = (
                "resolveBrowserRoute(e){let t=this.turnRoutes.get(XC(e));if(t==null){if(this.options.browserRoute!=null&&"
                "e.conversationId===this.options.browserRoute.conversationId){let t=this.options.browserRoute;return this.assertWindowAlive(t),"
                "Y().warning(`IAB_LIFECYCLE resolved browser use route from conversation fallback`,{safe:{conversationId:t.conversationId,"
                "turnId:e.turnId,windowId:t.windowId},sensitive:{}}),t}"
                "let n=null;for(let t of this.windows.values())if(t.conversations.has(e.conversationId)&&this.delegate?.isWindowAlive(t.windowId)===!0)"
                "{n={conversationId:e.conversationId,windowId:t.windowId};break}"
                "if(n!=null)return this.assertWindowAlive(n),Y().warning(`IAB_LIFECYCLE resolved browser use route from registered conversation fallback`,"
                "{safe:{conversationId:n.conversationId,turnId:e.turnId,windowId:n.windowId},sensitive:{}}),n;"
                "throw Y().warning(`IAB_LIFECYCLE missing browser use turn route`,"
                "{safe:e,sensitive:{}}),Error(`No Codex browser route captured for browser session ${e.conversationId} turn ${e.turnId}`)}"
                "let n={conversationId:t.conversationId,windowId:t.windowId};return this.assertWindowAlive(n),"
                "Y().info(`IAB_LIFECYCLE resolved browser use route`,{safe:{conversationId:t.conversationId,"
                "ownerWebContentsId:t.ownerWebContentsId,turnId:t.turnId,windowId:t.windowId},sensitive:{}}),n}"
            )
            text = replace_once(text, current_old, current_new, "browser-use IAB route fallback")
            changed = True

    old = (
        "canServeTurnForBrowserRoute(e,t){let n=this.turnRoutes.get(JC(e));return n==null||"
        "this.delegate?.isWindowAlive(n.windowId)!==!0?!1:n.conversationId===t.conversationId&&n.windowId===t.windowId}"
    )
    new = (
        "canServeTurnForBrowserRoute(e,t){let n=this.turnRoutes.get(JC(e));return n==null?"
        "e.conversationId===t.conversationId&&this.delegate?.isWindowAlive(t.windowId)===!0:"
        "this.delegate?.isWindowAlive(n.windowId)!==!0?!1:n.conversationId===t.conversationId&&n.windowId===t.windowId}"
    )
    if "e.conversationId===t.conversationId&&this.delegate?.isWindowAlive(t.windowId)===!0" not in text:
        if old in text:
            text = replace_once(text, old, new, "browser-use IAB canServe fallback")
        else:
            old_current = (
                "canServeTurnForBrowserRoute(e,t){let n=this.turnRoutes.get(XC(e));return n==null||"
                "this.delegate?.isWindowAlive(n.windowId)!==!0?!1:n.conversationId===t.conversationId&&n.windowId===t.windowId}"
            )
            new_current = (
                "canServeTurnForBrowserRoute(e,t){let n=this.turnRoutes.get(XC(e));return n==null?"
                "e.conversationId===t.conversationId&&this.delegate?.isWindowAlive(t.windowId)===!0:"
                "this.delegate?.isWindowAlive(n.windowId)!==!0?!1:n.conversationId===t.conversationId&&n.windowId===t.windowId}"
            )
            text = replace_once(text, old_current, new_current, "browser-use IAB canServe fallback")
        changed = True

    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_browser_use_alert_shim(root: Path) -> bool:
    path = root / ".vite/build/comment-preload.js"
    text = path.read_text(encoding="utf-8")
    if "__codexDesktopPatchAlertShim" in text:
        return False

    old = "var lf={interactionMode:`browse`,isAgentControllingBrowser:!1,comments:[],intlConfig:p,viewportScale:1,zoomPercent:100},uf=!1,df=null;"
    new = old + (
        "(()=>{try{if(window.__codexDesktopPatchAlertShim)return;"
        "Object.defineProperty(window,`__codexDesktopPatchAlertShim`,{value:!0});"
        "let e=window.alert;window.alert=function(t){if(lf?.isAgentControllingBrowser===!0)"
        "{try{console.warn(`[CodexDesktopPatch] suppressed alert during browser-use`,String(t??``))}catch{}return}"
        "return e.call(window,t)}}catch{}})();"
    )
    text = replace_once(text, old, new, "browser-use alert shim")
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


def repair_goal_state_db() -> bool:
    db_path = Path.home() / ".codex" / "state_5.sqlite"
    if not db_path.exists():
        print(f"{db_path}: Codex state database not found")
        return False

    changed = False
    with sqlite3.connect(db_path, timeout=10) as connection:
        has_table = connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'backfill_state'"
        ).fetchone()
        if has_table is None:
            print("Codex state database has no backfill_state table")
            return False

        rows = connection.execute("select id, status from backfill_state").fetchall()
        stale_ids = [row_id for row_id, status in rows if status == "idle"]
        if stale_ids:
            now = int(time.time())
            connection.executemany(
                "update backfill_state set status = ?, updated_at = ? where id = ?",
                [("complete", now, row_id) for row_id in stale_ids],
            )
            changed = True

    print(
        "repaired Codex goal runtime state database"
        if changed
        else "Codex goal runtime state database already current"
    )
    return changed


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--repair-state-db":
        repair_goal_state_db()
        return 0

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
            "usage: codex_desktop_patch.py <extracted-app-asar-dir>\n"
            "       codex_desktop_patch.py --repair-state-db\n"
            "       codex_desktop_patch.py --fix-integrity <electron-app-dir>\n"
            "       codex_desktop_patch.py --fix-integrity <codex-exe> <app-asar>",
            file=sys.stderr,
        )
        return 2
    root = Path(sys.argv[1]).resolve()
    changed = (
        patch_composer(root)
        | patch_index(root)
        | patch_cwd_retarget(root)
        | patch_browser_use_iab_route_fallback(root)
        | patch_browser_use_alert_shim(root)
    )
    print("patched Codex desktop goal/cwd/browser-use support" if changed else "Codex desktop patch already applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
