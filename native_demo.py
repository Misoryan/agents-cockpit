# -*- coding: utf-8 -*-
"""
Agents Cockpit — 原生渲染原型 (native_demo.py)

独立验证「不走终端、直接吃结构化事件流」是否成立。不依赖 web.py /
manager.py / ttyd / hub,互不干扰 —— 跑通后再谈集成。

后端:每轮 spawn 一个无状态进程
    claude -p "<prompt>"
        --output-format stream-json --verbose --include-partial-messages
        --allowedTools "Read,Edit,Bash,Write" --permission-mode acceptEdits
        [--resume <session_id>]
把 stdout 的 JSONL 事件流逐行作为 SSE 推给浏览器。多轮对话靠 session_id
(result / system 事件里带回)+ --resume 续接 —— 每轮一个新进程,崩了重起。

前端:fetch POST + ReadableStream 解析 SSE,按事件类型富渲染
(token 流式文本 / tool call 折叠 / thinking / 费用),而非终端转义。

启动:  python native_demo.py [--port 7979] [--dir <工作目录>]
打开:   http://127.0.0.1:7979
"""
import os
import sys
import json
import shutil
import time
import argparse
import subprocess
import threading
import http.server
import socketserver

CLAUDE = ""
WORKDIR = os.getcwd()
PORT = 7979


PAGE = r'''<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude 原生渲染 · 原型</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;background:#0e0f13;color:#e6e6e6;font:14px/1.55 system-ui,Segoe UI,Microsoft YaHei,sans-serif}
  header{padding:10px 14px;background:#15161a;border-bottom:1px solid #2e2f37;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  header h1{font-size:15px;margin:0;font-weight:600}
  header .hint{color:#8b91a0;font-size:12px}
  label{color:#8b91a0;font-size:12px}
  input[type=text]{background:#15161a;border:1px solid #2e2f37;border-radius:6px;color:#e6e6e6;padding:6px 8px;font:inherit}
  #dir{flex:1;min-width:200px;font-family:ui-monospace,Consolas,monospace;font-size:12px}
  main{max-width:920px;margin:0 auto;padding:14px}
  #log{display:flex;flex-direction:column;gap:10px;padding-bottom:120px}
  .msg{padding:10px 12px;border-radius:10px;white-space:normal;word-break:break-word;animation:f .12s ease}
  @keyframes f{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
  .msg.user{align-self:flex-end;max-width:80%;background:#2a5bd7;color:#fff}
  .msg.assistant{align-self:flex-start;max-width:92%;background:#1b1d24;border:1px solid #2a2c35}
  .msg.assistant .txt{white-space:pre-wrap;font-family:ui-monospace,Consolas,monospace;font-size:13px}
  .msg.sys,.msg.done{align-self:center;background:#171821;border:1px dashed #333443;color:#9aa0aa;font-size:12px;max-width:90%}
  .msg.err{align-self:center;background:#2a1414;border:1px solid #5a2424;color:#ff9a9a;font-size:12px}
  .msg.tool,.msg.result,.msg.think,.msg.raw{align-self:flex-start;max-width:92%;background:#16181f;border:1px solid #262830;font-size:12px}
  details summary{cursor:pointer;color:#7ab7ff;font-weight:600}
  details summary::-webkit-details-marker{color:#7ab7ff}
  pre{margin:6px 0 0;background:#0b0c10;padding:8px;border-radius:6px;overflow:auto;max-height:240px;font:11px/1.4 ui-monospace,Consolas,monospace;color:#cdd2dc}
  footer{position:fixed;left:0;right:0;bottom:0;background:#15161a;border-top:1px solid #2e2f37;padding:10px}
  footer .wrap{max-width:920px;margin:0 auto;display:flex;gap:8px}
  #prompt{flex:1;resize:none;height:44px;padding:8px 10px}
  #send{padding:0 18px;font-weight:600;background:#2a5bd7;color:#fff;border:0;border-radius:8px;cursor:pointer}
  #send:disabled{opacity:.5}
</style>
</head>
<body>
<header>
  <h1>🟣 Claude 原生渲染 <span class="hint">· stream-json 原型(默认放行 Read/Edit/Bash/Write)</span></h1>
</header>
<main>
  <div style="margin-bottom:10px"><label>工作目录 claude 在此运行:</label><br>
    <input type="text" id="dir" value="__DIR__" spellcheck="false"></div>
  <div id="log"></div>
</main>
<footer>
  <div class="wrap">
    <textarea id="prompt" placeholder="给 Claude 发消息…(Enter 发送,Shift+Enter 换行)"></textarea>
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
  d.appendChild(t); $("log").appendChild(d); curTxt = t;
  return d;
}
function addRow(cls, html){
  curTxt = null;
  var d = document.createElement("div"); d.className = "msg " + cls;
  d.innerHTML = html; $("log").appendChild(d);
  $("log").scrollTop = 1e9;
}
function handle(obj){
  if (obj && obj.session_id) SID = obj.session_id;
  var t = obj && obj.type;
  if (t === "system"){
    if (obj.subtype === "init") addRow("sys", "🔵 会话开始 · model: " + esc(obj.model || obj.session_id || ""));
    else if (obj.subtype === "api_retry") addRow("sys", "⚠️ API 重试 #" + esc(obj.attempt) + " · " + esc(obj.error || ""));
    return;
  }
  if (t === "stream_event"){
    var ev = obj.event || {}, dl = ev.delta || {};
    if (ev.type === "content_block_delta" && dl.type === "text_delta" && dl.text){
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
  if (t === "result"){
    var cost = (obj.total_cost_usd != null && typeof obj.total_cost_usd === "number")
               ? (" · 费用 $" + obj.total_cost_usd.toFixed(4)) : "";
    addRow("done", "✅ 完成" + cost); return;
  }
  addRow("raw", "<details><summary>" + esc(t || "event") + "</summary><pre>" + esc(JSON.stringify(obj, null, 2)) + "</pre></details>");
}
async function send(){
  var p = $("prompt").value.trim();
  if (!p || $("send").disabled) return;
  $("prompt").value = ""; $("send").disabled = true;
  addRow("user", esc(p));
  try {
    var resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: p, session_id: SID, dir: $("dir").value.trim() })
    });
    var reader = resp.body.getReader();
    var dec = new TextDecoder("utf-8");
    var buf = "";
    while (true){
      var r = await reader.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      var idx;
      while ((idx = buf.indexOf("\n\n")) >= 0){
        var chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        var dpos = chunk.indexOf("data: ");
        if (dpos < 0) continue;
        var payload = chunk.slice(dpos + 6);
        if (chunk.indexOf("event: done") >= 0){
          try { var dd = JSON.parse(payload); if (dd.stderr) addRow("err", "⚠️ stderr: " + esc(String(dd.stderr).slice(0, 600))); } catch (e) {}
          continue;
        }
        try { handle(JSON.parse(payload)); } catch (e) {}
      }
    }
  } catch (e) {
    addRow("err", "网络错误: " + esc(e && e.message || e));
  }
  $("send").disabled = false;
  $("prompt").focus();
}
$("send").addEventListener("click", send);
$("prompt").addEventListener("keydown", function(e){
  if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); }
});
</script>
</body>
</html>
'''


class Handler(http.server.BaseHTTPRequestHandler):
    # HTTP/1.0 + 流式写:靠连接关闭定界(简单可靠,SSE 在单次响应内持续 flush)
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
            safe = WORKDIR.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            body = PAGE.replace("__DIR__", safe).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._bad(404, "not found")

    def do_POST(self):
        global CLAUDE
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
        d = (data.get("dir") or WORKDIR).strip().strip('"')
        if not prompt:
            self._bad(400, "missing prompt"); return
        if not CLAUDE or not os.path.isfile(CLAUDE):
            self._bad(500, "claude CLI not found"); return
        if not d or not os.path.isdir(d):
            d = WORKDIR

        argv = [
            CLAUDE, "-p", prompt,
            "--output-format", "stream-json",
            "--verbose", "--include-partial-messages",
            "--allowedTools", "Read,Edit,Bash,Write",
            "--permission-mode", "acceptEdits",
        ]
        if sid:
            argv += ["--resume", sid]

        try:
            proc = subprocess.Popen(
                argv, cwd=d,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as e:
            self._bad(500, "spawn failed: %s" % e); return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.close_connection = True
        self.end_headers()

        err_buf = []
        def drain():
            try:
                for ln in proc.stderr:
                    err_buf.append(ln)
            except Exception:
                pass
        th = threading.Thread(target=drain, daemon=True)
        th.start()

        # watchdog:claude 长时间无输出(后端不可达反复重试后挂起、--resume 卡死等)则终止,
        # 避免 SSE 连接永挂(轮2 resume 在某些后端配置下会卡死,无此保护前端永远等不到结束)
        last_out = [time.time()]
        def watchdog():
            while proc.poll() is None:
                time.sleep(2)
                if time.time() - last_out[0] > 60:
                    try: proc.terminate()
                    except OSError: pass
                    return
        threading.Thread(target=watchdog, daemon=True).start()

        aborted = False
        try:
            for line in proc.stdout:
                last_out[0] = time.time()
                line = line.rstrip("\r\n")
                if not line:
                    continue
                self.wfile.write(("data: " + line + "\n\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            aborted = True
            try: proc.terminate()
            except OSError: pass

        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try: proc.kill()
            except OSError: pass

        th.join(timeout=2)
        err = "".join(err_buf)[-4000:]
        try:
            self.wfile.write(("event: done\ndata: " + json.dumps(
                {"exit": proc.returncode, "stderr": err, "aborted": aborted}
            ) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        except OSError:
            pass


class ThreadingHTTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global CLAUDE, WORKDIR, PORT
    ap = argparse.ArgumentParser(description="Claude 原生渲染原型(stream-json → SSE)")
    ap.add_argument("--port", type=int, default=7979)
    ap.add_argument("--dir", default=os.getcwd(), help="claude 的默认工作目录")
    args = ap.parse_args()
    PORT = args.port
    WORKDIR = os.path.abspath(args.dir)
    CLAUDE = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")
    if not CLAUDE or not os.path.isfile(CLAUDE):
        print("ERROR: 未找到 claude CLI。请先安装 Claude Code(npm i -g @anthropic-ai/claude-code)。")
        sys.exit(1)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("=" * 60)
    print(" Claude 原生渲染原型 (stream-json → SSE)")
    print(" 打开: http://127.0.0.1:%d" % PORT)
    print(" 工作目录: %s" % WORKDIR)
    print(" claude: %s" % CLAUDE)
    print(" 每轮 spawn: claude -p ... --output-format stream-json \\")
    print("              --verbose --include-partial-messages [--resume <sid>]")
    print(" Ctrl+C 退出。这是一个独立 demo,不影响 cockpit 主服务。")
    print("=" * 60)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
