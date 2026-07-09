# -*- coding: utf-8 -*-
"""
Agents Cockpit — 原生 Agent 会话 (native.py) — cli 路线

不自建 harness,而是 spawn claude CLI(--output-format stream-json),读 stdout
JSONL 事件流,经 WS 文本帧广播给前端渲染。直接获得 claude code 的全部能力
(20+ 工具 / 精细 system / 内置 compaction / thinking / skills)。

工具执行分两种模式:
  yolo(auto_approve):--dangerously-skip-permissions,工具自动执行。
  非 yolo:挂 gate_mcp.py 当 --permission-prompt-tool + ask 权限规则,Bash /
    PowerShell / Edit / Write 等工具调用经门控阻塞,网页审批(pending_approval)
    后才执行;另暴露 ask_user 工具让 agent 中途问用户(pending_ask)。
前端把每个工具调用 / 结果透明展示出来。多轮靠 claude --resume <session_id>。

认证 / 模型走 claude 自己的 ~/.claude/settings.json(cc-switch 写入),所以
manager 作为独立进程也无需继承 shell env。
"""
import os
import sys
import json
import time
import threading
import subprocess
import traceback

from common import ws_send, ws_recv, STATE_DIR, CLAUDE_BIN, MANAGER_PORT

_CLAUDE_ARGS = ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
_HERE = os.path.dirname(os.path.abspath(__file__))
_GATE_BIN = os.path.join(_HERE, "gate_mcp.py")
_GATE_TIMEOUT = 600.0          # 门控阻塞上限(秒);超时按拒绝/无回答处理
# 需要网页审批的工具(Windows 下模型走 PowerShell,故 Bash+PowerShell 都要)
_ASK_TOOLS = ["Bash", "PowerShell", "Edit", "Write", "NotebookEdit"]
# 提示模型主动用 ask_user(信息不足时问用户,别瞎猜)
_ASK_SYSTEM = ("当一个动作需要用户许可时你会被自动拦截。当信息不足、需要用户决策或确认意图时,"
               "调用 ask_user 工具向用户提问并等待回答,不要自行臆测。")


class NativeSession:
    def __init__(self, sid, cwd, yolo=False, cfg=None):
        self.sid = sid
        self.cwd = os.path.abspath(cwd)
        self.yolo = bool(yolo)          # True=跳过审批(--dangerously-skip-permissions);False=走门控
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.claude_sid = None          # claude 的 session_id(下次 --resume 续接)
        self.events = []                # 已完成的终态事件(replay 给新客户端)
        self._closed = False
        self.alive = True
        self._busy = False
        self.last_activity = time.time()
        self._lock = threading.Lock()   # 保护 events / claude_sid
        # 门控挂起态:tool_use_id -> {event, kind(approve|ask), allow, msg, ans}
        self._pending = {}
        self._pending_lock = threading.Lock()

    # ---------- public API ----------
    def send(self, prompt):
        with self._lock:
            self.events.append({"type": "user", "message": {"role": "user", "content": prompt}})
        self.last_activity = time.time()
        threading.Thread(target=self._run_cli, args=(prompt,), daemon=True).start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.alive = False
        # 唤醒所有挂起的门控(让阻塞的 await_* 返回拒绝/空,claude 得以退出)
        with self._pending_lock:
            for entry in self._pending.values():
                try: entry["event"].set()
                except Exception: pass
            self._pending.clear()
        # 清理 per-session 门控配置文件
        for p in (self._settings_path(), self._mcp_config_path()):
            try: os.unlink(p)
            except OSError: pass
        with self.clients_lock:
            socks = list(self.clients)
            self.clients.clear()
        for c in socks:
            try: c.close()
            except OSError: pass

    def state(self):
        if self._closed:
            return "idle"
        if self._busy:
            return "running"
        return "new" if not self.events else "idle"

    # ---------- 门控:权限审批 / ask_user ----------
    # await_* 由 manager 的 /api/_perm_gate、/api/_ask_gate 处理线程调用,阻塞等
    # 网页用户决定;approve/answer 由 /api/napprove、/api/nanswer 解锁。
    def await_permission(self, tool_use_id, tool_name, inp):
        """广播 pending_approval 并阻塞等用户裁决。返回 (allow, message)。"""
        entry = {"event": threading.Event(), "kind": "approve", "allow": None, "msg": None}
        with self._pending_lock:
            self._pending[tool_use_id] = entry
        self._broadcast({"type": "pending_approval", "tool_use_id": tool_use_id,
                         "name": tool_name, "input": inp,
                         "preview": self._preview_for(tool_name, inp),
                         "danger": self._is_dangerous(tool_name, inp)})
        # pending_approval 不入 self.events(挂起态不 replay,见 replay 决定)
        got = entry["event"].wait(timeout=_GATE_TIMEOUT)
        with self._pending_lock:
            self._pending.pop(tool_use_id, None)
        if not got or self._closed:
            return (False, "审批超时或会话已关闭")
        return (bool(entry["allow"]), entry["msg"])

    def await_answer(self, tool_use_id, question):
        """广播 pending_ask 并阻塞等用户回答。返回回答文本。"""
        entry = {"event": threading.Event(), "kind": "ask", "ans": None}
        with self._pending_lock:
            self._pending[tool_use_id] = entry
        self._broadcast({"type": "pending_ask", "tool_use_id": tool_use_id, "question": question})
        got = entry["event"].wait(timeout=_GATE_TIMEOUT)
        with self._pending_lock:
            self._pending.pop(tool_use_id, None)
        if not got or self._closed:
            return "(无回答/已超时)"
        return entry["ans"] or ""

    def approve(self, tool_use_id, allow, message=None):
        """网页点允许/拒绝 → 解锁对应 await_permission。返回是否命中挂起项。"""
        with self._pending_lock:
            entry = self._pending.get(tool_use_id)
        if not entry or entry.get("kind") != "approve":
            return False
        entry["allow"] = bool(allow)
        entry["msg"] = message
        entry["event"].set()
        self._broadcast({"type": "approval_decision", "tool_use_id": tool_use_id,
                         "allow": bool(allow)})
        return True

    def answer(self, tool_use_id, ans):
        """网页回答 ask_user → 解锁对应 await_answer。"""
        with self._pending_lock:
            entry = self._pending.get(tool_use_id)
        if not entry or entry.get("kind") != "ask":
            return False
        entry["ans"] = ans
        entry["event"].set()
        self._broadcast({"type": "ask_answered", "tool_use_id": tool_use_id})
        return True

    @staticmethod
    def _preview_for(tool_name, inp):
        if not isinstance(inp, dict):
            return ""
        cmd = inp.get("command") or inp.get("cmd")
        if cmd:
            return cmd
        if tool_name in ("Edit", "Write", "NotebookEdit"):
            return inp.get("file_path") or inp.get("path") or ""
        return ""   # 前端 fallback 到 JSON.stringify(input)

    @staticmethod
    def _is_dangerous(tool_name, inp):
        if not isinstance(inp, dict):
            return False
        cmd = (inp.get("command") or inp.get("cmd") or "").lower()
        return any(w in cmd for w in ("rm -rf", "rmdir", "del /f", "format ",
                                      "shutdown", "reg delete", ":(){", "mkfs"))

    # ---------- WS clients ----------
    def add_client(self, sock):
        with self._lock:
            snapshot = list(self.events)
        if snapshot:
            self._send_one(sock, {"type": "replay_batch", "events": snapshot})
        with self.clients_lock:
            self.clients.add(sock)
        def keepalive():
            # 服务端定期发 WS 协议级 ping(0x9) → 浏览器自动回 pong,产生下行流量,
            # 否则浏览器会在长时间无下行时判定连接死亡(code=1006)。
            while not self._closed:
                time.sleep(15)
                if self._closed:
                    break
                try:
                    ws_send(sock, b"", 0x9)
                except OSError:
                    break
        threading.Thread(target=keepalive, daemon=True).start()
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

    # ---------- 门控 argv / per-session 配置 ----------
    def _settings_path(self):
        return os.path.join(STATE_DIR, "gate_settings_%s.json" % self.sid)

    def _mcp_config_path(self):
        return os.path.join(STATE_DIR, "gate_mcp_%s.json" % self.sid)

    def _write_gate_configs(self):
        """写 per-session 的 --settings(ask 规则)与 --mcp-config(网关服务器)。"""
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(self._settings_path(), "w", encoding="utf-8") as f:
            json.dump({"permissions": {"ask": list(_ASK_TOOLS)}}, f, ensure_ascii=False)
        mcp = {"mcpServers": {"cockpit": {
            "command": sys.executable,
            "args": [_GATE_BIN, self.sid, str(MANAGER_PORT)]}}}
        with open(self._mcp_config_path(), "w", encoding="utf-8") as f:
            json.dump(mcp, f, ensure_ascii=False)

    def _build_argv(self, prompt):
        argv = [CLAUDE_BIN, "-p", prompt] + _CLAUDE_ARGS
        if self.claude_sid:
            argv += ["--resume", self.claude_sid]
        if self.yolo:
            argv += ["--dangerously-skip-permissions"]
            return argv
        # 非 yolo:挂门控 —— ask 规则 + 网关 MCP + 指定网关为 permission prompter
        try:
            self._write_gate_configs()
        except OSError:
            traceback.print_exc()
        argv += ["--permission-mode", "default",
                 "--settings", self._settings_path(),
                 "--mcp-config", self._mcp_config_path(),
                 "--permission-prompt-tool", "mcp__cockpit__approve",
                 "--strict-mcp-config",
                 "--append-system-prompt", _ASK_SYSTEM]
        return argv

    # ---------- claude cli ----------
    def _run_cli(self, prompt):
        self._busy = True
        self.last_activity = time.time()
        try:
            argv = self._build_argv(prompt)
            proc = subprocess.Popen(
                argv, cwd=self.cwd,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1)

            def drain():
                try:
                    for _ in proc.stderr:
                        pass
                except Exception:
                    pass
            threading.Thread(target=drain, daemon=True).start()

            for line in proc.stdout:
                line = line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                with self._lock:
                    if ev.get("session_id"):
                        self.claude_sid = ev["session_id"]
                    # 只存终态(replay 用),不存 stream_event 中间帧
                    if ev.get("type") in ("assistant", "user", "result"):
                        self.events.append(ev)
                        if len(self.events) > 200:
                            self.events = self.events[-200:]
                self._broadcast(ev)
                self.last_activity = time.time()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try: proc.kill()
                except OSError: pass
        except Exception:
            traceback.print_exc()
            self._broadcast({"type": "result", "error": "claude CLI 执行异常,见 manager 日志"})
        finally:
            self._busy = False
            self._persist()

    # ---------- persistence ----------
    def _persist(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(os.path.join(STATE_DIR, "native_%s.json" % self.sid), "w", encoding="utf-8") as f:
                json.dump({"claude_sid": self.claude_sid, "cwd": self.cwd,
                           "events": self.events[-50:]}, f, ensure_ascii=False)
        except OSError:
            pass

    @classmethod
    def recover(cls, sid, cwd):
        try:
            with open(os.path.join(STATE_DIR, "native_%s.json" % sid), "r", encoding="utf-8") as f:
                d = json.load(f)
            ns = cls(sid, d.get("cwd", cwd), yolo=False)
            ns.claude_sid = d.get("claude_sid")
            ns.events = d.get("events", [])
            return ns
        except (OSError, ValueError):
            return None
