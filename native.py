# -*- coding: utf-8 -*-
"""
Agents Cockpit — 原生 Agent 会话 (native.py)

NativeSession:自建 agent harness,直接打 Anthropic 兼容端点(GLM / 真 Claude),
不走 ttyd/PTY。后台 agent-loop 线程 + 多端 WS 订阅 + Bash human-in-the-loop 审批。
和终端会话(codex/claude/ttyd/hub)并列,backend="native" 标记。

事件经 WS 文本帧(0x1)广播给所有订阅端;渲染逻辑由前端负责。
配置来自环境变量(cc-switch 已设):ANTHROPIC_BASE_URL / AUTH_TOKEN / MODEL。
"""
import os
import json
import time
import queue
import threading
import subprocess
import traceback
import http.client
from urllib.parse import urlparse

from common import ws_send, ws_recv, STATE_DIR

def _load_cfg():
    """env 优先;缺失则回退读 cc-switch 写入的 ~/.claude/settings.json
    (cockpit manager 是独立进程,未必继承交互 shell 的 cc-switch env)。"""
    base = os.environ.get("ANTHROPIC_BASE_URL")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("ANTHROPIC_MODEL")
    src = "env"
    if not token or not base:
        try:
            p = os.path.expanduser("~/.claude/settings.json")
            d = json.load(open(p, encoding="utf-8"))
            env = d.get("env", {}) or {}
            base = base or env.get("ANTHROPIC_BASE_URL")
            token = token or (env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY"))
            model = model or env.get("ANTHROPIC_MODEL")
            if token:
                src = "settings.json"
        except Exception:
            pass
    cfg = {"base_url": base or "https://open.bigmodel.cn/api/anthropic",
           "token": token or "", "model": model or "glm-5.2"}
    print("[native] cfg src=%s base=%s model=%s token=%s" % (
        src, cfg["base_url"], cfg["model"],
        ("有(%d字符)" % len(cfg["token"])) if cfg["token"] else "空!"))
    return cfg


_CFG = _load_cfg()

_TOOLS = [
    {"name": "read_file", "description": "读取本地文件内容。path 可相对(基于工作目录)或绝对。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "str_replace_edit",
     "description": "在文件中做唯一字符串替换。old_str 必须在文件中唯一出现;若文件不存在且 old_str 为空则创建文件。",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}},
                      "required": ["path", "old_str", "new_str"]}},
    {"name": "write_file", "description": "写入整个文件(覆盖或新建)。",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "bash", "description": "执行 shell 命令(需用户审批)。在指定工作目录运行。",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "glob", "description": "按 glob 模式匹配文件(如 **/*.py 或 src/**/*.ts)。返回匹配文件的相对路径列表。path 可选(默认工作目录)。",
     "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                      "required": ["pattern"]}},
    {"name": "grep", "description": "在文件中正则搜索(递归)。pattern 是正则;path 可选(默认工作目录);include 文件名过滤(如 *.py)。返回 file:line:content。",
     "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "include": {"type": "string"}},
                      "required": ["pattern"]}},
    {"name": "ls", "description": "列目录内容。path 默认工作目录。子目录名前加 /。",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "web_fetch", "description": "抓取 URL 的网页内容(纯文本,截断)。用于查文档/资料。",
     "input_schema": {"type": "object",
                      "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "web_search", "description": "联网搜索(DuckDuckGo)。query 搜索词。返回前几条结果(标题+链接)。",
     "input_schema": {"type": "object",
                      "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "todo", "description": "任务清单管理(落盘)。action=write 覆盖写(需 todos);action=read 读当前。todos 每项 {content, status(pending/in_progress/completed), activeForm}。",
     "input_schema": {"type": "object",
                      "properties": {"action": {"type": "string"},
                                     "todos": {"type": "array", "items": {"type": "object"}}},
                      "required": ["action"]}},
    {"name": "memory", "description": "跨会话记忆(落盘)。action=write(key+content)/read(key)/list。便于跨对话记住事实。",
     "input_schema": {"type": "object",
                      "properties": {"action": {"type": "string"}, "key": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["action"]}},
]

_SYSTEM_PROMPT = (
    "你是一个运行在用户本机的编码助手 agent。你可以用工具(read_file / str_replace_edit / "
    "write_file / bash)读写文件、执行命令,帮助用户完成编程与系统任务。回答用中文,简洁专业。"
    "需要信息时主动用工具获取(读文件、跑命令),不要臆测。改文件前先读懂现状;执行可能有"
    "副作用的命令前简要说明意图。完成后简要总结做了什么。"
)

_APPROVAL_TIMEOUT = 300.0   # 审批超时 5 分钟 → 自动拒绝
_BASH_TIMEOUT = 120         # bash 执行超时
_MAX_STEPS = 40             # 单轮 agent loop 最大工具调用次数(防失控)
_THINK_BUDGET = 1024
_MAX_TOKENS = 4096


def _looks_dangerous(cmd):
    c = (cmd or "").lower()
    return any(s in c for s in ("rm -rf /", "rm -rf ~", "mkfs", "dd if=", ":(){",
                                "format ", "del /s /q c:", "shutdown"))


class NativeSession:
    def __init__(self, sid, cwd, approve_tools=("bash",), cfg=None):
        self.sid = sid
        self.cwd = os.path.abspath(cwd)
        self.approve_tools = set(approve_tools)
        c = cfg or _CFG
        self.base_url = c["base_url"]
        self.token = c["token"]
        self.model = c["model"]
        self.messages = []                 # Anthropic messages 历史
        self.clients = set()               # 订阅者裸 socket
        self.clients_lock = threading.Lock()
        self._inbox = queue.Queue()        # 用户消息队列
        self._approvals = {}               # tool_use_id -> {event, decision, name, input}
        self._approvals_lock = threading.Lock()
        self._closed = False
        self.alive = True
        self._busy = False                 # agent loop 正在跑 turn
        self._has_pending = False          # 有待审批 bash
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

    # ---------- public API ----------
    def send(self, prompt):
        self.last_activity = time.time()
        self._inbox.put({"role": "user", "content": prompt})

    def approve(self, tool_use_id, allow, message=None):
        with self._approvals_lock:
            req = self._approvals.get(tool_use_id)
        if not req:
            return False
        if req["decision"] is None:
            req["decision"] = {"allow": bool(allow), "message": message}
            req["event"].set()
        return True

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.alive = False
        self._inbox.put(None)
        with self._approvals_lock:
            for req in self._approvals.values():
                if req["decision"] is None:
                    req["decision"] = {"allow": False, "message": "会话已关闭"}
                req["event"].set()
        with self.clients_lock:
            socks = list(self.clients)
            self.clients.clear()
        for c in socks:
            try: c.close()
            except OSError: pass

    def _persist(self):
        """把对话历史落盘,供 manager 重启后 reattach 恢复。"""
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(os.path.join(STATE_DIR, "native_%s.json" % self.sid), "w", encoding="utf-8") as f:
                json.dump({"messages": self.messages, "cwd": self.cwd}, f, ensure_ascii=False)
        except OSError:
            pass

    @classmethod
    def recover(cls, sid, cwd):
        """从落盘文件恢复一个 native 会话(读取历史 messages)。失败返回 None。"""
        try:
            with open(os.path.join(STATE_DIR, "native_%s.json" % sid), "r", encoding="utf-8") as f:
                d = json.load(f)
            ns = cls(sid, d.get("cwd", cwd))
            ns.messages = d.get("messages", [])
            return ns
        except (OSError, ValueError):
            return None

    def state(self):
        if self._closed:
            return "idle"
        if self._has_pending:
            return "confirm"
        if self._busy:
            return "running"
        return "new" if not self.messages else "idle"

    # ---------- WS clients ----------
    def add_client(self, sock):
        # 新客户端先 replay 已完成的终态(messages),再阻塞读上行(仅断开检测)
        with self.clients_lock:
            snapshot = list(self.messages)
        for m in snapshot:
            self._send_one(sock, {"type": "assistant" if m.get("role") == "assistant" else "user",
                                  "message": m, "replay": True})
        with self.clients_lock:
            self.clients.add(sock)
        try:
            while not self._closed:
                op, _payload = ws_recv(sock)
                if op is None or op == 0x8:
                    break
        except OSError:
            pass
        finally:
            with self.clients_lock:
                self.clients.discard(sock)
            try: sock.close()
            except OSError: pass

    def _broadcast(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        with self.clients_lock:
            clients = list(self.clients)
        dead = []
        for c in clients:
            try:
                ws_send(c, data, 0x1)
            except OSError:
                dead.append(c)
        if dead:
            with self.clients_lock:
                for c in dead:
                    self.clients.discard(c)

    def _send_one(self, sock, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            ws_send(sock, data, 0x1)
        except OSError:
            with self.clients_lock:
                self.clients.discard(sock)

    # ---------- agent loop ----------
    def _run_loop(self):
        while not self._closed:
            try:
                msg = self._inbox.get(timeout=2)
            except queue.Empty:
                continue
            if msg is None:
                break
            self.messages.append(msg)
            self._busy = True
            try:
                steps = 0
                stop_loop = False
                while steps < _MAX_STEPS and not self._closed:
                    steps += 1
                    blocks, stop = self._stream_turn()
                    if blocks is None:
                        self._broadcast({"type": "result", "error": "请求失败(已重试),请稍后重试"})
                        stop_loop = True
                        break
                    self.messages.append({"role": "assistant", "content": blocks})
                    self._persist()
                    self._broadcast({"type": "assistant",
                                     "message": {"role": "assistant", "content": blocks}})
                    if stop != "tool_use":
                        self._broadcast({"type": "result"})
                        stop_loop = True
                        break
                    results = self._exec_tools(blocks)
                    if results is None:
                        stop_loop = True
                        break
                    self.messages.append({"role": "user", "content": results})
                    self._persist()
                if not stop_loop and not self._closed:
                    self._broadcast({"type": "result", "error": "达到最大步数上限(%d),已停止" % _MAX_STEPS})
            except Exception:
                traceback.print_exc()
                try:
                    self._broadcast({"type": "result", "error": "agent 内部错误,见 manager 日志"})
                except Exception:
                    pass
            finally:
                self._busy = False
                self._has_pending = False

    def _stream_turn(self):
        """请求一轮(stream),解析 Anthropic SSE,实时 broadcast text_delta。
        网络失败重试 3 次;全失败返回 (None, None)。"""
        body = json.dumps({
            "model": self.model, "max_tokens": _MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "thinking": {"type": "enabled", "budget_tokens": _THINK_BUDGET},
            "tools": _TOOLS, "messages": self.messages, "stream": True,
        }, ensure_ascii=False).encode("utf-8")
        for attempt in range(3):
            try:
                return self._do_stream(body)
            except (OSError, http.client.HTTPException) as e:
                print("native[%s] stream 重试 %d: %s" % (self.sid, attempt + 1, e))
                time.sleep(0.8 * (attempt + 1))
            except Exception:
                traceback.print_exc()
                return None, None
        return None, None

    def _do_stream(self, body):
        u = urlparse(self.base_url)
        conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(u.netloc, timeout=180)
        path = u.path.rstrip("/") + "/v1/messages"
        conn.request("POST", path, body, headers={
            "x-api-key": self.token,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        })
        resp = conn.getresponse()
        if resp.status != 200:
            err = resp.read().decode("utf-8", "replace")[:300]
            conn.close()
            raise OSError("端点 HTTP %d: %s" % (resp.status, err))
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
                    self._broadcast({"type": "stream_event", "event": {"type": "content_block_delta",
                             "delta": {"type": "text_delta", "text": d.get("text", "")}}})
                elif dt == "thinking_delta":
                    b["thinking"] = b.get("thinking", "") + (d.get("thinking") or "")
                    self._broadcast({"type": "stream_event", "event": {"type": "content_block_delta",
                             "delta": {"type": "thinking_delta", "thinking": d.get("thinking", "")}}})
                elif dt == "input_json_delta":
                    b["_input_json"] = b.get("_input_json", "") + (d.get("partial_json") or "")
            elif t == "message_delta":
                sr = (ev.get("delta", {}) or {}).get("stop_reason")
                if sr:
                    stop_reason = sr
        conn.close()
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
        if not out:
            # GLM 偶发返回 200 + 非 SSE 的 {"detail":"error parsing the body"},这里会被上面
            # 的 data: 过滤吞掉导致 blocks 空 —— 当错误处理,交给 _stream_turn 重试。
            raise OSError("端点返回空内容(GLM 偶发 'error parsing body'),将重试")
        return out, stop_reason

    # ---------- tool execution ----------
    def _exec_tools(self, blocks):
        results = []
        for b in blocks:
            if self._closed:
                return None
            if b.get("type") != "tool_use":
                continue
            name = b.get("name")
            inp = b.get("input", {}) or {}
            tuid = b.get("id", "")
            if name in self.approve_tools:
                dec = self._await_approval(tuid, name, inp)
                self._broadcast({"type": "approval_decision", "tool_use_id": tuid,
                                 "allow": dec["allow"], "message": dec.get("message")})
                self._has_pending = False
                if not dec["allow"]:
                    content = "(用户拒绝执行: %s)" % (dec.get("message") or "")
                    results.append({"type": "tool_result", "tool_use_id": tuid, "content": content})
                    self._broadcast({"type": "user", "message": {"role": "user",
                                 "content": [{"type": "tool_result", "content": content}]}})
                    continue
            content = self._safe_exec(name, inp)
            results.append({"type": "tool_result", "tool_use_id": tuid, "content": content})
            self._broadcast({"type": "user", "message": {"role": "user",
                         "content": [{"type": "tool_result", "content": content}]}})
        return results

    def _await_approval(self, tuid, name, inp):
        req = {"event": threading.Event(), "decision": None, "name": name, "input": inp}
        with self._approvals_lock:
            self._approvals[tuid] = req
        self._has_pending = True
        preview = inp.get("command", "") if name == "bash" else json.dumps(inp, ensure_ascii=False)
        self._broadcast({"type": "pending_approval", "tool_use_id": tuid, "name": name,
                         "input": inp, "preview": preview,
                         "danger": bool(name == "bash" and _looks_dangerous(preview))})
        ok = req["event"].wait(timeout=_APPROVAL_TIMEOUT)
        with self._approvals_lock:
            self._approvals.pop(tuid, None)
        if not ok or req["decision"] is None:
            return {"allow": False, "message": "审批超时(自动拒绝)"}
        return req["decision"]

    def _safe_exec(self, name, inp):
        try:
            if name == "read_file":
                full = self._resolve(inp.get("path", ""))
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
                return txt[:20000] + ("…[已截断]" if len(txt) > 20000 else "")
            if name == "write_file":
                full = self._resolve(inp.get("path", ""))
                parent = os.path.dirname(full)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(full, "w", encoding="utf-8") as f:
                    f.write(inp.get("content", ""))
                return "已写入 %s(%d 字节)" % (full, len(inp.get("content", "")))
            if name == "str_replace_edit":
                full = self._resolve(inp.get("path", ""))
                old = inp.get("old_str", "")
                new = inp.get("new_str", "")
                if not os.path.exists(full):
                    if old == "":
                        parent = os.path.dirname(full)
                        if parent:
                            os.makedirs(parent, exist_ok=True)
                        with open(full, "w", encoding="utf-8") as f:
                            f.write(new)
                        return "已创建 %s" % full
                    return "(文件不存在: %s)" % full
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    cur = f.read()
                cnt = cur.count(old)
                if cnt == 0:
                    return "(未找到 old_str;请提供更完整的唯一上下文)"
                if cnt > 1:
                    return "(old_str 出现 %d 次,需更唯一的上下文)" % cnt
                with open(full, "w", encoding="utf-8") as f:
                    f.write(cur.replace(old, new, 1))
                return "已替换 %s" % full
            if name == "bash":
                cmd = inp.get("command", "")
                r = subprocess.run(cmd, shell=True, cwd=self.cwd, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=_BASH_TIMEOUT)
                out = (r.stdout or "")
                if r.stderr:
                    out += ("\n[stderr]\n" + r.stderr)
                return ("[exit %d]\n" % r.returncode) + out[:20000] + ("…[已截断]" if len(out) > 20000 else "")
            if name == "glob":
                import glob as _glob
                pat = inp.get("pattern", "")
                base = inp.get("path") or self.cwd
                full = pat if os.path.isabs(pat) else os.path.join(base, pat)
                ms = _glob.glob(full, recursive=True)[:200]
                return "\n".join(os.path.relpath(m, self.cwd) for m in ms) or "(无匹配)"
            if name == "grep":
                import re as _re
                import fnmatch as _fm
                try:
                    rx = _re.compile(inp.get("pattern", "") or "", _re.IGNORECASE)
                except _re.error as e:
                    return "(正则错误: %s)" % e
                base = self._resolve(inp.get("path") or ".")
                inc = inp.get("include")
                hits = []
                for dp, _d, fs in os.walk(base):
                    for fn in fs:
                        if inc and not _fm.fnmatch(fn, inc):
                            continue
                        fp = os.path.join(dp, fn)
                        try:
                            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                                for i, line in enumerate(f, 1):
                                    if rx.search(line):
                                        hits.append("%s:%d: %s" % (os.path.relpath(fp, self.cwd), i, line.rstrip()[:200]))
                                        if len(hits) >= 100:
                                            break
                        except OSError:
                            pass
                    if len(hits) >= 100:
                        break
                return "\n".join(hits) or "(无匹配)"
            if name == "ls":
                base = self._resolve(inp.get("path") or ".")
                items = sorted(os.listdir(base))[:300]
                return "\n".join(("/" + x if os.path.isdir(os.path.join(base, x)) else x) for x in items)
            if name == "web_fetch":
                import urllib.request
                url = inp.get("url", "")
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = r.read(60000).decode("utf-8", "replace")
                    return data[:8000]
                except Exception as e:
                    return "(抓取失败: %s)" % e
            if name == "web_search":
                import urllib.request, urllib.parse
                import re as _re2
                q = inp.get("query", "")
                try:
                    surl = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
                    req = urllib.request.Request(surl, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        html = r.read().decode("utf-8", "replace")
                    results = []
                    for m in _re2.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, _re2.S):
                        title = _re2.sub(r'<[^>]+>', '', m.group(2)).strip()
                        if title:
                            results.append(title + " — " + m.group(1))
                        if len(results) >= 6:
                            break
                    return "\n".join(results) or "(无结果/抓取失败)"
                except Exception as e:
                    return "(搜索失败: %s)" % e
            if name == "todo":
                action = (inp.get("action") or "").strip()
                tpath = os.path.join(STATE_DIR, "native_%s_todo.json" % self.sid)
                if action == "write":
                    todos = inp.get("todos", [])
                    try:
                        with open(tpath, "w", encoding="utf-8") as f:
                            json.dump(todos, f, ensure_ascii=False)
                    except OSError as e:
                        return "(写失败: %s)" % e
                    return "已保存 %d 个任务" % len(todos)
                if action == "read":
                    try:
                        with open(tpath, encoding="utf-8") as f:
                            return json.dumps(json.load(f), ensure_ascii=False, indent=2)
                    except OSError:
                        return "(无任务)"
                return "(未知 action: %s;用 write/read)" % action
            if name == "memory":
                action = (inp.get("action") or "").strip()
                mem_dir = os.path.join(STATE_DIR, "memory")
                key = (inp.get("key") or "").strip().replace("/", "_").replace("\\", "_")
                if action == "write":
                    if not key:
                        return "(缺少 key)"
                    os.makedirs(mem_dir, exist_ok=True)
                    try:
                        with open(os.path.join(mem_dir, key + ".md"), "w", encoding="utf-8") as f:
                            f.write(inp.get("content", ""))
                    except OSError as e:
                        return "(写失败: %s)" % e
                    return "已写入 memory/%s" % key
                if action == "read":
                    try:
                        with open(os.path.join(mem_dir, key + ".md"), encoding="utf-8") as f:
                            return f.read()
                    except OSError:
                        return "(无此 memory: %s)" % key
                if action == "list":
                    try:
                        return "\n".join(sorted(os.listdir(mem_dir))) or "(空)"
                    except OSError:
                        return "(空)"
                return "(未知 action: %s;用 write/read/list)" % action
            return "(未知工具: %s)" % name
        except subprocess.TimeoutExpired:
            return "(bash 超时 %ds,已终止)" % _BASH_TIMEOUT
        except PermissionError as e:
            return "(拒绝: %s)" % e
        except OSError as e:
            return "(执行失败: %s)" % e

    def _resolve(self, path):
        full = path if os.path.isabs(path) else os.path.join(self.cwd, path)
        real = os.path.realpath(full)
        root = os.path.realpath(self.cwd)
        if os.path.commonpath([os.path.normcase(root), os.path.normcase(real)]) != os.path.normcase(root):
            raise PermissionError("路径越界(工作目录外): %s" % real)
        return real
