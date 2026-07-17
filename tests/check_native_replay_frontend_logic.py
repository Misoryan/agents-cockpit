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
vm.runInContext(fs.readFileSync("assets/native_tool_results.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_terminal_cards.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_replay.js", "utf8"), ctx);
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
  nativeConnect,
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
  nStructuredToolBody
} = ctx;

let st = {renderedEvents: {}, lastSeq: 0};
assert.strictEqual(nMarkRendered(st, {type:"assistant", seq:1}), true);
assert.strictEqual(nMarkRendered(st, {type:"assistant", seq:1, replay:true}), false);
assert.strictEqual(st.lastSeq, 1);

assert.strictEqual(nMarkRendered(st, {type:"assistant", event_id:"evt-1"}), true);
assert.strictEqual(nMarkRendered(st, {type:"assistant", event_id:"evt-1", replay:true}), false);

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
