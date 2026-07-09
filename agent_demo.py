# -*- coding: utf-8 -*-
"""
Agents Cockpit — 原生 Agent harness 原型 (agent_demo.py)

不走 claude CLI(在 GLM 后端会因 20+ tools + thinking + beta 头过载返回 529),
而是自建 agent loop 直接打 Anthropic 兼容端点(GLM / 真 Claude / 任何兼容),
自己执行工具。→ 原生渲染 + 完整工具链 + 思考 + 多轮,且请求小、后端扛得住。

后端:每会话保留 messages,POST {base_url}/v1/messages (stream:true, tools,
thinking) → 解析 Anthropic SSE → 转 claude stream-json 风格事件经 SSE 推前端 →
收到 tool_use 则本机执行 read_file → 回填 tool_result → 继续循环直到 end_turn。

配置来自环境变量(cc-switch 已设):
  ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN(或 API_KEY)/ ANTHROPIC_MODEL

启动: python agent_demo.py [--port 7979] [--dir <工作目录>]
打开:  http://127.0.0.1:7979
"""
import os
import sys
import json
import uuid
import argparse
import http.client
import http.server
import socketserver
from urllib.parse import urlparse

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY") or ""
MODEL = os.environ.get("ANTHROPIC_MODEL", "glm-5.2")
WORKDIR = os.getcwd()
PORT = 7979

SESSIONS = {}   # sid -> {"messages": [...], "cwd": ...}

_TOOLS = [{
    "name": "read_file",
    "description": "读取本地文件内容。path 可为相对路径(基于工作目录)或绝对路径。",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
    },
}]

PAGE = r'''<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>原生 Agent · harness 原型</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;background:#0e0f13;color:#e6e6e6;font:14px/1.55 system-ui,Segoe UI,Microsoft YaHei,sans-serif}
  header{padding:10px 14px;background:#15161a;border-bottom:1px solid #2e2f37}
  header h1{font-size:15px;margin:0;font-weight:600}
  header .hint{color:#8b91a0;font-size:12px;margin-left:6px}
  label{color:#8b91a0;font-size:12px}
  input[type=text]{background:#15161a;border:1px solid #2e2f37;border-radius:6px;color:#e6e6e6;padding:6px 8px;font:inherit}
  #dir{width:100%;font-family:ui-monospace,Consolas,monospace;font-size:12px;margin-top:4px}
  main{max-width:920px;margin:0 auto;padding:14px}
  #log{display:flex;flex-direction:column;gap:10px;padding-bottom:120px}
  .msg{padding:10px 12px;border-radius:10px;word-break:break-word;animation:f .12s ease}
  @keyframes f{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
  .msg.user{align-self:flex-end;max-width:80%;background:#2a5bd7;color:#fff}
  .msg.assistant{align-self:flex-start;max-width:92%;background:#1b1d24;border:1px solid #2a2c35}
  .msg.assistant .txt{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:13px}
  .msg.sys,.msg.done{align-self:center;background:#171821;border:1px dashed #333443;color:#9aa0aa;font-size:12px}
  .msg.tool,.msg.result,.msg.think{align-self:flex-start;max-width:92%;background:#16181f;border:1px solid #262830;font-size:12px}
  details summary{cursor:pointer;color:#7ab7ff;font-weight:600}
  pre{margin:6px 0 0;background:#0b0c10;padding:8px;border-radius:6px;overflow:auto;max-height:260px;font:11px/1.4 ui-monospace,Consolas,monospace;color:#cdd2dc}
  footer{position:fixed;left:0;right:0;bottom:0;background:#15161a;border-top:1px solid #2e2f37;padding:10px}
  footer .wrap{max-width:920px;margin:0 auto;display:flex;gap:8px}
  #prompt{flex:1;resize:none;height:48px;padding:8px 10px}
  #send{padding:0 18px;font-weight:600;background:#2a5bd7;color:#fff;border:0;border-radius:8px;cursor:pointer}
  #send:disabled{opacity:.5}
</style>
</head>
<body>
<header>
  <h1>🟣 原生 Agent <span class="hint">· 自建 harness(打 GLM / Anthropic 兼容端点)· 工具 read_file · 思考可见</span></h1>
</header>
<main>
  <div><label>工作目录(agent 在此读文件):</label><input type="text" id="dir" value="__DIR__" spellcheck="false"></div>
  <div id="log" style="margin-top:10px"></div>
</main>
<footer>
  <div class="wrap">
    <textarea id="prompt" placeholder="给 agent 发消息…(Enter 发送)"></textarea>
    <button id="send">发送</button>
  </div>
</footer>
<script>
var SID = "";
function $(id){ return document.getElementById(id); }
function esc(s){
  s = String(s == null ? "" : s);
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
var curTxt = null;
function newTextBubble(){
  var d = document.createElement("div"); d.className = "msg assistant";
  var t = document.createElement("div"); t.className = "txt";
  d.appendChild(t); $("log").appendChild(d); curTxt = t; return d;
}
function addRow(cls, html){
  curTxt = null;
  var d = document.createElement("div"); d.className = "msg " + cls;
  d.innerHTML = html; $("log").appendChild(d); $("log").scrollTop = 1e9;
}
function handle(obj){
  if (obj && obj.session_id) SID = obj.session_id;
  var t = obj && obj.type;
  if (t === "system"){
    if (obj.subtype === "init") addRow("sys", "🔵 会话开始 · model: " + esc(obj.model || ""));
    return;
  }
  if (t === "stream_event"){
    var dl = (obj.event || {}).delta || {};
    if (dl.type === "text_delta" && dl.text){
      if (!curTxt) newTextBubble();
      curTxt.appendChild(document.createTextNode(dl.text));
      $("log").scrollTop = 1e9;
    }
    return;
  }
  if (t === "assistant"){
    var blocks = (obj.message && obj.message.content) || [];
    blocks.forEach(function(b){
      if (b.type === "text"){
        if (!curTxt || !curTxt.textContent){ if (!curTxt) newTextBubble(); curTxt.textContent = b.text; }
      } else if (b.type === "tool_use"){
        addRow("tool", "<details><summary>🔧 " + esc(b.name) + "</summary><pre>" + esc(JSON.stringify(b.input, null, 2)) + "</pre></details>");
      } else if (b.type === "thinking"){
        addRow("think", "<details><summary>💭 思考</summary><pre>" + esc(b.thinking || "") + "</pre></details>");
      }
    });
    $("log").scrollTop = 1e9; return;
  }
  if (t === "user"){
    var bs = ((obj.message || {}).content); if (!Array.isArray(bs)) bs = bs ? [bs] : [];
    bs.forEach(function(b){
      if (b && b.type === "tool_result"){
        var c = b.content; var txt = typeof c === "string" ? c : JSON.stringify(c, null, 2);
        addRow("result", "<details><summary>↩ 工具结果</summary><pre>" + esc(txt) + "</pre></details>");
      }
    });
    return;
  }
  if (t === "result"){ addRow("done", "✅ 完成"); return; }
}
async function send(){
  var p = $("prompt").value.trim();
  if (!p || $("send").disabled) return;
  $("prompt").value = ""; $("send").disabled = true;
  addRow("user", esc(p));
  try {
    var resp = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: p, session_id: SID, dir: $("dir").value.trim() })
    });
    var reader = resp.body.getReader(); var dec = new TextDecoder("utf-8"); var buf = "";
    while (true){
      var r = await reader.read(); if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      var idx;
      while ((idx = buf.indexOf("\n\n")) >= 0){
        var chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        var dpos = chunk.indexOf("data: ");
        if (dpos < 0) continue;
        var payload = chunk.slice(dpos + 6);
        if (chunk.indexOf("event: done") >= 0) continue;
        try { handle(JSON.parse(payload)); } catch (e) {}
      }
    }
  } catch (e) { addRow("tool", "网络错误: " + esc(e && e.message || e)); }
  $("send").disabled = false; $("prompt").focus();
}
$("send").addEventListener("click", send);
$("prompt").addEventListener("keydown", function(e){
  if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); }
});
</script>
</body>
</html>
'''


def exec_tool(name, inp, cwd):
    if name == "read_file":
        p = (inp or {}).get("path", "")
        full = p if os.path.isabs(p) else os.path.join(cwd, p)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            return txt[:20000] + ("…[已截断]" if len(txt) > 20000 else "")
        except OSError as e:
            return "(读取失败: %s)" % e
    return "(未知工具: %s)" % name


def _sse(wfile, obj):
    wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
    wfile.flush()


def stream_turn(base_url, token, model, messages, wfile):
    """请求一轮(stream),解析 Anthropic SSE,把 text_delta 即时推给前端;
    返回 (content_blocks, stop_reason)。content_blocks 含 thinking/text/tool_use。"""
    u = urlparse(base_url)
    conn = http.client.HTTPSConnection(u.netloc, timeout=180)
    body = json.dumps({
        "model": model, "max_tokens": 4096,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "tools": _TOOLS,
        "messages": messages, "stream": True,
    }, ensure_ascii=False).encode("utf-8")
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    conn.request("POST", u.path.rstrip("/") + "/v1/messages", body, headers=headers)
    resp = conn.getresponse()
    blocks = {}
    stop_reason = "end_turn"
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            continue
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "content_block_start":
            idx = ev.get("index", 0)
            cb = ev.get("content_block", {}) or {}
            blocks[idx] = dict(cb)
            if cb.get("type") == "tool_use":
                blocks[idx]["_input_json"] = ""
        elif t == "content_block_delta":
            idx = ev.get("index", 0)
            d = ev.get("delta", {}) or {}
            dt = d.get("type")
            b = blocks.setdefault(idx, {"type": "text", "text": ""})
            if dt == "text_delta":
                b["text"] = b.get("text", "") + (d.get("text") or "")
                _sse(wfile, {"type": "stream_event", "event": {"type": "content_block_delta",
                         "delta": {"type": "text_delta", "text": d.get("text", "")}}})
            elif dt == "thinking_delta":
                b["thinking"] = b.get("thinking", "") + (d.get("thinking") or "")
            elif dt == "input_json_delta":
                b["_input_json"] = b.get("_input_json", "") + (d.get("partial_json") or "")
        elif t == "message_delta":
            sr = (ev.get("delta", {}) or {}).get("stop_reason")
            if sr:
                stop_reason = sr
    out = []
    for idx in sorted(blocks):
        b = blocks[idx]
        if b.get("type") == "tool_use":
            try:
                b["input"] = json.loads(b.get("_input_json", "{}") or "{}")
            except ValueError:
                b["input"] = {}
            b.pop("_input_json", None)
        out.append(b)
    conn.close()
    return out, stop_reason


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _bad(self, code, msg=""):
        b = msg.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        try: self.wfile.write(b)
        except OSError: pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            body = PAGE.replace("__DIR__", WORKDIR.replace("\\", "/")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._bad(404, "not found")

    def do_POST(self):
        if self.path != "/api/chat":
            self._bad(404, "not found"); return
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        prompt = (data.get("prompt") or "").strip()
        sid = (data.get("session_id") or "").strip()
        cwd = (data.get("dir") or WORKDIR).strip().strip('"')
        if not prompt:
            self._bad(400, "missing prompt"); return
        if not cwd or not os.path.isdir(cwd):
            cwd = WORKDIR
        if not TOKEN:
            self._bad(500, "ANTHROPIC_AUTH_TOKEN/API_KEY 未设置"); return
        if not sid:
            sid = uuid.uuid4().hex[:12]
            SESSIONS[sid] = {"messages": [], "cwd": cwd}
        sess = SESSIONS[sid]
        sess["cwd"] = cwd

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.close_connection = True
        self.end_headers()

        _sse(self.wfile, {"type": "system", "subtype": "init", "session_id": sid, "model": MODEL})
        sess["messages"].append({"role": "user", "content": prompt})

        aborted = False
        try:
            steps = 0
            while steps < 20:   # 最多 20 轮工具循环,防失控
                steps += 1
                blocks, stop = stream_turn(BASE_URL, TOKEN, MODEL, sess["messages"], self.wfile)
                _sse(self.wfile, {"type": "assistant",
                     "message": {"role": "assistant", "content": blocks}, "session_id": sid})
                sess["messages"].append({"role": "assistant", "content": blocks})
                if stop != "tool_use":
                    _sse(self.wfile, {"type": "result", "session_id": sid})
                    break
                results = []
                for b in blocks:
                    if b.get("type") == "tool_use":
                        res = exec_tool(b["name"], b.get("input", {}), sess["cwd"])
                        results.append({"type": "tool_result", "tool_use_id": b.get("id"), "content": res})
                        _sse(self.wfile, {"type": "user", "message": {"role": "user",
                             "content": [{"type": "tool_result", "content": res}]}})
                sess["messages"].append({"role": "user", "content": results})
        except (BrokenPipeError, ConnectionResetError, OSError):
            aborted = True
        except Exception as e:
            import traceback; traceback.print_exc()
            try: _sse(self.wfile, {"type": "result", "error": str(e)})
            except OSError: pass

        try:
            self.wfile.write(("event: done\ndata: " + json.dumps({"aborted": aborted}) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        except OSError:
            pass


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global WORKDIR, PORT
    ap = argparse.ArgumentParser(description="原生 Agent harness 原型(打 Anthropic 兼容端点 + 工具 + 思考)")
    ap.add_argument("--port", type=int, default=7979)
    ap.add_argument("--dir", default=os.getcwd())
    args = ap.parse_args()
    PORT = args.port
    WORKDIR = os.path.abspath(args.dir)
    print("=" * 60)
    print(" 原生 Agent harness 原型")
    print(" 打开: http://127.0.0.1:%d" % PORT)
    print(" 工作目录: %s" % WORKDIR)
    print(" 端点: %s | model: %s" % (BASE_URL, MODEL))
    print(" token: %s" % ("已设(%d字符)" % len(TOKEN) if TOKEN else "(未设!)"))
    print(" 工具: read_file | 思考: enabled(budget 1024)")
    print(" Ctrl+C 退出。独立 demo,不影响 cockpit 主服务。")
    print("=" * 60)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
