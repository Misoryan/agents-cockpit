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
let ctx = {console, setTimeout, clearTimeout};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("assets/native_replay.js", "utf8"), ctx);
const {
  nMarkRendered,
  nReplayUnseenEvents,
  nReplayEventKey,
  nReplayBatchAsync
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
