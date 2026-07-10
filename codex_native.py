# -*- coding: utf-8 -*-
"""Codex app-server backed structured sessions for Agents Cockpit.

This adapter keeps the browser-facing event shape close to native.py's Claude
stream-json events, while speaking Codex app-server JSONL/JSON-RPC on the
backend.
"""
import atexit
import json
import os
import subprocess
import threading
import time
import traceback

import common
from common import ws_send, ws_recv, STATE_DIR


_CLIENT_LOCK = threading.Lock()
_CLIENT = None

_TASK_SYSTEM = (
    "Task mode: for multi-step work, keep a concise todo list and update it as "
    "you make progress so the user can follow the task state."
)


def _push_notify_worker(title, body, event):
    try:
        common.push_notify(title, body, event)
    except Exception:
        pass


def _text_from_user_input(items):
    parts = []
    for item in items or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "\n".join(p for p in parts if p).strip()


def _json_text(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def _changes_to_diff(changes):
    out = []
    for ch in changes or []:
        if not isinstance(ch, dict):
            continue
        path = ch.get("path") or ""
        kind = ch.get("kind") or ""
        diff = ch.get("diff") or ""
        if path or kind:
            out.append("--- %s %s" % (kind, path))
        if diff:
            out.append(diff)
    return "\n".join(out).strip()


class CodexAppServerClient:
    def __init__(self):
        self.proc = None
        self.lock = threading.RLock()
        self.next_id = 1
        self.pending = {}
        self.sessions = {}
        self.stderr_tail = []
        self.initialized = False
        self.dead = False

    def ensure(self):
        needs_start = False
        with self.lock:
            if self.proc and self.proc.poll() is None and self.initialized:
                return
            needs_start = True
        if needs_start:
            self._start_locked()

    def _start_locked(self):
        with self.lock:
            self.shutdown()
            argv = common.codex_argv("app-server", "--stdio")
            if not argv:
                raise RuntimeError("Codex CLI was not found. Install codex or set [binaries] codex in config.ini.")
            self.dead = False
            self.initialized = False
            self.proc = subprocess.Popen(
                argv,
                cwd=common.HERE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=common.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
        res = self.request(
            "initialize",
            {
                "clientInfo": {"name": "agents-cockpit", "title": "Agents Cockpit", "version": "0"},
                "capabilities": {"experimentalApi": True, "requestAttestation": False},
            },
            timeout=15,
            ensure_started=False,
        )
        if res is None:
            raise RuntimeError("Codex app-server initialize returned no response")
        with self.lock:
            self.initialized = True

    def _read_stdout(self):
        proc = self.proc
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                self._dispatch(msg)
        except Exception:
            traceback.print_exc()
        finally:
            self.dead = True
            with self.lock:
                pending = list(self.pending.values())
                self.pending.clear()
            for waiter in pending:
                waiter["error"] = "Codex app-server exited"
                waiter["event"].set()
            for session in list(self.sessions.values()):
                try:
                    session.on_client_exit()
                except Exception:
                    pass

    def _read_stderr(self):
        proc = self.proc
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                self.stderr_tail.append(line)
                if len(self.stderr_tail) > 40:
                    self.stderr_tail = self.stderr_tail[-40:]
        except Exception:
            pass

    def _dispatch(self, msg):
        if "id" in msg and ("result" in msg or "error" in msg):
            with self.lock:
                waiter = self.pending.pop(str(msg.get("id")), None)
            if waiter:
                waiter["result"] = msg.get("result")
                waiter["error"] = msg.get("error")
                waiter["event"].set()
            return
        if "id" in msg and msg.get("method"):
            threading.Thread(target=self._handle_server_request, args=(msg,), daemon=True).start()
            return
        method = msg.get("method")
        params = msg.get("params") or {}
        thread_id = self._thread_id_from_params(params)
        if thread_id:
            session = self.sessions.get(thread_id)
            if session:
                session.handle_notification(method, params)

    @staticmethod
    def _thread_id_from_params(params):
        if not isinstance(params, dict):
            return None
        if params.get("threadId"):
            return params.get("threadId")
        thread = params.get("thread")
        if isinstance(thread, dict):
            return thread.get("id") or thread.get("sessionId")
        return None

    def _handle_server_request(self, msg):
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        thread_id = self._thread_id_from_params(params)
        session = self.sessions.get(thread_id) if thread_id else None
        try:
            if session:
                result = session.handle_server_request(str(req_id), method, params)
                self.respond(req_id, result)
            elif method == "currentTime/read":
                self.respond(req_id, {"utcTimestampMs": int(time.time() * 1000)})
            else:
                self.respond_error(req_id, -32601, "unsupported app-server request: %s" % method)
        except Exception as e:
            self.respond_error(req_id, -32000, str(e))

    def request(self, method, params=None, timeout=60, ensure_started=True):
        if ensure_started:
            self.ensure()
        with self.lock:
            req_id = str(self.next_id)
            self.next_id += 1
            waiter = {"event": threading.Event(), "result": None, "error": None}
            self.pending[req_id] = waiter
            line = json.dumps({"id": req_id, "method": method, "params": params}, ensure_ascii=False)
            try:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
            except Exception:
                self.pending.pop(req_id, None)
                raise
        if not waiter["event"].wait(timeout):
            with self.lock:
                self.pending.pop(req_id, None)
            raise RuntimeError("Codex app-server request timed out: %s" % method)
        if waiter["error"]:
            raise RuntimeError(_json_text(waiter["error"]))
        return waiter["result"]

    def respond(self, req_id, result):
        self._write({"id": req_id, "result": result})

    def respond_error(self, req_id, code, message):
        self._write({"id": req_id, "error": {"code": code, "message": message}})

    def _write(self, obj):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def register(self, thread_id, session):
        if thread_id:
            self.sessions[thread_id] = session

    def unregister(self, session):
        for thread_id, existing in list(self.sessions.items()):
            if existing is session:
                self.sessions.pop(thread_id, None)

    def shutdown(self):
        proc = self.proc
        self.proc = None
        self.initialized = False
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def get_app_client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = CodexAppServerClient()
        return _CLIENT


def shutdown_app_server():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            _CLIENT.shutdown()
            _CLIENT = None


atexit.register(shutdown_app_server)


class CodexSession:
    provider = "codex"

    def __init__(self, sid, cwd, yolo=False, cfg=None):
        self.sid = sid
        self.cwd = os.path.abspath(cwd)
        self.yolo = bool(yolo)
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.events = []
        self.thread_id = None
        self.last_turn_id = None
        self.model = ""
        self.model_provider = ""
        self.service_tier = ""
        self.alive = True
        self._closed = False
        self._busy = False
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._lock = threading.Lock()
        self._last_notify = {}
        self._thread_ready = False
        self._item_output = {}
        self._item_changes = {}
        self._last_usage = None
        self.plan_mode = False
        self.task_mode = False
        self.last_activity = time.time()

    def start(self):
        res = get_app_client().request("thread/start", self._thread_params(), timeout=30)
        self._apply_thread_response(res)
        self._thread_ready = True
        self._persist()

    def send(self, prompt):
        with self._lock:
            self.events.append({"type": "user", "message": {"role": "user", "content": prompt}})
        self.last_activity = time.time()
        threading.Thread(target=self._run_turn, args=(prompt,), daemon=True).start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.alive = False
        with self._pending_lock:
            for entry in self._pending.values():
                try:
                    entry["event"].set()
                except Exception:
                    pass
            self._pending.clear()
        try:
            get_app_client().unregister(self)
        except Exception:
            pass
        with self.clients_lock:
            socks = list(self.clients)
            self.clients.clear()
        for sock in socks:
            try:
                sock.close()
            except OSError:
                pass

    def interrupt(self):
        if not self.thread_id or not self.last_turn_id:
            return False
        try:
            get_app_client().request(
                "turn/interrupt",
                {"threadId": self.thread_id, "turnId": self.last_turn_id},
                timeout=10,
            )
            return True
        except Exception as e:
            self._broadcast({"type": "result", "error": "Codex interrupt failed: %s" % e})
            return False

    def state(self):
        if self._closed:
            return "idle"
        with self._pending_lock:
            if self._pending:
                return "confirm"
        if self._busy:
            return "running"
        return "new" if not self.events else "idle"

    def set_modes(self, plan=None, task=None):
        if plan is not None:
            self.plan_mode = bool(plan)
        if task is not None:
            self.task_mode = bool(task)
        self._broadcast({"type": "mode_state", "plan": self.plan_mode, "task": self.task_mode})

    def _thread_params(self):
        params = {"cwd": self.cwd}
        if self.yolo:
            params["approvalPolicy"] = "never"
            params["sandbox"] = "danger-full-access"
        return params

    def _turn_params(self, prompt):
        text = prompt
        if self.task_mode:
            text = _TASK_SYSTEM + "\n\n" + text
        params = {
            "threadId": self.thread_id,
            "cwd": self.cwd,
            "input": [{"type": "text", "text": text, "text_elements": []}],
        }
        if self.plan_mode:
            params["collaborationMode"] = {
                "mode": "plan",
                "settings": {
                    "model": self.model or "",
                    "reasoning_effort": None,
                    "developer_instructions": None,
                },
            }
        if self.yolo:
            params["approvalPolicy"] = "never"
            params["sandboxPolicy"] = {"type": "dangerFullAccess"}
        return params

    def _apply_thread_response(self, res):
        if not isinstance(res, dict):
            return
        thread = res.get("thread") or {}
        self.thread_id = thread.get("id") or thread.get("sessionId") or self.thread_id
        self.model = res.get("model") or self.model
        self.model_provider = res.get("modelProvider") or self.model_provider
        self.service_tier = res.get("serviceTier") or self.service_tier
        if self.thread_id:
            get_app_client().register(self.thread_id, self)
        if self.model:
            self._record_and_broadcast({"type": "system", "model": self.model, "version": thread.get("cliVersion")})

    def _ensure_thread(self):
        client = get_app_client()
        client.ensure()
        if self.thread_id:
            client.register(self.thread_id, self)
        if self._thread_ready:
            return
        if self.thread_id:
            res = client.request(
                "thread/resume",
                {"threadId": self.thread_id, "cwd": self.cwd, "excludeTurns": True},
                timeout=30,
            )
            self._apply_thread_response(res)
            self._thread_ready = True
        else:
            self.start()

    def _run_turn(self, prompt):
        self._busy = True
        self.last_activity = time.time()
        try:
            self._ensure_thread()
            res = get_app_client().request("turn/start", self._turn_params(prompt), timeout=30)
            turn = (res or {}).get("turn") or {}
            self.last_turn_id = turn.get("id") or self.last_turn_id
            self._persist()
        except Exception as e:
            self._busy = False
            self._record_and_broadcast({"type": "result", "error": "Codex turn failed: %s" % e})
            self._persist()

    def handle_notification(self, method, params):
        if not method:
            return
        self.last_activity = time.time()
        if method == "thread/started":
            self._apply_thread_response({"thread": params.get("thread") or {}})
        elif method == "turn/started":
            turn = params.get("turn") or {}
            self.last_turn_id = turn.get("id") or self.last_turn_id
            self._busy = True
            self._persist()
        elif method == "turn/completed":
            self._on_turn_completed(params.get("turn") or {})
        elif method == "thread/status/changed":
            status = params.get("status")
            if status == "idle" or (isinstance(status, dict) and status.get("type") == "idle"):
                self._busy = False
        elif method == "item/agentMessage/delta":
            delta = params.get("delta")
            if delta:
                self._broadcast({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": delta}}})
        elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
            delta = params.get("delta")
            if delta:
                self._broadcast({"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": delta}}})
        elif method == "item/started":
            self._on_item_started(params.get("item") or {})
        elif method == "item/completed":
            self._on_item_completed(params.get("item") or {})
        elif method == "item/commandExecution/outputDelta":
            self._append_tool_output(params.get("itemId"), params.get("delta") or "")
        elif method == "item/fileChange/patchUpdated":
            item_id = params.get("itemId")
            changes = params.get("changes") or []
            self._item_changes[item_id] = changes
            self._append_tool_output(item_id, _changes_to_diff(changes), replace=True)
        elif method == "item/mcpToolCall/progress":
            self._append_tool_output(params.get("itemId"), params.get("message") or "")
        elif method == "turn/diff/updated":
            diff = params.get("diff") or ""
            if diff:
                self._append_tool_output("turn-diff", diff, replace=True)
        elif method == "turn/plan/updated":
            self._on_plan_updated(params)
        elif method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage") or {}
            self._last_usage = self._usage_for_meta(usage)
            self._broadcast({"type": "codex_usage", "usage": usage})
        elif method == "thread/compacted":
            self._record_and_broadcast({"type": "compacted"})
        elif method in ("warning", "guardianWarning", "configWarning", "deprecationNotice"):
            msg = params.get("message") or params.get("text") or _json_text(params)
            self._broadcast({"type": "codex_notice", "message": msg})
        elif method == "error":
            self._record_and_broadcast({"type": "result", "error": params.get("message") or _json_text(params)})

    def _on_turn_completed(self, turn):
        self._busy = False
        self.last_turn_id = turn.get("id") or self.last_turn_id
        status = turn.get("status") or ""
        error = turn.get("error")
        if status == "interrupted":
            self._record_and_broadcast({"type": "interrupted"})
        else:
            ev = {"type": "result", "duration_ms": turn.get("durationMs"), "usage": self._last_usage or {}}
            if status == "failed" or error:
                ev["error"] = _json_text(error or "Codex turn failed")
                ev["is_error"] = True
            self._record_and_broadcast(ev)
            if not ev.get("error") and not self._closed:
                self._push("done", "Codex done - " + os.path.basename(self.cwd), self.cwd)
        self._persist()

    def _on_item_started(self, item):
        ev = self._tool_event_from_item(item)
        if ev:
            self._record_and_broadcast(ev)

    def _on_item_completed(self, item):
        typ = item.get("type")
        if typ == "agentMessage":
            text = item.get("text") or ""
            if text:
                self._record_and_broadcast({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        elif typ == "reasoning":
            content = "\n".join((item.get("summary") or []) + (item.get("content") or []))
            if content:
                self._record_and_broadcast({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": content}]}})
        else:
            result = self._tool_result_from_item(item)
            if result:
                self._record_and_broadcast(result)

    def _on_plan_updated(self, params):
        plan = params.get("plan") or []
        todos = [{"content": p.get("step") or "", "status": p.get("status") or "pending"} for p in plan if isinstance(p, dict)]
        if todos:
            self._record_and_broadcast({
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "id": "codex-plan", "name": "TodoWrite", "input": {"todos": todos}}]},
            })

    @staticmethod
    def _usage_for_meta(usage):
        last = (usage or {}).get("last") or {}
        return {
            "input_tokens": last.get("inputTokens") or 0,
            "output_tokens": last.get("outputTokens") or 0,
            "cache_read_input_tokens": last.get("cachedInputTokens") or 0,
            "cache_creation_input_tokens": 0,
            "reasoning_output_tokens": last.get("reasoningOutputTokens") or 0,
        }

    def _tool_event_from_item(self, item):
        typ = item.get("type")
        item_id = item.get("id") or ("item-%d" % int(time.time() * 1000))
        if typ == "commandExecution":
            command = item.get("command") or ""
            name = "PowerShell" if os.name == "nt" else "Bash"
            inp = {"command": command, "cwd": item.get("cwd") or self.cwd}
        elif typ == "fileChange":
            changes = item.get("changes") or []
            inp = {"file_path": ", ".join(ch.get("path", "") for ch in changes if isinstance(ch, dict)), "changes": changes}
            name = "Edit"
        elif typ == "mcpToolCall":
            name = "%s.%s" % (item.get("server") or "mcp", item.get("tool") or "tool")
            inp = item.get("arguments") or {}
        elif typ == "dynamicToolCall":
            name = "%s.%s" % (item.get("namespace") or "tool", item.get("tool") or "call")
            inp = item.get("arguments") or {}
        elif typ == "webSearch":
            name = "WebSearch"
            inp = {"query": item.get("query") or "", "action": item.get("action")}
        elif typ == "plan":
            return {"type": "assistant", "message": {"content": [{"type": "text", "text": item.get("text") or ""}]}}
        elif typ == "userMessage":
            txt = _text_from_user_input(item.get("content") or [])
            if txt:
                return {"type": "user", "message": {"role": "user", "content": txt}}
            return None
        else:
            name = typ or "CodexItem"
            inp = item
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": item_id, "name": name, "input": inp}]}}

    def _tool_result_from_item(self, item):
        typ = item.get("type")
        item_id = item.get("id")
        if not item_id:
            return None
        if typ == "commandExecution":
            pieces = []
            out = item.get("aggregatedOutput")
            if out:
                pieces.append(out)
            if item.get("exitCode") is not None:
                pieces.append("exit code: %s" % item.get("exitCode"))
            txt = "\n".join(pieces).strip()
        elif typ == "fileChange":
            txt = _changes_to_diff(item.get("changes") or [])
            if item.get("status"):
                txt = (txt + "\n\nstatus: " + item.get("status")).strip()
        elif typ == "mcpToolCall":
            txt = _json_text(item.get("result") or item.get("error") or {})
        elif typ == "dynamicToolCall":
            txt = _json_text(item.get("contentItems") or {"success": item.get("success")})
        elif typ in ("webSearch", "imageGeneration", "imageView", "sleep", "contextCompaction"):
            txt = _json_text(item)
        else:
            return None
        return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": item_id, "content": txt}]}}

    def _append_tool_output(self, item_id, delta, replace=False):
        if not item_id:
            return
        if replace:
            text = delta or ""
        else:
            text = self._item_output.get(item_id, "") + (delta or "")
        self._item_output[item_id] = text
        self._broadcast({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": item_id, "content": text}]}})

    def handle_server_request(self, req_id, method, params):
        if method == "item/commandExecution/requestApproval":
            return self._await_approval(req_id, method, params, "Command", params.get("command") or "")
        if method == "item/fileChange/requestApproval":
            preview = params.get("reason") or params.get("grantRoot") or "File change approval"
            return self._await_approval(req_id, method, params, "FileChange", preview)
        if method == "item/permissions/requestApproval":
            return self._await_approval(req_id, method, params, "Permissions", params.get("reason") or _json_text(params.get("permissions")))
        if method == "item/tool/requestUserInput":
            return self._await_user_input(req_id, method, params)
        if method == "mcpServer/elicitation/request":
            return self._await_user_input(req_id, method, params)
        if method == "currentTime/read":
            return {"utcTimestampMs": int(time.time() * 1000)}
        return {}

    def _await_approval(self, req_id, method, params, name, preview):
        entry = {"event": threading.Event(), "kind": "approve", "method": method, "params": params, "allow": None, "always": False}
        with self._pending_lock:
            self._pending[req_id] = entry
        danger = self._is_dangerous(preview)
        self._broadcast({
            "type": "pending_approval",
            "tool_use_id": req_id,
            "name": name,
            "input": params,
            "preview": preview,
            "danger": danger,
        })
        self._push("confirm", "Codex needs confirmation - " + os.path.basename(self.cwd), str(preview or name))
        entry["event"].wait(timeout=600)
        with self._pending_lock:
            self._pending.pop(req_id, None)
        if not entry.get("allow"):
            return self._approval_response(method, False, False, params)
        return self._approval_response(method, True, bool(entry.get("always")), params)

    def _await_user_input(self, req_id, method, params):
        questions = params.get("questions") or []
        if questions:
            question_text = "\n\n".join(q.get("question") or q.get("header") or "" for q in questions if isinstance(q, dict))
        else:
            question_text = params.get("message") or params.get("prompt") or _json_text(params)
        entry = {"event": threading.Event(), "kind": "ask", "method": method, "params": params, "answer": ""}
        with self._pending_lock:
            self._pending[req_id] = entry
        self._broadcast({"type": "pending_ask", "tool_use_id": req_id, "question": question_text})
        self._push("confirm", "Codex waits for input - " + os.path.basename(self.cwd), question_text)
        entry["event"].wait(timeout=600)
        with self._pending_lock:
            self._pending.pop(req_id, None)
        ans = entry.get("answer") or ""
        if method == "item/tool/requestUserInput":
            out = {}
            for q in questions:
                if isinstance(q, dict) and q.get("id"):
                    out[q["id"]] = {"answers": [ans]}
            return {"answers": out}
        return {"action": "accept" if ans else "decline", "content": {"answer": ans} if ans else None}

    def _approval_response(self, method, allow, always, params):
        if method == "item/commandExecution/requestApproval":
            return {"decision": ("acceptForSession" if always else "accept") if allow else "decline"}
        if method == "item/fileChange/requestApproval":
            return {"decision": ("acceptForSession" if always else "accept") if allow else "decline"}
        if method == "item/permissions/requestApproval":
            permissions = params.get("permissions") if allow else {}
            return {"permissions": permissions or {}, "scope": "session" if always else "turn"}
        return {"decision": "accept" if allow else "decline"}

    def approve(self, tool_use_id, allow, message=None, always=False):
        with self._pending_lock:
            entry = self._pending.get(tool_use_id)
        if not entry or entry.get("kind") != "approve":
            return False
        entry["allow"] = bool(allow)
        entry["always"] = bool(always)
        entry["event"].set()
        self._broadcast({"type": "approval_decision", "tool_use_id": tool_use_id, "allow": bool(allow)})
        if always and allow:
            self._broadcast({"type": "auto_allow_added", "tool": entry.get("method") or "Codex"})
        return True

    def answer(self, tool_use_id, ans):
        with self._pending_lock:
            entry = self._pending.get(tool_use_id)
        if not entry or entry.get("kind") != "ask":
            return False
        entry["answer"] = ans or ""
        entry["event"].set()
        self._broadcast({"type": "ask_answered", "tool_use_id": tool_use_id})
        return True

    @staticmethod
    def _is_dangerous(text):
        s = str(text or "").lower()
        return any(w in s for w in ("rm -rf", "rmdir", "del /f", "format ", "shutdown", "reg delete", "mkfs"))

    def _record_and_broadcast(self, obj):
        with self._lock:
            if obj.get("type") in ("assistant", "user", "result", "system", "compacted"):
                self.events.append(obj)
                if len(self.events) > 200:
                    self.events = self.events[-200:]
        self._broadcast(obj)

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
        try:
            ws_send(sock, json.dumps(obj, ensure_ascii=False).encode("utf-8"), 0x1)
        except OSError:
            with self.clients_lock:
                self.clients.discard(sock)

    def add_client(self, sock):
        with self._lock:
            snapshot = list(self.events)
        if snapshot:
            self._send_one(sock, {"type": "replay_batch", "events": snapshot})
        with self.clients_lock:
            self.clients.add(sock)

        def keepalive():
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
            try:
                sock.close()
            except OSError:
                pass

    def _push(self, event, title, body):
        try:
            if not common._notify_enabled_for(event):
                return
            now = time.time()
            if now - self._last_notify.get(event, 0.0) < common.NOTIFY_MIN_INTERVAL:
                return
            self._last_notify[event] = now
        except Exception:
            pass
        threading.Thread(target=_push_notify_worker, args=(title or "", body or "", event), daemon=True).start()

    def on_client_exit(self):
        self._busy = False
        self._thread_ready = False
        if not self._closed:
            self._broadcast({"type": "result", "error": "Codex app-server exited. It will be restarted on the next send."})

    def _state_path(self):
        return os.path.join(STATE_DIR, "codex_%s.json" % self.sid)

    def _persist(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(self._state_path(), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "thread_id": self.thread_id,
                        "last_turn_id": self.last_turn_id,
                        "cwd": self.cwd,
                        "model": self.model,
                        "model_provider": self.model_provider,
                        "service_tier": self.service_tier,
                        "events": self.events[-50:],
                    },
                    f,
                    ensure_ascii=False,
                )
        except OSError:
            pass

    @classmethod
    def recover(cls, sid, cwd):
        try:
            with open(os.path.join(STATE_DIR, "codex_%s.json" % sid), "r", encoding="utf-8") as f:
                data = json.load(f)
            ns = cls(sid, data.get("cwd") or cwd, yolo=False)
            ns.thread_id = data.get("thread_id")
            ns.last_turn_id = data.get("last_turn_id")
            ns.model = data.get("model") or ""
            ns.model_provider = data.get("model_provider") or ""
            ns.service_tier = data.get("service_tier") or ""
            ns.events = data.get("events") or []
            if ns.thread_id:
                get_app_client().register(ns.thread_id, ns)
            return ns
        except (OSError, ValueError):
            return None
