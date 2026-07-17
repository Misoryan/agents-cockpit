"""Check browser replay de-duplication behavior with Node."""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    js = r'''
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
let ctx = {
  console,
  setTimeout,
  clearTimeout,
  setInterval: () => 1,
  clearInterval: () => {},
  requestAnimationFrame: (fn) => fn(),
  window: {},
  document: {addEventListener: () => {}, visibilityState: "visible"},
  location: {protocol: "http:", host: "localhost"},
  _I: () => ""
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("assets/native_utils.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_stage.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_tool_helpers.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_text_cards.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_tool_results.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_terminal_cards.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_replay.js", "utf8"), ctx);
ctx.nativeViewMode = "chat";
ctx.nativeWorkStages = {};
ctx.nativeWorkBusy = {};
vm.runInContext(fs.readFileSync("assets/native_work.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_pending_cards.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_socket.js", "utf8"), ctx);
const {
  nMarkRendered,
  nReplayUnseenEvents,
  nReplayEventKey,
  nReplayBatchAsync,
  nResetReplayState,
  nAtBottom,
  nUpdateScrollButton,
  nJumpBottom,
  nScrollBottom,
  nSettleIdleSnapshot,
  nativeConnect,
  nativeCatchupPoll,
  nReconcilePendingSnapshot,
  nDiffResultHtml,
  nDiffFileSections,
  nDiffFileListHtml,
  nDiffPatchSummaryHtml,
  nDiffStats,
  nToolResultMarkup,
  nJsonResultHtml,
  nMcpStatusResultHtml,
  nCodexInventoryResultHtml,
  nCodexAccountResultHtml,
  nTerminalCardHtml,
  nSpecialToolBody,
  nStructuredToolBody,
  nativeViewIsWork,
  nWorkStatusText,
  nWorkSafeStatus,
  nWorkElapsedMs,
  nativeWorkSyncElapsed,
  nativeWorkRenderSignature,
  nativeWorkRememberOpenDetails,
  nativeWorkRestoreOpenDetails,
  nativeWorkTurnRows,
  nWorkHistoryHtml,
  nWorkProgressHtml,
  nWorkTurnHtml,
  nWorkErrorHtml,
  nWorkToolTotal,
  nWorkFileTotal,
  nWorkCountsText
} = ctx;

let st = {renderedEvents: {}, lastSeq: 0};
assert.strictEqual(nMarkRendered(st, {type:"assistant", seq:1}), true);
assert.strictEqual(nMarkRendered(st, {type:"assistant", seq:1, replay:true}), false);
assert.strictEqual(st.lastSeq, 1);

assert.strictEqual(nMarkRendered(st, {type:"assistant", event_id:"evt-1"}), true);
assert.strictEqual(nMarkRendered(st, {type:"assistant", event_id:"evt-1", replay:true}), false);
assert.strictEqual(nativeViewIsWork(), false);
ctx.nativeViewMode = "work";
assert.strictEqual(nativeViewIsWork(), true);
ctx.nativeViewMode = "chat";
assert.strictEqual(nWorkStatusText("confirm", false), "等待确认");
assert.strictEqual(nWorkSafeStatus('bad" onclick="x'), "pending");
assert.strictEqual(nWorkElapsedMs({turn_elapsed_ms:2500}), 2500);
assert.strictEqual(nWorkElapsedMs({running:true, turn_started_at_ms:1000, server_now_ms:3500}), 2500);
assert.strictEqual(nWorkToolTotal({tool_total:3, tools:[{}]}), 3);
assert.strictEqual(nWorkFileTotal({file_total:2, files:["a"]}), 2);
assert.strictEqual(nWorkCountsText(null, [{name:"PowerShell", count:2}, {name:"Edit", count:1}]), "PowerShell x2 / Edit x1");
let runningWorkHtml = nWorkTurnHtml({
  status:"running",
  user_text:"fix mobile",
  tool_total:2,
  file_total:1,
  tool_counts:{Edit:1, PowerShell:1},
  latest_tool:{name:"PowerShell", label:"npm test -- --watch=false", status:"running"},
  tools:[
    {id:"edit-1", name:"Edit", label:"old detail", input:{file_path:"assets/very/long/path.js", old_str:"old line", new_str:"new line"}, preview:"diff --git a/assets/very/long/path.js b/assets/very/long/path.js\n--- a/assets/very/long/path.js\n+++ b/assets/very/long/path.js\n@@\n-old line\n+new line", files:["assets/very/long/path.js"], changed_files:[{path:"assets/very/long/path.js", added:3, deleted:1}], diff:{added:3, deleted:1}},
    {id:"cmd-1", name:"PowerShell", label:"npm test -- --watch=false", input:{command:"npm test -- --watch=false", cwd:"E:/repo"}, status:"running", preview:"running tests\nexit code: 0\nduration ms: 25"}
  ],
  files:["assets/very/long/path.js"],
  todos:[{content:"Card task that should stay pinned", status:"in_progress"}],
  elapsed_ms:2000,
  assistant_text:"I checked the current test run and am fixing the Work card now.",
  assistant_text_chars:61,
  assistant_text_hidden:true
}, 0, 1);
assert.ok(runningWorkHtml.includes("work-current-action"));
assert.ok(runningWorkHtml.includes("PowerShell"));
assert.ok(runningWorkHtml.includes("2 动作"));
assert.ok(runningWorkHtml.includes("work-turn-elapsed"));
assert.ok(runningWorkHtml.includes("2秒"));
assert.strictEqual((runningWorkHtml.match(/fix mobile/g) || []).length, 1, "running Work View should not duplicate the user prompt");
assert.ok(runningWorkHtml.includes("work-progress"));
assert.ok(runningWorkHtml.includes("AI 中途回复"));
assert.ok(runningWorkHtml.includes("I checked the current test run"));
assert.ok(!runningWorkHtml.includes("work-current-action-detail"));
assert.ok(!runningWorkHtml.includes("动作详情"));
assert.ok(!runningWorkHtml.includes("work-action-cards"));
assert.ok(!runningWorkHtml.includes('class="nmsg tool work-tool-card'));
assert.ok(!runningWorkHtml.includes("old detail"), "running Work View should hide older action details");
assert.ok(!runningWorkHtml.includes("assets/very/long/path.js"), "running Work View should hide concrete action details");
assert.ok(!runningWorkHtml.includes('class="tcmd">$ npm test -- --watch=false'));
assert.ok(!runningWorkHtml.includes("E:/repo"));
assert.ok(!runningWorkHtml.includes("cmd-det"));
assert.ok(!runningWorkHtml.includes("running tests"));
assert.ok(!runningWorkHtml.includes('class="diff-file"'));
assert.ok(!runningWorkHtml.includes("old line"));
assert.ok(!runningWorkHtml.includes("new line"));
assert.ok(!runningWorkHtml.includes("diff-det"));
assert.ok(!runningWorkHtml.includes("Card task that should stay pinned"), "latest Work card should not duplicate pinned tasks");
assert.ok(nWorkProgressHtml({}) === "");
let historicalTaskHtml = nWorkTurnHtml({
  status:"done",
  user_text:"older work",
  tool_total:0,
  todos:[{content:"Historical task visible", status:"pending"}]
}, 0, 2);
assert.ok(historicalTaskHtml.includes("Historical task visible"), "historical cards should still show their task list");
let doneWorkHtml = nWorkTurnHtml({
  status:"done",
  user_text:"fix mobile",
  tool_total:3,
  file_total:2,
  tool_counts:{PowerShell:2, Edit:1},
  latest_tool:{name:"Edit", label:"assets/secret.js"},
  tools:[{name:"Edit", label:"assets/secret.js"}],
  files:["assets/secret.js"],
  assistant_text:"detailed final text",
  assistant_text_hidden:true,
  assistant_text_chars:19,
  changed_files:[{path:"assets/visible.js", added:4, deleted:2, total:6}],
  diff_added:4,
  diff_deleted:2,
  diff_total:6
}, 0, 1);
assert.ok(doneWorkHtml.includes("work-complete"));
assert.ok(doneWorkHtml.includes("work-final-details"));
assert.ok(doneWorkHtml.includes('data-work-detail="final-turn-0" open'));
assert.ok(doneWorkHtml.includes("work-file-details"));
assert.ok(doneWorkHtml.includes("改动文件一览"));
assert.ok(doneWorkHtml.includes("assets/visible.js"));
assert.ok(doneWorkHtml.includes("+4"));
assert.ok(doneWorkHtml.includes("-2"));
assert.ok(doneWorkHtml.includes('data-work-action="chat-turn"'));
assert.ok(doneWorkHtml.includes("查看本卡 Chat View"));
assert.ok(doneWorkHtml.includes("3 个动作"));
assert.ok(doneWorkHtml.includes("detailed final text"), "completed Work View should keep final assistant text inside a folded details block");
assert.ok(!doneWorkHtml.includes("assets/secret.js"), "completed Work View should hide concrete tool/file details");
assert.ok(!doneWorkHtml.includes("work-tools"));
let failedWorkHtml = nWorkTurnHtml({
  status:"error",
  user_text:"run deploy",
  tool_total:1,
  file_total:0,
  error:"boom <bad>"
}, 0, 1);
assert.ok(failedWorkHtml.includes("本轮失败"));
assert.ok(failedWorkHtml.includes("work-error"));
assert.ok(failedWorkHtml.includes("boom &lt;bad&gt;"));
assert.ok(nWorkErrorHtml({status:"error"}).includes("未提供详细错误"));
assert.strictEqual(
  nativeWorkRenderSignature({status:"running", server_now_ms:1000, turn_elapsed_ms:500, turns:[{status:"running", elapsed_ms:500}]}, []),
  nativeWorkRenderSignature({status:"running", server_now_ms:9000, turn_elapsed_ms:8500, turns:[{status:"running", elapsed_ms:8500}]}, []),
  "work signature should ignore elapsed-only poll changes"
);
assert.notStrictEqual(
  nativeWorkRenderSignature({status:"running", turns:[{status:"running"}]}, []),
  nativeWorkRenderSignature({status:"idle", turns:[{status:"done"}]}, []),
  "work signature should still change for content/state changes"
);
assert.deepStrictEqual(
  nativeWorkTurnRows([{key:"turn-1"}, {key:"turn-2"}, {key:"turn-3"}]).map((row) => row.turn.key + ":" + row.idx),
  ["turn-3:2", "turn-2:1", "turn-1:0"],
  "Work View should render newest cards first while preserving original turn numbers"
);
let historyRows = nativeWorkTurnRows([{key:"turn-1", status:"done"}, {key:"turn-2", status:"done"}, {key:"turn-3", status:"done"}]).slice(1);
let historyHtml = nWorkHistoryHtml(historyRows, 3);
assert.ok(historyHtml.includes("work-history"));
assert.ok(historyHtml.includes("历史轮次 · 2 轮"));
assert.ok(!historyHtml.includes('data-work-detail="final-turn-3" open'), "historical cards should not default-open latest summary");
let remembered = nativeWorkRememberOpenDetails({root:{querySelectorAll: () => [
  {open:true, getAttribute: () => "final-turn-1"},
  {open:false, getAttribute: () => "final-turn-2"}
]}});
assert.strictEqual(remembered["final-turn-1"], true);
assert.strictEqual(remembered["final-turn-2"], undefined);
let restoredDetail = {open:false, getAttribute: () => "final-turn-1"};
nativeWorkRestoreOpenDetails({root:{querySelectorAll: () => [restoredDetail]}}, remembered);
assert.strictEqual(restoredDetail.open, true);
let elapsedNode = {textContent: ""};
let elapsedStage = {root: {querySelectorAll: () => [elapsedNode]}, elapsedTimer: null};
nativeWorkSyncElapsed(elapsedStage, {running:true, turn_elapsed_ms:1000});
assert.strictEqual(elapsedStage.elapsedTimer, 1);
assert.ok(elapsedNode.textContent, "work elapsed label should render immediately from server elapsed time");

let scrollShown = false;
let nodes = {
  nativemsgs: {scrollHeight: 1000, scrollTop: 780, clientHeight: 200, _nativeStickBottom: undefined},
  scrollbottom: {classList: {toggle: (_cls, show) => { scrollShown = !!show; }}}
};
ctx.currentSid = "scroll-sid";
ctx.$ = function(id){ return nodes[id]; };
assert.strictEqual(nAtBottom(), true);
nUpdateScrollButton();
assert.strictEqual(nodes.nativemsgs._nativeStickBottom, true);
nodes.nativemsgs.scrollHeight = 1400;
nScrollBottom();
assert.strictEqual(nodes.nativemsgs.scrollTop, 1400, "bottom-stuck users should follow large appended content");
nodes.nativemsgs.scrollHeight = 1600;
nodes.nativemsgs.scrollTop = 900;
nUpdateScrollButton();
assert.strictEqual(nodes.nativemsgs._nativeStickBottom, false);
assert.strictEqual(scrollShown, true);
nScrollBottom();
assert.strictEqual(nodes.nativemsgs.scrollTop, 900, "scrolled-up users should not be forced to bottom");
nJumpBottom();
assert.strictEqual(nodes.nativemsgs._nativeStickBottom, true);
assert.strictEqual(scrollShown, false);

function fakePendingCard(cls, tuid){
  return {
    className: "nmsg " + cls,
    dataset: {tuid},
    removed: false,
    parentNode: {removeChild: function(card){ card.removed = true; }}
  };
}
let pendingCards = [
  fakePendingCard("approval", "approve-1"),
  fakePendingCard("ask", "ask-1"),
  fakePendingCard("form", "form-1")
];
let pendingRoot = {querySelectorAll: () => pendingCards};
nReconcilePendingSnapshot({root: pendingRoot}, {type:"state_snapshot", pending:[{id:"ask-1", kind:"ask"}]});
assert.strictEqual(pendingCards[0].removed, true);
assert.strictEqual(pendingCards[1].removed, false);
assert.strictEqual(pendingCards[2].removed, true);
nReconcilePendingSnapshot({root: pendingRoot}, {type:"state_snapshot", pending:[]});
assert.strictEqual(pendingCards[1].removed, true, "empty snapshot pending list should clear stale pending cards");

let turnDoneClass = "";
let idleStage = {
  turnCard: {classList: {add: (cls) => { turnDoneClass = cls; }}},
  curTxt: {},
  curThink: null,
  thinking: false
};
assert.strictEqual(nSettleIdleSnapshot(idleStage, {type:"state_snapshot", state:"idle", running:false}), true);
assert.strictEqual(turnDoneClass, "done");
assert.strictEqual(idleStage.turnCard, null);
assert.strictEqual(idleStage.curTxt, null);
let confirmStage = {
  turnCard: {classList: {add: () => { throw new Error("confirm snapshot should not close pending turn"); }}},
  curTxt: {},
  thinking: false
};
assert.strictEqual(nSettleIdleSnapshot(confirmStage, {type:"state_snapshot", state:"confirm", running:false}), false);
assert.notStrictEqual(confirmStage.turnCard, null);

let unseen = nReplayUnseenEvents(st, [
  {type:"assistant", seq:1},
  {type:"assistant", seq:2},
  {type:"assistant", seq:2},
  {type:"assistant", event_id:"evt-1"},
  {type:"assistant", event_id:"evt-2"},
  {type:"assistant", event_id:"evt-2"},
  {type:"codex_notice"}
]);
assert.deepStrictEqual(unseen.map(nReplayEventKey), ["seq:2", "id:evt-2", ""]);

let handled = [];
let st2 = {renderedEvents: {"seq:1": true}, lastSeq: 1};
ctx.nHandle = function(_sid, event){
  handled.push(nReplayEventKey(event));
  nMarkRendered(st2, event);
};
nReplayBatchAsync("s1", st2, [
  {type:"assistant", seq:1},
  {type:"assistant", seq:2},
  {type:"assistant", seq:2},
  {type:"assistant", seq:3}
], {silent:true});
assert.deepStrictEqual(handled, ["seq:2", "seq:3"]);
assert.strictEqual(st2.lastSeq, 3);

const sampleDiff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-old\n+new";
assert.deepStrictEqual(JSON.parse(JSON.stringify(nDiffStats(sampleDiff))), {lines:6, files:1, add:1, del:1, fileList:["a.py"]});
const sampleSections = nDiffFileSections(sampleDiff);
assert.strictEqual(sampleSections.length, 1);
assert.deepStrictEqual(JSON.parse(JSON.stringify({path:sampleSections[0].path, add:sampleSections[0].add, del:sampleSections[0].del})), {path:"a.py", add:1, del:1});
const diffHtml = nDiffResultHtml(sampleDiff);
assert.ok(diffHtml.includes("Diff"));
assert.ok(diffHtml.includes("diff-unified"));
assert.ok(diffHtml.includes("diff-patch-summary"));
assert.ok(diffHtml.includes("diff-file-list"));
assert.ok(diffHtml.includes("diff-file-chip"));
assert.ok(diffHtml.includes("diff-file-chip-stat"));
assert.ok(diffHtml.includes("du-add"));
assert.ok(diffHtml.includes("du-del"));
assert.ok(nToolResultMarkup("turn-diff", sampleDiff).includes("diff-unified"));
const multiDiff = Array.from({length:10}, (_, i) => {
  const name = "src/file" + i + ".js";
  return "diff --git a/" + name + " b/" + name + "\n--- a/" + name + "\n+++ b/" + name + "\n@@\n-old" + i + "\n+new" + i;
}).join("\n");
const multiStats = nDiffStats(multiDiff);
const multiSections = nDiffFileSections(multiDiff);
assert.strictEqual(multiStats.files, 10);
assert.strictEqual(multiSections.length, 10);
assert.deepStrictEqual(JSON.parse(JSON.stringify(multiStats.fileList.slice(0,3))), ["src/file0.js", "src/file1.js", "src/file2.js"]);
const multiHtml = nDiffResultHtml(multiDiff);
assert.ok(multiHtml.includes("diff-large"));
assert.ok(!multiHtml.includes("diff-det\" open"));
assert.ok(multiHtml.includes("diff-file-sections"));
assert.ok(multiHtml.includes("diff-file-section"));
assert.ok(multiHtml.includes("largest: src/file0.js +1 -1"));
assert.ok(multiHtml.includes("+2 more"));
assert.ok(nDiffFileListHtml(multiSections).includes("src/file7.js"));
assert.ok(nDiffPatchSummaryHtml(multiStats, multiSections).includes("10 files"));
const termHtml = nTerminalCardHtml("proc-1", {stdin: "password:"});
assert.ok(termHtml.includes("Command needs terminal input"));
assert.ok(termHtml.includes("Type text to send to stdin"));
assert.ok(termHtml.includes("class=\"tresize\""));
assert.ok(termHtml.includes("terminal-status"));
assert.ok(termHtml.includes("proc-1"));
assert.ok(termHtml.includes("password:"));
assert.ok(nToolResultMarkup("tool-1", "plain text").includes("Result (1 lines)"));
assert.ok(nToolResultMarkup("cmd-1", "out\nexit code: 2", "Bash").includes("Command"));
assert.ok(nToolResultMarkup("cmd-1", "out\nexit code: 2", "Bash").includes("exit 2"));
assert.ok(nToolResultMarkup("cmd-1", "ok\nexit code: 0\nduration ms: 2500", "Bash").includes("3秒"));
const splitCmd = nToolResultMarkup("cmd-2", "", "PowerShell", {stdout:"ok", stderr:"warn", exit_code:1, duration_ms:1500});
assert.ok(splitCmd.includes("stdout"));
assert.ok(splitCmd.includes("stderr"));
assert.ok(splitCmd.includes("cmd-stderr"));
assert.ok(splitCmd.includes("exit 1"));
const jsonHtml = nJsonResultHtml('{"content":[{"type":"text","text":"hello from mcp"}],"isError":false}', "demo.tool");
assert.ok(jsonHtml.includes("JSON · demo.tool"));
assert.ok(jsonHtml.includes("json-preview"));
assert.ok(jsonHtml.includes("json-result"));
assert.ok(nToolResultMarkup("mcp-tool-demo", '{"error":"bad"}', "demo.tool").includes("JSON · demo.tool · error"));
const mcpStatusHtml = nMcpStatusResultHtml({
  servers: [{
    name: "docs",
    authStatus: "unsupported",
    tools: 1,
    resources: 1,
    resourceTemplates: 1,
    resourceList: [{name:"Guide", uri:"file://guide.md", mimeType:"text/markdown"}],
    toolList: [{name:"search", description:"Search docs"}],
    resourceTemplateList: [{name:"Issue", uriTemplate:"issue://{id}"}]
  }]
}, "mcpServerStatus.list");
assert.ok(mcpStatusHtml.includes("MCP Status"));
assert.ok(mcpStatusHtml.includes("mcp-server-card"));
assert.ok(mcpStatusHtml.includes("data-mcp-command"));
assert.ok(mcpStatusHtml.includes("/mcp-resource"));
assert.ok(mcpStatusHtml.includes("file://guide.md"));
const mcpResourceHtml = nToolResultMarkup("mcp-resources-docs", JSON.stringify({
  server: "docs",
  authStatus: "unsupported",
  resources: [{name:"Guide", uri:"file://guide.md"}],
  resourceTemplates: [{name:"Issue", uriTemplate:"issue://{id}"}],
  tools: [{name:"search", description:"Search docs"}]
}), "mcpServerStatus.resources");
assert.ok(mcpResourceHtml.includes("MCP Resources"));
assert.ok(mcpResourceHtml.includes("mcp-resource-card"));
assert.ok(mcpResourceHtml.includes("/mcp-resource"));
const skillsHtml = nCodexInventoryResultHtml({
  total: 1,
  enabled: 1,
  disabled: 0,
  roots: [{cwd:"E:/repo", skills:[{name:"openai-docs", displayName:"OpenAI Docs", scope:"system", enabled:true, shortDescription:"Docs helper"}]}]
}, "codex.skills");
assert.ok(skillsHtml.includes("Codex Skills"));
assert.ok(skillsHtml.includes("codex-inventory-card"));
assert.ok(skillsHtml.includes("OpenAI Docs"));
assert.ok(nToolResultMarkup("codex-skills", JSON.stringify({
  total: 1,
  enabled: 1,
  roots: [{cwd:"E:/repo", skills:[{name:"openai-docs", enabled:true}]}]
}), "codex.skills").includes("Codex Skills"));
const pluginsHtml = nCodexInventoryResultHtml({
  mode: "installed",
  total: 1,
  marketplaces: [{name:"Local", plugins:[{id:"browser", name:"Browser", installed:true}]}]
}, "codex.plugins");
assert.ok(pluginsHtml.includes("Codex Plugins"));
assert.ok(pluginsHtml.includes("Browser"));
const accountHtml = nCodexAccountResultHtml({
  account: {signed_in:true, type:"chatgpt", plan_type:"pro", email:"p***n@example.com"},
  rateLimits: {primary:{used:1, limit:10}},
  usage: {inputTokens:100},
  errors: [{method:"account/usage/read", error:"auth required"}]
}, "codex.accountStatus");
assert.ok(accountHtml.includes("Codex Account"));
assert.ok(accountHtml.includes("codex-account-card"));
assert.ok(accountHtml.includes("Rate limits"));
assert.ok(accountHtml.includes("Warnings"));
assert.ok(nToolResultMarkup("codex-account", JSON.stringify({
  account: {requires_openai_auth:true},
  errors: []
}), "codex.accountStatus").includes("login required"));
assert.ok(nSpecialToolBody("sleep", {durationMs: 1200, reason: "wait"}).includes("sleep-card"));
assert.ok(nSpecialToolBody("contextcompaction", {status: "started", summary: "compact"}).includes("compact-card"));
assert.ok(nSpecialToolBody("imagegeneration", {prompt: "a cat", size: "1024x1024"}).includes("image-card"));
assert.ok(nSpecialToolBody("imageview", {path: "https://example.test/a.png"}).includes("special-path"));
const mcpBody = nStructuredToolBody("demo.lookup", {query: "abc", limit: 3});
assert.ok(mcpBody.includes("mcp-card"));
assert.ok(mcpBody.includes("tool-arg-preview"));
assert.ok(mcpBody.includes("demo"));
assert.ok(mcpBody.includes("lookup"));
assert.strictEqual(nStructuredToolBody("Bash", {command: "echo ok"}), "");

(async function(){
  let cancelHandled = [];
  let stCancel = {sid:"cancel", root:{innerHTML:"", children:[]}, renderedEvents:{}, lastSeq:0};
  ctx.currentSid = "";
  ctx.nRenderTasks = function(){};
  ctx.nHandle = function(_sid, event){
    cancelHandled.push(event.seq);
    nMarkRendered(stCancel, event);
  };
  nReplayBatchAsync("cancel", stCancel, Array.from({length:40}, (_, i) => ({type:"assistant", seq:i+1})), {silent:true});
  assert.strictEqual(cancelHandled.length, 18);
  assert.strictEqual(stCancel.replayActive, true);
  nResetReplayState(stCancel);
  assert.strictEqual(stCancel.replayActive, false);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.strictEqual(cancelHandled.length, 18, "cancelled replay pump should not continue rendering");

  let catchupEvents = [];
  let catchupUrls = [];
  let st3 = {
    sid: "s3",
    root: {children: [{classList: {contains: () => false}}]},
    renderedEvents: {"seq:4": true},
    lastSeq: 4,
    replayActive: false,
    replayWaiting: false,
    lastCatchupPoll: 0,
    catchupInFlight: false
  };
  ctx.currentSid = "s3";
  ctx.nativeStages = {s3: st3};
  ctx.nativeWs = {s3: {readyState: 1}};
  ctx.nativePollTimers = {};
  ctx.nativePollBusy = {};
  ctx.nFindRunSession = function(sid){ return {sid, state: "running"}; };
  ctx.api = function(url){
    catchupUrls.push(url);
    return Promise.resolve({
      ok: true,
      events: [{type:"assistant", seq:5}],
      snapshot: {type:"state_snapshot", last_seq:5},
      pending: []
    });
  };
  ctx.nHandle = function(sid, event){
    catchupEvents.push(event.type + ":" + (event.seq || event.last_seq || ""));
    ctx.nMarkRendered(st3, event);
  };
  ctx.nativeMaybeCatchupPoll({sid:"s3", state:"running"}, "running", "test");
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.strictEqual(catchupUrls.length, 1);
  assert.ok(catchupUrls[0].includes("/api/nreplay?sid=s3&after=4"));
  assert.deepStrictEqual(catchupEvents, ["assistant:5", "state_snapshot:5"]);
  assert.strictEqual(st3.lastSeq, 5);
  ctx.nativeMaybeCatchupPoll({sid:"s3", state:"running"}, "running", "test");
  assert.strictEqual(catchupUrls.length, 1, "catch-up poll should be throttled");

  let idleEvents = [];
  let idleUrls = [];
  let st4 = {
    sid: "s4",
    root: {children: [{classList: {contains: () => false}}]},
    renderedEvents: {"seq:7": true},
    lastSeq: 7,
    replayActive: false,
    replayWaiting: false,
    lastCatchupPoll: 0,
    catchupInFlight: false
  };
  ctx.currentSid = "s4";
  ctx.nativeStages = {s4: st4};
  ctx.nativeWs = {s4: {readyState: 1}};
  ctx.api = function(url){
    idleUrls.push(url);
    return Promise.resolve({
      ok: true,
      events: [{type:"codex_notice", seq:8}],
      snapshot: {type:"state_snapshot", last_seq:8},
      pending: []
    });
  };
  ctx.nHandle = function(sid, event){
    idleEvents.push(event.type + ":" + (event.seq || event.last_seq || ""));
    ctx.nMarkRendered(st4, event);
  };
  ctx.nativeMaybeCatchupPoll(
    {sid:"s4", state:"idle", last_output_ts:20},
    {state:"idle", last_output_ts:10}
  );
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.strictEqual(idleUrls.length, 1, "idle activity should trigger catch-up");
  assert.ok(idleUrls[0].includes("/api/nreplay?sid=s4&after=7"));
  assert.deepStrictEqual(idleEvents, ["codex_notice:8", "state_snapshot:8"]);

  let switchUrls = [];
  let stSwitch = {
    sid: "s-switch",
    root: {children: [{classList: {contains: () => false}}]},
    renderedEvents: {"seq:9": true},
    lastSeq: 9,
    replayActive: false,
    replayWaiting: false,
    lastCatchupPoll: Date.now(),
    catchupInFlight: false
  };
  ctx.currentSid = "s-switch";
  ctx.nativeStages = {"s-switch": stSwitch};
  ctx.nativeWs = {"s-switch": {readyState: 1}};
  ctx.api = function(url){
    switchUrls.push(url);
    return Promise.resolve({ok: true, events: [], pending: []});
  };
  nativeCatchupPoll("s-switch", "switch");
  await Promise.resolve();
  assert.strictEqual(switchUrls.length, 1, "tab switch catch-up should bypass active-state throttle");
  assert.ok(switchUrls[0].includes("/api/nreplay?sid=s-switch&after=9"));

  let staleFetchHandled = 0;
  let staleFetchResolve;
  let stStaleFetch = {
    sid: "stale-fetch",
    root: {innerHTML: "old", children: [{classList: {contains: () => false}}]},
    renderedEvents: {"seq:2": true},
    lastSeq: 2,
    replayActive: false,
    replayWaiting: false,
    replayFetchId: 0,
    lastCatchupPoll: 0,
    catchupInFlight: false
  };
  ctx.currentSid = "stale-fetch";
  ctx.nativeStages = {"stale-fetch": stStaleFetch};
  ctx.nativeWs = {"stale-fetch": {readyState: 1}};
  ctx.api = function(_url){
    return new Promise((resolve) => { staleFetchResolve = resolve; });
  };
  ctx.nHandle = function(){ staleFetchHandled++; };
  nativeCatchupPoll("stale-fetch", "activity");
  assert.strictEqual(stStaleFetch.catchupInFlight, true);
  nResetReplayState(stStaleFetch);
  assert.strictEqual(stStaleFetch.catchupInFlight, false);
  assert.strictEqual(stStaleFetch.replayFetchId, 1);
  staleFetchResolve({
    ok: true,
    events: [{type:"assistant", seq:3}],
    snapshot: {type:"state_snapshot", last_seq:3},
    pending: []
  });
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.strictEqual(staleFetchHandled, 0, "stale catch-up response after reset must not render events");
  assert.strictEqual(stStaleFetch.lastSeq, 0);

  let sockets = [];
  let stalePolls = 0;
  let staleReconnects = 0;
  let stopPolls = 0;
  let socketMessages = 0;
  ctx.WebSocket = function(url){
    this.url = url;
    this.readyState = 1;
    this.sent = [];
    this.closed = false;
    this.send = (msg) => { this.sent.push(msg); };
    this.close = () => { this.closed = true; this.readyState = 3; };
    sockets.push(this);
  };
  ctx.nativeStages = {
    s5: {
      sid: "s5",
      root: {children: [{classList: {contains: () => false}}]},
      renderedEvents: {"seq:12": true},
      lastSeq: 12,
      replayActive: false,
      replayWaiting: false
    }
  };
  ctx.nativeWs = {};
  ctx.nativeReconnectTimers = {};
  ctx.nativeReconnectState = {};
  ctx.nativePollTimers = {};
  ctx.nativePollBusy = {};
  ctx.currentSid = "s5";
  ctx.nativeStartPolling = function(){ stalePolls++; };
  ctx.nativeScheduleReconnect = function(){ staleReconnects++; };
  ctx.nativeStopPolling = function(){ stopPolls++; };
  ctx.nHandle = function(){ socketMessages++; };
  nativeConnect("s5");
  const firstSocket = sockets[0];
  nativeConnect("s5", {force:true});
  const secondSocket = sockets[1];
  assert.notStrictEqual(firstSocket, secondSocket);
  assert.strictEqual(ctx.nativeWs.s5, secondSocket);
  firstSocket.onopen();
  firstSocket.onmessage({data: '{"type":"assistant","seq":13}'});
  firstSocket.onclose({code:1006, reason:"old"});
  assert.strictEqual(firstSocket.closed, true, "stale socket open should close itself");
  assert.strictEqual(stopPolls, 0, "stale socket open must not stop active polling");
  assert.strictEqual(socketMessages, 0, "stale socket messages must be ignored");
  assert.strictEqual(stalePolls, 0, "stale socket close must not start replay polling");
  assert.strictEqual(staleReconnects, 0, "stale socket close must not schedule reconnect");
  assert.strictEqual(ctx.nativeWs.s5, secondSocket);
  secondSocket.onmessage({data: '{"type":"assistant","seq":14}'});
  assert.strictEqual(socketMessages, 1, "current socket messages should still be handled");
  ctx.nativeReconnectState.s5 = {lastLog: Date.now(), openedAt: Date.now()};
  secondSocket.onclose({code:1006, reason:"current"});
  assert.strictEqual(stalePolls, 1, "current socket close should start replay polling");
  assert.strictEqual(staleReconnects, 1, "current socket close should schedule reconnect");
  assert.strictEqual(ctx.nativeWs.s5, null);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
'''
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        path = handle.name
    try:
        subprocess.run(["node", path], cwd=ROOT, check=True)
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass
    print("native replay frontend logic checks passed")


if __name__ == "__main__":
    main()
