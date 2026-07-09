# -*- coding: utf-8 -*-
"""
Agents Cockpit — 原生 Agent 会话 (native.py) — cli 路线

不自建 harness,而是 spawn claude CLI(--output-format stream-json),读 stdout
JSONL 事件流,经 WS 文本帧广播给前端渲染。直接获得 claude code 的全部能力
(20+ 工具 / 精细 system / 内置 compaction / thinking / skills)。

工具在 -p 非交互模式下自动执行(等同 yolo);前端把每个工具调用 / 结果透明
展示出来(可看到 agent 在做什么)。多轮靠 claude --resume <session_id>。

认证 / 模型走 claude 自己的 ~/.claude/settings.json(cc-switch 写入),所以
manager 作为独立进程也无需继承 shell env。
"""
import os
import json
import time
import threading
import subprocess
import traceback

from common import ws_send, ws_recv, STATE_DIR, CLAUDE_BIN

_CLAUDE_ARGS = ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]


class NativeSession:
    def __init__(self, sid, cwd, approve_tools=(), cfg=None):
        self.sid = sid
        self.cwd = os.path.abspath(cwd)
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.claude_sid = None          # claude 的 session_id(下次 --resume 续接)
        self.events = []                # 已完成的终态事件(replay 给新客户端)
        self._closed = False
        self.alive = True
        self._busy = False
        self.last_activity = time.time()
        self._lock = threading.Lock()   # 保护 events / claude_sid

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

    # cli 路线工具自动执行,审批/提问接口保留 stub(前端不会收到 pending 事件,
    # 但路由/方法存在,避免 manager 调用报错)
    def approve(self, *a, **k):
        return False

    def answer(self, *a, **k):
        return False

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

    # ---------- claude cli ----------
    def _run_cli(self, prompt):
        self._busy = True
        self.last_activity = time.time()
        try:
            argv = [CLAUDE_BIN, "-p", prompt] + _CLAUDE_ARGS
            if self.claude_sid:
                argv += ["--resume", self.claude_sid]
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
            ns = cls(sid, d.get("cwd", cwd))
            ns.claude_sid = d.get("claude_sid")
            ns.events = d.get("events", [])
            return ns
        except (OSError, ValueError):
            return None
