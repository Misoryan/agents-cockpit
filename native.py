# -*- coding: utf-8 -*-
"""
Agents Cockpit — 原生 Agent 会话 (native.py) — cli 路线

不自建 harness,而是 spawn claude CLI(--output-format stream-json),读 stdout
JSONL 事件流,经 WS 文本帧广播给前端渲染。直接获得 claude code 的全部能力
(20+ 工具 / 精细 system / 内置 compaction / thinking / skills)。

工具执行 = 权限 × 规划 两个正交维度:
  规划:plan_mode=True → --permission-mode plan,提供 ExitPlanMode;agent 先只读调研 → 提交计划
    → 经 gate_mcp 门控让用户审批(pending_approval)→ 批准后退出 plan 继续执行。plan 优先于 yolo,
    不被 yolo 屏蔽(yolo+plan:批准计划后普通工具 allow 自动放行,不再逐项审批)。
  权限:yolo(auto_approve)→ 普通工具自动放行(plan 轮用 settings.allow;非 plan 轮用
    --dangerously-skip-permissions)。非 yolo → 挂 gate_mcp 当 --permission-prompt-tool + ask
    规则,Bash/PowerShell/Edit/Write 等逐项网页审批;另暴露 ask_user 工具让 agent 中途问用户(pending_ask)。
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
import re

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


# ---------- 529/1305 限流检测 ----------
# z.ai 网关对 glm-5.2 账号有速率限制:请求速率/并发突增会把账号推进限流冷却期(cooldown),冷却期内
# 对该账号的所有请求(哪怕一句 hi)一律返回 529/1305。这跟"瞬时过载"不同 —— 重试只会延长冷却期,
# 所以检测到限流就停止本轮、提示用户稍候,而不是硬重试。触发主因是 web 多会话并发 + send 无 busy
# 保护(CLI 单会话低频够不到限流线)。冷却期/Retry-After 的原始证据由 _dump_failure 打进 manager 日志。
_OVERLOAD_RE = re.compile(r"\b529\b|overload", re.I)


def _is_overloaded(result_ev, stderr_text):
    """本轮是否 529/限流。看 result 事件文本字段 + 累积 stderr ——
    z.ai 的 529 既有体现在 result.result("API Error: 529 [1305]..."),也可能只印在 stderr。"""
    parts = []
    if result_ev:
        parts.append(str(result_ev.get("result") or ""))
        parts.append(str(result_ev.get("error") or ""))
        parts.append(str(result_ev.get("subtype") or ""))
    if stderr_text:
        parts.append(stderr_text)
    return any(_OVERLOAD_RE.search(p) for p in parts)


def _short_err(result_ev):
    if not result_ev:
        return ""
    return str(result_ev.get("result") or result_ev.get("error") or "")[:200]


def _push_notify_worker(title, body, event, webhook_body=None):
    """外部推送(Telegram/Bark/webhook)的后台线程目标。阻塞 HTTP,必须脱线调用。"""
    try:
        common.push_notify(title, body, event, webhook_body=webhook_body)
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
        self.model = ""                # claude 当前 model(system 事件报出;新客户端连上时补发)
        self.convo_title = None      # 首条用户消息摘要(活跃会话标题优于目录名)
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
            if not self.events:
                _t = " ".join(str(prompt).split())[:60]
                if _t:
                    self.convo_title = _t
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
        """拼装本轮的 --append-system-prompt。提示必须与 _build_argv 实际挂载的能力一致:
          ask_user 由 gate_mcp 提供 → 仅在挂 gate_mcp 时注入 _ASK_SYSTEM(=plan_mode 或 非 yolo)。
          ExitPlanMode 由 --permission-mode plan 自带 → 仅 plan_mode 时注入 _PLAN_SYSTEM。
          yolo 且非 plan:不挂 gate_mcp(--dangerously-skip-permissions)→ 无 ask_user;又无 plan →
            无 ExitPlanMode;只保留 TodoWrite(claude 自带)的 _TASK_SYSTEM。
        """
        gated = self.plan_mode or (not self.yolo)   # 挂 gate_mcp ⟺ 有 ask_user
        parts = []
        if gated:
            parts.append(_ASK_SYSTEM)
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

    def _push(self, event, title, body, webhook_body=None):
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
        threading.Thread(target=_push_notify_worker,
                         args=(title or "", body or "", event, webhook_body),
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
        with self._lock:
            _m = self.model
        if _m:
            self._send_one(sock, {"type": "system", "model": _m})
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

    def _write_gate_configs(self, allow_tools=False):
        """写 per-session 的 --settings 与 --mcp-config(网关服务器)。
        allow_tools=True(yolo+plan):普通工具进 allow 自动放行,只有 ExitPlanMode 走门控审批计划。
        allow_tools=False(非 yolo):普通工具进 ask → 走 gate_mcp 逐项审批。"""
        os.makedirs(STATE_DIR, exist_ok=True)
        key = "allow" if allow_tools else "ask"
        with open(self._settings_path(), "w", encoding="utf-8") as f:
            json.dump({"permissions": {key: list(_ASK_TOOLS)}}, f, ensure_ascii=False)
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
        # 计划模式优先于 yolo:plan 用于"先规划后执行",不应被 yolo 屏蔽。无论 yolo 与否,plan_mode
        # 都挂 --permission-mode plan(提供 ExitPlanMode)+ gate_mcp(ExitPlanMode 经
        # --permission-prompt-tool 让用户审批计划)。yolo 只决定普通工具:allow 自动放行 vs ask 逐项审批。
        # 注意 plan 轮不能加 --dangerously-skip-permissions,否则 ExitPlanMode 也被 bypass、跳过计划审批。
        if self.plan_mode:
            try:
                self._write_gate_configs(allow_tools=self.yolo)
            except OSError:
                traceback.print_exc()
            argv += ["--permission-mode", "plan",
                     "--settings", self._settings_path(),
                     "--mcp-config", self._mcp_config_path(),
                     "--permission-prompt-tool", "mcp__cockpit__approve",
                     "--strict-mcp-config"]
            if sys_prompt:
                argv += ["--append-system-prompt", sys_prompt]
            return argv
        if self.yolo:
            argv += ["--dangerously-skip-permissions"]
            if sys_prompt:
                argv += ["--append-system-prompt", sys_prompt]
            return argv
        # 非 yolo 非 plan:default + 门控逐项审批
        try:
            self._write_gate_configs(allow_tools=False)
        except OSError:
            traceback.print_exc()
        argv += ["--permission-mode", "default",
                 "--settings", self._settings_path(),
                 "--mcp-config", self._mcp_config_path(),
                 "--permission-prompt-tool", "mcp__cockpit__approve",
                 "--strict-mcp-config",
                 "--append-system-prompt", sys_prompt]
        return argv

    # ---------- claude cli ----------
    def _run_one_round(self, prompt):
        """Spawn claude CLI 一次。实时广播 result 以外的所有事件;result 事件暂存返回,由 _run_cli
        据其判断 529 过载后重试或正常收尾。返回 (result_ev, ran_clean, stderr_text)。

        result 不在此广播/入 events —— 因为前端 result 分支会复位发送按钮并判定本轮结束(native.py
        顶部契约);529 的 error result 必须由外层拦下重试,不能提前推给前端。"""
        argv = self._build_argv(prompt)
        proc = subprocess.Popen(
            argv, cwd=self.cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._proc = proc   # interrupt() 据此 kill 当前轮子进程

        stderr_buf = []
        threading.Thread(target=self._drain_stderr, args=(proc, stderr_buf), daemon=True).start()

        result_ev = None
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
                if ev.get("type") == "system" and ev.get("model"):
                    self.model = ev["model"]
            if ev.get("type") == "result":
                result_ev = ev   # 暂存,不广播不入 events
                continue
            # 只存终态(replay 用),不存 stream_event 中间帧
            if ev.get("type") in ("assistant", "user"):
                with self._lock:
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
        return result_ev, True, "".join(stderr_buf)

    @staticmethod
    def _drain_stderr(proc, buf):
        """读 claude CLI 的 stderr 到 buf(诊断用)。原先直接 for+pass 吞掉,连 CLI 的「正在重试/
        过载」提示都看不到;现在累积起来,失败时由 _run_cli 打印,便于定位网关问题。"""
        try:
            for line in proc.stderr:
                buf.append(line)
        except Exception:
            pass

    def _dump_failure(self, tag, result_ev, stderr_text):
        """失败时把完整 result + stderr 打进 manager 日志。z.ai 的 529/1305 里藏着 request-id、
        错误码、可能的 Retry-After(冷却剩余秒)—— 这是坐实"限流冷却期"假设的关键证据,不截断。"""
        try:
            print("[native %s] === %s ===" % (self.sid, tag))
            if result_ev:
                print("[native %s] result: %s"
                      % (self.sid, json.dumps(result_ev, ensure_ascii=False)))
            if stderr_text and stderr_text.strip():
                print("[native %s] stderr:\n%s" % (self.sid, stderr_text))
        except Exception:
            pass

    def _run_cli(self, prompt):
        self._busy = True
        self.last_activity = time.time()
        success = False
        try:
            result_ev, _ran_clean, stderr_text = self._run_one_round(prompt)
            if self._interrupted or self._closed:
                pass   # 用户打断/会话关闭 → finally 里 interrupted 分支收尾
            elif result_ev is not None:
                # 529/1305 限流:不重试(冷却期内重试只会延长冷却)。改广播专门的 rate_limited 提示,
                # 让用户知道是账号被限速、稍候再发,而非当成普通报错。
                if _is_overloaded(result_ev, stderr_text):
                    self._dump_failure("rate-limit/overload (1305/529)", result_ev, stderr_text)
                    self._broadcast({"type": "rate_limited",
                                     "detail": _short_err(result_ev)})
                else:
                    self._broadcast(result_ev)
                    success = not (result_ev.get("is_error") or result_ev.get("error"))
                with self._lock:
                    self.events.append(result_ev)
                    if len(self.events) > 200:
                        self.events = self.events[-200:]
            elif stderr_text.strip():
                # 没拿到 result 事件却有 stderr(进程级崩溃):dump 诊断 + 广播错误 result
                self._dump_failure("process crash (no result event)", None, stderr_text)
                self._broadcast({"type": "result",
                                 "error": "claude CLI 异常退出,见 manager 日志"})
            else:
                # 极端:stdout 无 result 事件、stderr 也空(不应发生)→ 仍给前端收尾,避免卡住
                self._broadcast({"type": "result", "error": "未收到 claude 结果事件"})
        except Exception:
            traceback.print_exc()
            self._broadcast({"type": "result", "error": "claude CLI 执行异常,见 manager 日志"})
        finally:
            self._busy = False
            self._proc = None
            self._persist()
            # 用户点了「打断」:本轮按打断收尾(前端 interrupted 分支补系统提示 + 复位按钮),
            # 不发「已完成」推送。否则真正成功完成 → 推手机(限流/失败不推,避免误导)。
            if self._interrupted and not self._closed:
                self._interrupted = False
                self._broadcast({"type": "interrupted"})
            elif success and not self._closed:
                with self._lock:
                    webhook_body = common.notify_result_text(self.events)
                self._push("done", "✅ 已完成 · " + os.path.basename(self.cwd),
                           self.cwd + " · 等待下一条指令",
                           webhook_body=webhook_body or (self.cwd + " · 已完成但没有文本结果"))

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
