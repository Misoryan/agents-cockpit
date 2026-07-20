"""Check sidebar recent-task ordering stays stable when selecting/restoring rows."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    js = r'''
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

let ctx = {
  console,
  currentSid: "s-old",
  location: {search: ""},
  localStorage: {getItem: () => null, setItem: () => {}},
  document: {
    addEventListener: () => {},
    querySelectorAll: () => [],
    body: {classList: {add: () => {}, remove: () => {}}}
  },
  $: () => null,
  basename: (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || "",
  normDir: (p) => String(p || "").toLowerCase(),
  relTime: (ts) => String(ts),
  elapsedStr: (ts) => String(ts),
  backendShort: (b) => b || "",
  isCodexBackend: () => true,
  esc: (s) => String(s == null ? "" : s)
};

vm.createContext(ctx);
vm.runInContext(fs.readFileSync("assets/app_sidebar.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/app_sidebar_rows.js", "utf8"), ctx);

ctx.runSessions = [
  {sid:"s-old", state:"idle", dir:"E:/repo", title:"old", started:10, last_completed_at:100, last_output_ts:100},
  {sid:"s-new", state:"idle", dir:"E:/repo", title:"new", started:20, last_completed_at:300, last_output_ts:300},
  {sid:"s-run", state:"running", dir:"E:/repo", title:"run", started:30, current_turn_started_at:200, last_input_ts:200, last_output_ts:240}
];
assert.deepStrictEqual(ctx.sortedRunSessions("").map((s) => s.sid), ["s-new", "s-run", "s-old"]);
ctx.currentSid = "s-old";
let oldCurrent = ctx.sortedRunSessions("").map((s) => s.sid);
ctx.currentSid = "s-new";
assert.deepStrictEqual(ctx.sortedRunSessions("").map((s) => s.sid), oldCurrent, "clicking a session must not change recent order");

let beforeResume = [
  {kind:"hist", data:{session_id:"thread-a", title:"a", ts:300}},
  {kind:"hist", data:{session_id:"thread-b", title:"b", ts:200}},
  {kind:"hist", data:{session_id:"thread-c", title:"c", ts:100}}
].sort(ctx.recentTaskSort).map((it) => it.data.session_id);
let afterResume = [
  {kind:"hist", data:{session_id:"thread-a", title:"a", ts:300}},
  {kind:"run", data:{sid:"s-b", session_id:"thread-b", title:"b", state:"idle", started:999, last_completed_at:200, last_output_ts:200}},
  {kind:"hist", data:{session_id:"thread-c", title:"c", ts:100}}
].sort(ctx.recentTaskSort).map((it) => it.data.session_id);
assert.deepStrictEqual(afterResume, beforeResume, "restoring a history item should keep its completed-time position");

let mixed = [
  {kind:"run", data:{sid:"s-old", session_id:"thread-old", state:"idle", started:999, last_completed_at:100}},
  {kind:"hist", data:{session_id:"thread-new", ts:300}},
  {kind:"hist", data:{session_id:"thread-mid", ts:200}}
].sort(ctx.recentTaskSort).map((it) => it.data.session_id);
assert.deepStrictEqual(mixed, ["thread-new", "thread-mid", "thread-old"]);

let fakeRow = {
  nextElementSibling: {},
  getAttribute: (name) => name === "data-cwd-key" ? ctx.normDir("E:/repo") : "",
  getBoundingClientRect: () => ({top:260, bottom:430, height:170})
};
let fakeList = {
  scrollTop: 0,
  getBoundingClientRect: () => ({top:100, bottom:400, height:300}),
  querySelectorAll: () => [fakeRow]
};
ctx.$ = (id) => id === "dirlist" ? fakeList : null;
ctx.ensureDirRowVisible("E:/repo");
assert.strictEqual(fakeList.scrollTop, 82, "opening a lower folder should keep a following folder visible when there is room");
fakeList.scrollTop = 0;
ctx.ensureDirRowVisible("E:/repo", {headTop: 260});
assert.strictEqual(fakeList.scrollTop, 0, "pointer-open should keep the clicked folder anchored instead of auto-scrolling");
'''
    with subprocess.Popen(
        ["node", "-e", js],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        out, err = proc.communicate()
        if proc.returncode:
            raise AssertionError((out or "") + (err or ""))
    print("sidebar sort frontend checks passed")


if __name__ == "__main__":
    main()
