"""Static contract checks for native replay loading feedback in index.html."""
import subprocess
import sys
import tempfile
import os
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


class ScriptExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_script = False
        self.parts = []
        self.srcs = []
        self.current_external = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            attrs = dict(attrs)
            src = attrs.get("src") or ""
            self.current_external = bool(src)
            if src:
                self.srcs.append(src)
            self.in_script = True

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self.in_script = False
            self.current_external = False

    def handle_data(self, data):
        if self.in_script and not self.current_external:
            self.parts.append(data)


def _local_script_text(src):
    if src.startswith(("http://", "https://", "//")):
        return ""
    src_path = src.split("?", 1)[0].lstrip("/")
    path = ROOT / src_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main():
    html = INDEX.read_text(encoding="utf-8")
    assert 'href="/assets/app.css"' in html
    assert "cdn.jsdelivr.net" not in html
    assert 'href="/assets/vendor/atom-one-light.min.css"' in html
    assert 'id="lm-args"' not in html
    assert 'id="set-args"' not in html
    assert 'id="lm-codex-field"' in html
    assert 'id="slashmenu"' in html
    assert "#nativesend .nwrap{position:relative" in html
    assert "max-height:min(420px,calc(100dvh - 190px))" in html
    assert "contain:layout style paint" in html
    assert "content-visibility:auto" in html
    assert "#nativetasks.done" in html
    assert 'id="hist-archived"' in html
    assert '&#36827;&#34892;&#20013;' in html
    assert '&#24050;&#24402;&#26723;' in html
    assert 'id="lm-codex-reasoning"' in html
    assert 'id="lm-codex-summary"' in html
    assert 'id="lm-codex-service-tier"' in html
    assert 'id="lm-codex-writable-roots"' in html
    assert 'id="nativeslashhelp"' in html
    assert '&#22270;&#29255;' in html
    assert 'id="lm-codex-status"' in html
    parser = ScriptExtractor()
    parser.feed(html)
    js = "\n".join(parser.parts + [_local_script_text(src) for src in parser.srcs])
    codex_native = (ROOT / "codex_native.py").read_text(encoding="utf-8")
    assert "_REPLAY_MAX_EVENTS = 400" in codex_native
    assert "def _repair_full_replay_from_thread(self):" in codex_native
    assert "thread/read" in codex_native and "includeTurns" in codex_native
    assert "self._repair_full_replay_from_thread()" in codex_native
    assert "local_tail = list(self.timeline or [])" in codex_native
    assert "replay_signature(event)" in codex_native
    local_scripts = [src for src in parser.srcs if src.startswith("/assets/")]
    assert local_scripts == [
        "/assets/vendor/marked.min.js",
        "/assets/vendor/purify.min.js",
        "/assets/vendor/highlight.min.js",
        "/assets/app_core.js",
        "/assets/app_sidebar.js",
        "/assets/app_sidebar_codex_actions.js",
        "/assets/app_sidebar_rows.js",
        "/assets/app_state.js",
        "/assets/native_utils.js",
        "/assets/native_stage.js",
        "/assets/native_tool_helpers.js",
        "/assets/native_text_cards.js",
        "/assets/native_tool_results.js",
        "/assets/native_replay.js",
        "/assets/native_forms.js",
        "/assets/native_pending_cards.js",
        "/assets/native_tool_cards.js",
        "/assets/native_terminal_cards.js",
        "/assets/native_events.js",
        "/assets/native_socket.js",
        "/assets/native_actions.js",
        "/assets/app_launch.js",
        "/assets/app_usage_settings.js",
        "/assets/app_init.js",
        "/assets/auth.js",
        "/assets/icons.js",
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        js_path = f.name
    try:
        subprocess.run(["node", "--check", js_path], check=True)
    finally:
        try:
            os.unlink(js_path)
        except OSError:
            pass

    required = [
        "function nReplayRenderableEvents(events)",
        "function nStageHasReplayContent(st)",
        "function nHandleStreamEvent(sid, st, obj)",
        "function nRenderAssistantText(sid, st, text)",
        "function nRenderAssistantThinkingBlock(sid, st, obj, block)",
        "function nReplayUnseenEvents(st, events)",
        "if(st.renderedEvents[id]) return false",
        "Object.assign({}, st.renderedEvents||{})",
        "nReplayUnseenEvents(st, nReplayRenderableEvents(events))",
        "function nReplayProgressCancel(st)",
        "m._nativeStickBottom=at",
        "m._nativeStickBottom=true; m.scrollTop=m.scrollHeight",
        "var stick=(m._nativeStickBottom!==false) || nAtBottom()",
        "/api/history?limit=200&live_codex=1",
        "\"hist-archived\"",
        "function setHistoryView(archived)",
        "sbArchived?\"&archived=1\":\"\"",
        "var loadSeq=++sidebarLoadSeq",
        "function renderDirRow(d, q)",
        "function renderDirBody(d, mc)",
        "function renderConv(it)",
        "function closeSession(sid, btn)",
        "function resumeHist(h)",
        "function delHist(h, btn)",
        "{label:\"\\u53d6\\u6d88\\u5f52\\u6863\", title:\"\\u4ece\\u5f52\\u6863\\u4e2d\\u6062\\u590d\\u6b64 Codex \\u5386\\u53f2\\u4f1a\\u8bdd\", action:\"unarchive\"}",
        "function nativeScheduleReconnect(sid, delay)",
        "function nativeReconnectDelay(sid, baseDelay)",
        "if(existing && (existing.readyState===0 || existing.readyState===1) && !opts.force) return existing",
        "if(nativeReconnectTimers[sid]) return",
        "var hasContent=nStageHasReplayContent(st)",
        "if(!hasContent){",
        "if(nativeWs[sid]!==ws)",
        "\"[N] stale ws open ignored\"",
        "var isCurrent=(nativeWs[sid]===ws)",
        "if(!isCurrent){",
        "Number(obj.merged_seq)||0",
        "replayRunId:0",
        "replayFetchId:0",
        "st.replayRunId=(st.replayRunId||0)+1",
        "st.replayFetchId=(st.replayFetchId||0)+1",
        "var fetchId=st.replayFetchId||0",
        "(st.replayFetchId||0)!==fetchId",
        "st.replayActive=false; st.replayPending=[]",
        "st.catchupInFlight=false",
        "var runId=(st.replayRunId||0)+1; st.replayRunId=runId",
        "if(st.replayRunId!==runId) return",
        "if(typeof nResetReplayState===\"function\") nResetReplayState(st)",
        "function nativeStartPolling(sid, immediate)",
        "function nativeMaybeCatchupPoll(s, prevSession, reason)",
        "Number(s.last_output_ts||0) > Number(prevSession.last_output_ts||0)",
        'reason==="foreground"',
        'reason==="switch"',
        "function nativeCatchupPoll(sid, reason)",
        "st.catchupInFlight",
        "st.lastCatchupPoll",
        "if(!ws || ws.readyState!==1)",
        '"[N] catch-up"',
        '"[N] catch-up result"',
        "nReplayBatchAsync(sid, st, evs, {silent:true})",
        "nativeMaybeCatchupPoll(_visibleCatchup.session, _visibleCatchup.prevSession)",
        'nativeCatchupPoll(sid, "foreground")',
        'nativeCatchupPoll(sid, "switch")',
        "function nativeSlashCommand(command, st)",
        "var nativeSlashCommands=[",
        "function nRenderSlashMenu()",
        'postJSON("/api/nslash"',
        'if(p.charAt(0)==="/" && !images.length)',
        "function nAddImageFile(file)",
        'postJSON("/api/nsend", {sid:currentSid, prompt:p, images:images',
        '"/approval on-request"',
        '"/sandbox workspace-write"',
        '"/search live"',
        '"/reasoning medium"',
        '"/summary auto"',
        '"/service-tier auto"',
        '"/add-dir "',
        '"/rename "',
        '"/archive"',
        '"/unarchive"',
        '"/fork"',
        "function openForkedCodexThread(threadId, title, cwd)",
        'if(t==="thread_forked")',
        "openForkedCodexThread(fid, ftitle, obj.cwd||\"\")",
        '"/rollback 1"',
        '"/goal get"',
        '"/mcp-status full"',
        '"/mcp-resources "',
        '"/mcp-resource "',
        '"/mcp-tool "',
        '"/skills"',
        '"/plugins"',
        '"/account-status"',
        '"/exec "',
        '"/exec-stream "',
        '"/steer "',
        "function nSlashMove(delta)",
        "function nSlashPickActive()",
        "function nRenderFileMentionMenu(info)",
        "function nInsertMention(path)",
        '"/api/nfiles?sid="+encodeURIComponent(currentSid)',
        "function nRenderInputAssist()",
        "function nLooksLikeAssistInput(value)",
        "function nScheduleInputAssist(inp)",
        "nativeInputAssistTimer=setTimeout",
        "nativeHeightTimer=setTimeout",
        'if(value.indexOf("\\n")>=0 || value.length>160)',
        'addEventListener("input", function(){ nScheduleInputAssist(this); })',
        "function nTerminalCardHtml(pid, obj)",
        "function nTerminalStatus(card, msg, isError)",
        "function nPostTerminal(processId, action, input, closeStdin, cols, rows, card)",
        "function nHandleTerminalInteraction(st, obj)",
        "function nHandleTerminalInputSent(st, obj)",
        "function nHandleTerminalClosed(st, obj)",
        'postJSON("/api/nterminal"',
        'class="tresize"',
        'class="terminal-status"',
        "Command needs terminal input",
        'if(t==="terminal_interaction")',
        'if(t==="terminal_closed")',
        "function nDiffResultHtml(txt)",
        "function nDiffFileSections(txt)",
        "function nDiffFileListHtml(files)",
        "function nDiffPatchSummaryHtml(st, sections)",
        "function nCommandResultParts(txt, meta)",
        "function nCommandSectionHtml(label, txt, cls)",
        "function nCommandResultHtml(txt, toolName, meta)",
        "function nJsonResultHtml(txt, toolName)",
        "function nMcpStatusResultHtml(obj, toolName)",
        "function nCodexInventoryResultHtml(obj, toolName)",
        "function nCodexSkillsResultHtml(obj)",
        "function nCodexPluginsResultHtml(obj)",
        "function nCodexAccountResultHtml(obj, toolName)",
        "function nCodexAccountStatusLine(account)",
        "function nSpecialToolBody(name, input)",
        "function nStructuredToolBody(name, input)",
        "function nToolResultMarkup(toolId, txt, toolName, meta)",
        "function nRenderToolResult(st, tuid, txt, meta)",
        "function nHandlePendingApproval(sid, st, obj)",
        "function nHandlePendingAsk(sid, st, obj)",
        "function nHandlePendingForm(sid, st, obj)",
        "function nHandlePendingResolved(sid, st, obj, type)",
        "function nReconcilePendingSnapshot(st, obj)",
        "nReconcilePendingSnapshot(st, obj)",
        ".nmsg.approval[data-tuid],.nmsg.plan[data-tuid],.nmsg.ask[data-tuid],.nmsg.form[data-tuid]",
        "function nRenderToolUseBlock(sid, st, b)",
        "_tu.dataset.tname=b.name||\"\"",
        "var _special=nSpecialToolBody(_n, _inp)",
        "var _structured=_special?\"\":nStructuredToolBody(b.name, _inp)",
        "class=\"tcmeta\"",
        "class=\"special-card mcp-card\"",
        "class=\"tool-arg-preview\"",
        "sleep:_I('hourglass')",
        "contextcompaction:_I('archive')",
        "imagegeneration:_I('sparkles')",
        "imageview:_I('file-text')",
        'toolId==="turn-diff"',
        'class="diff-unified"',
        'class="diff-patch-summary"',
        'class="diff-file-list"',
        'class="diff-file-chip"',
        'class="diff-file-chip-stat"',
        'class="diff-file-sections"',
        'class="diff-file-section"',
        'diff-large',
        'class="json-result"',
        'class="mcp-action"',
        "data-mcp-command",
        'class="mcp-resource-card"',
        'class="mcp-server-card"',
        'class="mcp-status-card codex-inventory-card"',
        'class="mcp-status-card codex-account-card"',
        'e.target.closest ? e.target.closest(".mcp-action")',
        "nRenderToolResult(st, b.tool_use_id, txt, b)",
        'e.key==="ArrowDown"',
        'if(_nGenerating && p.indexOf("/steer ")!==0',
        'if(t==="replay_replace")',
        "nResetReplayState(st)",
        "\"/api/nreplay?sid=\"+encodeURIComponent(sid)+\"&after=\"+encodeURIComponent(after)",
        "\"?after=\"+encodeURIComponent(String(afterSeq))",
        "\"retry=\"+nativeReconnectDelay(sid,1500)+\"ms\"",
        "\"lastSeq=\"",
        "\"after=\"",
        "\"hasContent=\"",
        "Connecting session",
        "Waiting for conversation replay",
        "No replay history",
        "if(!opts.silent) nReplayProgressStart",
        "_sig===st.lastReplayBatchSig && _hasContent",
        "if(_hasContent){",
        "var _unseen=nReplayUnseenEvents(st,_evs)",
        "st.replaySigParts=_parts",
        "nReplayBatchAsync(sid, st, _unseen, {silent:true})",
        "function nSettleIdleSnapshot(st, obj)",
        "function nTasksAllCompleted(st)",
        "function nSettleActiveTasks(st)",
        "function nMaybeCompleteTasks(st)",
        "if(!obj.running){ nSettleActiveTasks(st); nMaybeCompleteTasks(st); }",
        "st.curTxt || st.turnCard",
        "nSettleIdleSnapshot(st, obj)",
        "window.NATIVE_DEBUG",
        "if(st.replayWaiting && !st.replayActive)",
        "function codexLaunchConfig(backend)",
        "/api/codex_options?dir=",
        "approvalPolicy:lmCodexApproval",
        "reasoningEffort:lmCodexReasoning",
        "reasoningSummary:lmCodexSummary",
        "serviceTier:lmCodexServiceTier",
        "writableRoots:lmCodexWritableRoots",
        "webSearch:lmCodexSearch",
        "function codexAccountStatusText(account)",
        "function codexMaskEmail(email)",
        "function codexStatusText(r)",
        "function codexDiagnosticRows(r)",
        "function renderCodexDiagnostics(r)",
        "function renderCodexStatus(r)",
        "Codex \u53ea\u8bfb\u72b6\u6001",
        "Codex \u8bca\u65ad",
        "lm-codex-diagnostics",
        'class="codex-diag"',
        "permission_profiles",
        "function runCodexAction(sid, command, btn, cwd)",
        "function appendCodexRunActions(el, s)",
        'postJSON("/api/nslash", {sid:sid, command:command})',
        "function appendCodexActionMenu(el, actions)",
        'more.className="cbtn ghost more-actions"',
        'actions.classList.add("cactions-pop")',
        "document.body.appendChild(actions)",
        '{label:"\\u5206\\u53c9", title:"\\u5206\\u53c9\\u6b64 Codex \\u4f1a\\u8bdd", command:"/fork"}',
        '{label:"\\u56de\\u6eda", title:"\\u56de\\u6eda\\u4e00\\u8f6e Codex \\u5bf9\\u8bdd", command:"/rollback 1"}',
        '{label:"\\u91cd\\u547d\\u540d", title:"\\u91cd\\u547d\\u540d\\u6b64 Codex \\u4f1a\\u8bdd"',
        '{label:"\\u76ee\\u6807", title:"\\u8bbe\\u7f6e\\u6b64 Codex \\u4f1a\\u8bdd\\u76ee\\u6807"',
        "function runCodexHistoryAction(h, action, btn, extra)",
        "function appendCodexHistoryActions(el, h)",
        'postJSON("/api/codex_history_action"',
        '{label:"\\u5206\\u53c9", title:"\\u5206\\u53c9\\u6b64 Codex \\u5386\\u53f2\\u4f1a\\u8bdd", action:"fork"}',
        '{label:"\\u5f52\\u6863", title:"\\u5f52\\u6863\\u6b64 Codex \\u5386\\u53f2\\u4f1a\\u8bdd", action:"archive"}',
        '{label:"\\u53d6\\u6d88\\u5f52\\u6863", title:"\\u4ece\\u5f52\\u6863\\u4e2d\\u6062\\u590d\\u6b64 Codex \\u5386\\u53f2\\u4f1a\\u8bdd", action:"unarchive"}',
        '{label:"\\u91cd\\u547d\\u540d", title:"\\u91cd\\u547d\\u540d\\u6b64 Codex \\u5386\\u53f2\\u4f1a\\u8bdd", action:"rename"',
        '{label:"\\u76ee\\u6807", title:"\\u8bbe\\u7f6e\\u6b64 Codex \\u5386\\u53f2\\u4f1a\\u8bdd\\u76ee\\u6807", action:"goal_set"',
    ]
    missing = [token for token in required if token not in js]
    assert not missing, "missing replay loading contracts: %r" % missing
    print("ok")


if __name__ == "__main__":
    main()
