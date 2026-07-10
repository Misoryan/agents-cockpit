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

import common
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
# 计划模式:只读调研 → ExitPlanMode 提交结构化计划,等用户批准再执行
_PLAN_SYSTEM = ("【计划模式】你只能使用只读工具(Read / Grep / Glob / WebFetch / WebSearch 等)进行调研,"
                "不得执行任何修改性操作(Bash / Edit / Write 等)。调研清楚后,调用 ExitPlanMode 工具"
                "提交一份结构化计划(目标 / 实施步骤 / 风险与注意事项),交由用户审批后再执行。")
# 任务模式:多步骤工作用 TodoWrite 跟踪并实时更新状态
_TASK_SYSTEM = ("【任务模式】对多步骤工作,请先用 TodoWrite 工具建立任务清单,并在推进过程中实时更新"
                "每项状态(pending → in_progress → completed),让用户随时看到进度。")


def _push_notify_worker(title, body, event):
    """外部推送(Telegram/Bark/webhook)的后台线程目标。阻塞 HTTP,必须脱线调用。"""
    try:
        common.push_notify(title, body, event)
    except Exception:
        pass


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
        self._proc = None            # 当前正在跑的 claude 子进程(interrupt 用;None=没在跑)
        self._interrupted = False    # 用户点了「打断」→ 子进程被 kill,本轮按打断收尾而非完成
        self.last_activity = time.time()
        self._lock = threading.Lock()   # 保护 events / claude_sid
        # 门控挂起态:tool_use_id -> {event, kind(approve|ask), allow, msg, ans}
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._last_notify = {}   # event -> epoch;按事件类型 min_interval 去抖外部推送
        self._allow_tools = set()   # 本会话「不再询问」工具集(approve always);同类调用门控直接放行
        self.plan_mode = False      # 计划模式:本轮 claude 跑 --permission-mode plan(只读+ExitPlanMode)
        self.task_mode = False      # 任务模式:system prompt 鼓励用 TodoWrite 跟踪多步骤工作

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

    def interrupt(self):
        """打断当前正在跑的 claude 子进程,但保留会话与历史(下次 send 重新 --resume)。
        与 close() 的区别:不关 WS、不删会话,只终止这一轮的子进程。
        子进程 stdout 读到 EOF → _run_cli 的循环结束 → 广播 interrupted 给前端收尾。
        若此刻正卡在审批/提问门控(子进程阻塞在 gate),顺带放行挂起项,免得门控线程空等 600s。
        返回是否确有进程被 kill(前端据此决定是否复位按钮)。"""
        proc = self._proc
        killed = bool(proc and proc.poll() is None)
        if killed:
            self._interrupted = True
            try:
                proc.kill()
            except OSError:
                pass
            # 子进程已死,挂起的审批/提问不会再被消费 → 唤醒门控线程让它们返回(给死掉的 MCP),
            # 避免占着线程空等 _GATE_TIMEOUT。pending_approval 卡片留在前端,用户可自行点掉。
            with self._pending_lock:
                for entry in self._pending.values():
                    try: entry["event"].set()
                    except Exception: pass
                self._pending.clear()
        return killed

    def state(self):
        if self._closed:
            return "idle"
        # 有挂起的审批/提问 → 「需确认」:侧边栏黄点 + 站内 notice + 外部推送都靠它触发
        with self._pending_lock:
            if self._pending:
                return "confirm"
        if self._busy:
            return "running"
        return "new" if not self.events else "idle"

    def _mode_system(self):
        """拼装本轮的 --append-system-prompt:基础 ask_user 提示 + 计划/任务模式提示(按开关)。"""
        parts = [_ASK_SYSTEM]
        if self.plan_mode:
            parts.append(_PLAN_SYSTEM)
        if self.task_mode:
            parts.append(_TASK_SYSTEM)
        return " ".join(parts)

    def set_modes(self, plan=None, task=None):
        """网页切换 计划/任务 模式 → 更新本会话开关,并广播 mode_state(多标签/多端同步 UI)。
        None 表示不改该开关。"""
        if plan is not None:
            self.plan_mode = bool(plan)
        if task is not None:
            self.task_mode = bool(task)
        self._broadcast({"type": "mode_state", "plan": self.plan_mode, "task": self.task_mode})

    def _push(self, event, title, body):
        """状态层(侧边栏黄点 / 站内 notice)由前端轮询 state() 驱动;这里补「真正发到手机」
        的外部推送。后台线程发,按事件类型做 NOTIFY_MIN_INTERVAL 去抖。未配置/未启用则静默。"""
        try:
            if not common._notify_enabled_for(event):
                return
            now = time.time()
            if now - self._last_notify.get(event, 0.0) < common.NOTIFY_MIN_INTERVAL:
                return
            self._last_notify[event] = now
        except Exception:
            pass
        threading.Thread(target=_push_notify_worker, args=(title or "", body or "", event),
                         daemon=True).start()

    # ---------- 门控:权限审批 / ask_user ----------
    # await_* 由 manager 的 /api/_perm_gate、/api/_ask_gate 处理线程调用,阻塞等
    # 网页用户决定;approve/answer 由 /api/napprove、/api/nanswer 解锁。
    def await_permission(self, tool_use_id, tool_name, inp):
        """广播 pending_approval 并阻塞等用户裁决。返回 (allow, message)。"""
        # 本会话已加入「不再询问」清单的工具:门控直接放行(不广播卡片、不阻塞、不推送)。
        # 高危命令(rm -rf / format / shutdown …)例外 —— 即便在允许集里也强制弹审批,守住底线。
        with self._pending_lock:
            whitelisted = tool_name in self._allow_tools
        if whitelisted and not self._is_dangerous(tool_name, inp):
            return (True, None)
        entry = {"event": threading.Event(), "kind": "approve", "allow": None, "msg": None,
                 "tool": tool_name}
        with self._pending_lock:
            self._pending[tool_use_id] = entry
        self._broadcast({"type": "pending_approval", "tool_use_id": tool_use_id,
                         "name": tool_name, "input": inp,
                         "preview": self._preview_for(tool_name, inp),
                         "danger": self._is_dangerous(tool_name, inp)})
        # 顺手推送到手机:有人没盯着网页时也能收到「需确认」
        self._push("confirm", ("⚠️ 高危需确认 · " if self._is_dangerous(tool_name, inp) else "⚠️ 需确认 · ")
                   + os.path.basename(self.cwd),
                   (self._preview_for(tool_name, inp) or tool_name or "") + "\n" + self.cwd)
        # pending_approval 不入 self.events(挂起态不 replay,见 replay 决定)
        got = entry["event"].wait(timeout=_GATE_TIMEOUT)
        with self._pending_lock:
            self._pending.pop(tool_use_id, None)
        if not got or self._closed:
            return (False, "审批超时或会话已关闭")
        allow = bool(entry["allow"])
        # 批准 ExitPlanMode = 用户认可计划 → 自动退出计划模式(下一轮回 default),广播同步前端开关。
        # 这与 claude cli「批准计划即退出 plan 模式」一致。
        if allow and tool_name == "ExitPlanMode" and self.plan_mode:
            self.plan_mode = False
            self._broadcast({"type": "mode_state", "plan": False, "task": self.task_mode})
        return (allow, entry["msg"])

    def await_answer(self, tool_use_id, question):
        """广播 pending_ask 并阻塞等用户回答。返回回答文本。"""
        entry = {"event": threading.Event(), "kind": "ask", "ans": None}
        with self._pending_lock:
            self._pending[tool_use_id] = entry
        self._broadcast({"type": "pending_ask", "tool_use_id": tool_use_id, "question": question})
        self._push("confirm", "❓ 待回答 · " + os.path.basename(self.cwd),
                   (question or "") + "\n" + self.cwd)
        got = entry["event"].wait(timeout=_GATE_TIMEOUT)
        with self._pending_lock:
            self._pending.pop(tool_use_id, None)
        if not got or self._closed:
            return "(无回答/已超时)"
        return entry["ans"] or ""

    def approve(self, tool_use_id, allow, message=None, always=False):
        """网页点允许/拒绝 → 解锁对应 await_permission。返回是否命中挂起项。
        always=True(「允许并不再询问」):把该工具加入本会话允许集,后续同类调用门控自动放行。"""
        with self._pending_lock:
            entry = self._pending.get(tool_use_id)
        if not entry or entry.get("kind") != "approve":
            return False
        tool_name = entry.get("tool")
        if always and allow and tool_name:
            with self._pending_lock:
                self._allow_tools.add(tool_name)
        entry["allow"] = bool(allow)
        entry["msg"] = message
        entry["event"].set()
        self._broadcast({"type": "approval_decision", "tool_use_id": tool_use_id,
                         "allow": bool(allow)})
        # 「不再询问」已生效:给前端一条反馈,让用户知道同类操作此后自动放行(高危仍会确认)。
        if always and allow and tool_name:
            self._broadcast({"type": "auto_allow_added", "tool": tool_name})
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
        sys_prompt = self._mode_system()
        if self.yolo:
            argv += ["--dangerously-skip-permissions"]
            if sys_prompt:
                argv += ["--append-system-prompt", sys_prompt]
            return argv
        # 非 yolo:挂门控 —— ask 规则 + 网关 MCP + 指定网关为 permission prompter。
        # plan_mode=True → --permission-mode plan(只读调研 + ExitPlanMode 提交计划,门控审批后才执行)
        try:
            self._write_gate_configs()
        except OSError:
            traceback.print_exc()
        argv += ["--permission-mode", ("plan" if self.plan_mode else "default"),
                 "--settings", self._settings_path(),
                 "--mcp-config", self._mcp_config_path(),
                 "--permission-prompt-tool", "mcp__cockpit__approve",
                 "--strict-mcp-config",
                 "--append-system-prompt", sys_prompt]
        return argv

    # ---------- claude cli ----------
    def _run_cli(self, prompt):
        self._busy = True
        self.last_activity = time.time()
        completed = False
        try:
            argv = self._build_argv(prompt)
            proc = subprocess.Popen(
                argv, cwd=self.cwd,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
            self._proc = proc   # interrupt() 据此 kill 当前轮子进程

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
            completed = True   # stdout 走完(result 已收)= 这一轮 agent 工作结束
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
            self._proc = None
            self._persist()
            # 用户点了「打断」:本轮按打断收尾(前端 interrupted 分支补系统提示 + 复位按钮),
            # 不发「已完成」推送。否则正常完成 → 推手机。
            if self._interrupted and not self._closed:
                self._interrupted = False
                self._broadcast({"type": "interrupted"})
            elif completed and not self._closed:
                self._push("done", "✅ 已完成 · " + os.path.basename(self.cwd),
                           self.cwd + " · 等待下一条指令")

    # ---------- persistence ----------
    def _persist(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(os.path.join(STATE_DIR, "native_%s.json" % self.sid), "w", encoding="utf-8") as f:
                json.dump({"claude_sid": self.claude_sid, "cwd": self.cwd,
                           "allow_tools": sorted(self._allow_tools),
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
            ns._allow_tools = set(d.get("allow_tools") or [])
            return ns
        except (OSError, ValueError):
            return None
