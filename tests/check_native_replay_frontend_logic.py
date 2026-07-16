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
let ctx = {console, setTimeout, clearTimeout, window: {}, _I: () => ""};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("assets/native_utils.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_stage.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/native_replay.js", "utf8"), ctx);
const {
  nMarkRendered,
  nReplayUnseenEvents,
  nReplayEventKey,
  nReplayBatchAsync,
  nDiffResultHtml,
  nDiffStats,
  nToolResultMarkup,
  nJsonResultHtml,
  nSpecialToolBody
} = ctx;

let st = {renderedEvents: {}, lastSeq: 0};
assert.strictEqual(nMarkRendered(st, {type:"assistant", seq:1}), true);
assert.strictEqual(nMarkRendered(st, {type:"assistant", seq:1, replay:true}), false);
assert.strictEqual(st.lastSeq, 1);

assert.strictEqual(nMarkRendered(st, {type:"assistant", event_id:"evt-1"}), true);
assert.strictEqual(nMarkRendered(st, {type:"assistant", event_id:"evt-1", replay:true}), false);

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
assert.deepStrictEqual(JSON.parse(JSON.stringify(nDiffStats(sampleDiff))), {lines:6, files:1, add:1, del:1});
const diffHtml = nDiffResultHtml(sampleDiff);
assert.ok(diffHtml.includes("Diff"));
assert.ok(diffHtml.includes("diff-unified"));
assert.ok(diffHtml.includes("du-add"));
assert.ok(diffHtml.includes("du-del"));
assert.ok(nToolResultMarkup("turn-diff", sampleDiff).includes("diff-unified"));
assert.ok(nToolResultMarkup("tool-1", "plain text").includes("Result (1 lines)"));
const jsonHtml = nJsonResultHtml('{"content":[{"type":"text","text":"hello from mcp"}],"isError":false}', "demo.tool");
assert.ok(jsonHtml.includes("JSON · demo.tool"));
assert.ok(jsonHtml.includes("json-preview"));
assert.ok(jsonHtml.includes("json-result"));
assert.ok(nToolResultMarkup("mcp-tool-demo", '{"error":"bad"}', "demo.tool").includes("JSON · demo.tool · error"));
assert.ok(nSpecialToolBody("sleep", {durationMs: 1200, reason: "wait"}).includes("sleep-card"));
assert.ok(nSpecialToolBody("contextcompaction", {status: "started", summary: "compact"}).includes("compact-card"));
assert.ok(nSpecialToolBody("imagegeneration", {prompt: "a cat", size: "1024x1024"}).includes("image-card"));
assert.ok(nSpecialToolBody("imageview", {path: "https://example.test/a.png"}).includes("special-path"));

(async function(){
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
