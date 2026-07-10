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


def _push_notify_worker(title, body, event, webhook_body=None):
    try:
        common.push_notify(title, body, event, webhook_body=webhook_body)
    except Exception:
        pass


def _text_from_user_input(items):
    parts = []
    for item in items or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "\n".join(p for p in parts if p).strip()


def _clean_questions(questions):
    out = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        opts = []
        for opt in q.get("options") or []:
            if isinstance(opt, dict):
                opts.append({
                    "label": str(opt.get("label") or ""),
                    "description": str(opt.get("description") or ""),
                })
            elif opt is not None:
                opts.append({"label": str(opt), "description": ""})
        out.append({
            "id": str(q.get("id") or ""),
            "header": str(q.get("header") or ""),
            "question": str(q.get("question") or ""),
            "isOther": bool(q.get("isOther")),
            "isSecret": bool(q.get("isSecret")),
            "options": opts,
        })
    return out


def _question_text(questions, fallback=""):
    parts = []
    for q in questions or []:
        text = q.get("question") or q.get("header") or ""
        if text:
            parts.append(text)
    return "\n\n".join(parts) or fallback


def _answer_list(value):
    if isinstance(value, dict) and "answers" in value:
        value = value.get("answers")
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None and str(v) != ""]
    if value is None:
        return []
    text = str(value)
    return [text] if text else []


def _answers_for_questions(questions, answer):
    out = {}
    answer_map = answer if isinstance(answer, dict) else None
    for idx, q in enumerate(questions or []):
        qid = q.get("id") or str(idx)
        if answer_map is not None:
            raw = answer_map.get(qid)
            if raw is None:
                raw = answer_map.get(str(idx))
        else:
            raw = answer
        out[qid] = {"answers": _answer_list(raw)}
    return out


def _json_text(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def _compact_json(obj, limit=900):
    text = _json_text(obj)
    if len(text) > limit:
        return text[:limit] + "\n... (truncated)"
    return text


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


def _epoch(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    if value > 100000000000:
        value = value / 1000.0
    return value


def _thread_id(thread):
    if not isinstance(thread, dict):
        return ""
    return thread.get("id") or thread.get("sessionId") or ""


def _thread_title(thread):
    if not isinstance(thread, dict):
        return "(Untitled)"
    return (thread.get("name") or thread.get("preview") or thread.get("agentNickname")
            or _thread_id(thread) or "(Untitled)")


def _thread_history_item(thread, archived=False):
    tid = _thread_id(thread)
    if not tid:
        return None
    return {
        "session_id": tid,
        "thread_id": tid,
        "cwd": thread.get("cwd") or os.path.expanduser("~"),
        "ts": _epoch(thread.get("recencyAt") or thread.get("updatedAt") or thread.get("createdAt")),
        "title": _thread_title(thread),
        "originator": thread.get("source") or "",
        "backend": "codex_native",
        "provider": "codex",
        "archived": bool(archived),
    }


def _status_text(status):
    if isinstance(status, dict):
        return status.get("type") or _compact_json(status, 180)
    return str(status or "")


def _extract_text(obj):
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(x for x in (_extract_text(v) for v in obj) if x)
    if isinstance(obj, dict):
        for key in ("text", "summary", "content", "message", "delta", "part"):
            text = _extract_text(obj.get(key))
            if text:
                return text
    return ""


def _extract_proposed_plan(text):
    text = str(text or "")
    start_tag = "<proposed_plan>"
    end_tag = "</proposed_plan>"
    start = text.find(start_tag)
    if start < 0:
        return ""
    end = text.find(end_tag, start + len(start_tag))
    if end < 0:
        return ""
    return text[start + len(start_tag):end].strip()


class AppServerRequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)


def _option_list(spec):
    if not isinstance(spec, dict):
        return []
    raw = spec.get("options")
    if raw is None:
        raw = spec.get("choices")
    opts = []
    if isinstance(raw, list):
        for opt in raw:
            if isinstance(opt, dict):
                value = opt.get("value")
                if value is None:
                    value = opt.get("id") or opt.get("name") or opt.get("const") or opt.get("label") or opt.get("title")
                label = opt.get("label") or opt.get("title") or opt.get("name") or value
                desc = opt.get("description") or opt.get("help") or ""
                if value is not None:
                    opts.append({"value": str(value), "label": str(label), "description": str(desc)})
            elif opt is not None:
                opts.append({"value": str(opt), "label": str(opt), "description": ""})
    enum = spec.get("enum")
    if isinstance(enum, list):
        enum_names = spec.get("enumNames") or []
        for idx, value in enumerate(enum):
            if value is None:
                continue
            label = enum_names[idx] if idx < len(enum_names) and enum_names[idx] else value
            opts.append({"value": str(value), "label": str(label), "description": ""})
    for key in ("oneOf", "anyOf"):
        raw_variants = spec.get(key)
        if isinstance(raw_variants, list):
            for variant in raw_variants:
                if not isinstance(variant, dict):
                    continue
                value = variant.get("const")
                if value is None:
                    venum = variant.get("enum")
                    if isinstance(venum, list) and len(venum) == 1:
                        value = venum[0]
                if value is None:
                    continue
                label = variant.get("title") or variant.get("label") or value
                opts.append({
                    "value": str(value),
                    "label": str(label),
                    "description": str(variant.get("description") or ""),
                })
    if not opts and isinstance(spec.get("items"), dict):
        opts = _option_list(spec.get("items"))
    deduped = []
    seen = set()
    for opt in opts:
        value = opt.get("value")
        if value in seen:
            continue
        seen.add(value)
        deduped.append(opt)
    return deduped


def _schema_type(spec):
    if not isinstance(spec, dict):
        return "string"
    typ = spec.get("type") or spec.get("inputType") or spec.get("input_type") or ""
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), typ[0] if typ else "")
    return str(typ or "string").lower()


def _form_input_type(spec, options):
    typ = _schema_type(spec)
    fmt = str(spec.get("format") or "").lower() if isinstance(spec, dict) else ""
    widget = str(spec.get("widget") or spec.get("component") or "").lower() if isinstance(spec, dict) else ""
    if typ in ("boolean", "checkbox") or widget == "checkbox":
        return "checkbox"
    if typ in ("array", "multi_select", "multiselect") or widget in ("multi_select", "multiselect"):
        return "multiselect" if options else "textarea"
    if options:
        return "select"
    if typ in ("number", "integer"):
        return "number"
    if typ in ("textarea", "long_text") or fmt in ("textarea", "multiline") or widget == "textarea":
        return "textarea"
    return "text"


def _field_from_spec(key, spec, required=False):
    if not isinstance(spec, dict):
        spec = {}
    options = _option_list(spec)
    return {
        "id": str(key),
        "label": str(spec.get("label") or spec.get("title") or spec.get("name") or key),
        "description": str(spec.get("description") or spec.get("help") or ""),
        "type": _form_input_type(spec, options),
        "required": bool(required or spec.get("required")),
        "default": spec.get("default"),
        "options": options,
    }


def _form_fields_from_schema(schema):
    if not isinstance(schema, dict):
        return []
    fields = []
    raw_fields = schema.get("fields") or schema.get("inputs") or schema.get("elements")
    if isinstance(raw_fields, list):
        for idx, spec in enumerate(raw_fields):
            if not isinstance(spec, dict):
                continue
            key = spec.get("id") or spec.get("name") or spec.get("key") or spec.get("path") or ("field_%d" % (idx + 1))
            fields.append(_field_from_spec(key, spec, bool(spec.get("required"))))
        return fields
    props = schema.get("properties")
    if isinstance(props, dict):
        required = set(x for x in (schema.get("required") or []) if isinstance(x, str))
        for key, spec in props.items():
            fields.append(_field_from_spec(key, spec, key in required))
    return fields


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
                "capabilities": {
                    "experimentalApi": True,
                    "mcpServerOpenaiFormElicitation": True,
                    "requestAttestation": False,
                },
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
                return
        if method:
            for session in list(self.sessions.values()):
                try:
                    session.handle_notification(method, params)
                except Exception:
                    pass

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
                for s in list(self.sessions.values()):
                    try:
                        s._codex_notice("Unsupported app-server request", method, params)
                    except Exception:
                        pass
                self.respond_error(req_id, -32601, "unsupported app-server request: %s" % method)
        except AppServerRequestError as e:
            self.respond_error(req_id, e.code, e.message)
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
        self._awaiting_plan_decision = False
        self.last_activity = time.time()

    def start(self):
        res = get_app_client().request("thread/start", self._thread_params(), timeout=30)
        self._apply_thread_response(res)
        self._thread_ready = True
        self._persist()

    def send(self, prompt):
        with self._lock:
            self._awaiting_plan_decision = False
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
        if self._awaiting_plan_decision:
            return "plan"
        if self._busy:
            return "running"
        return "new" if not self.events else "idle"

    def set_modes(self, plan=None, task=None):
        if plan is not None:
            self.plan_mode = bool(plan)
            if not self.plan_mode:
                self._awaiting_plan_decision = False
            self._sync_collaboration_mode()
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
            "collaborationMode": self._collaboration_mode(),
        }
        if self.yolo:
            params["approvalPolicy"] = "never"
            params["sandboxPolicy"] = {"type": "dangerFullAccess"}
        return params

    def _collaboration_mode(self):
        return {
            "mode": "plan" if self.plan_mode else "default",
            "settings": {
                "model": self.model or "",
                "reasoning_effort": None,
                "developer_instructions": None,
            },
        }

    def _sync_collaboration_mode(self):
        if not self.thread_id:
            return
        try:
            get_app_client().request(
                "thread/settings/update",
                {"threadId": self.thread_id, "collaborationMode": self._collaboration_mode()},
                timeout=15,
            )
        except Exception as e:
            self._codex_notice(
                "Failed to update Codex Plan mode",
                "thread/settings/update",
                {"mode": "plan" if self.plan_mode else "default", "error": str(e)},
            )

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
            self._sync_collaboration_mode()
            res = get_app_client().request("turn/start", self._turn_params(prompt), timeout=30)
            turn = (res or {}).get("turn") or {}
            self.last_turn_id = turn.get("id") or self.last_turn_id
            self._persist()
        except Exception as e:
            self._busy = False
            self._record_and_broadcast({"type": "result", "error": "Codex turn failed: %s" % e})
            self._persist()

    def _codex_notice(self, message, method=None, params=None):
        ev = {"type": "codex_notice", "message": message}
        if method:
            ev["method"] = method
        if params is not None:
            ev["detail"] = _compact_json(params)
        self._broadcast(ev)

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
            self._broadcast({"type": "turn_started", "provider": "codex", "turn_id": self.last_turn_id})
            self._persist()
        elif method == "turn/completed":
            self._on_turn_completed(params.get("turn") or {})
        elif method == "thread/status/changed":
            status = params.get("status")
            if status == "idle" or (isinstance(status, dict) and status.get("type") == "idle"):
                self._busy = False
        elif method == "thread/settings/updated":
            self._on_thread_settings_updated(params.get("threadSettings") or {})
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
        elif method == "item/reasoning/summaryPartAdded":
            text = _extract_text(params)
            if text:
                self._broadcast({"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": text}}})
        elif method == "item/commandExecution/terminalInteraction":
            self._codex_notice("Command requires terminal interaction; continue in CLI if input is required.", method, params)
        elif method == "item/fileChange/outputDelta":
            self._append_tool_output(params.get("itemId"), params.get("delta") or _extract_text(params) or "")
        elif method == "item/plan/delta":
            text = params.get("delta") or _extract_text(params)
            if text:
                self._broadcast({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": text}}})
        elif method == "model/rerouted":
            self._codex_notice("Model rerouted", method, params)
        elif method == "model/safetyBuffering/updated":
            self._codex_notice("Safety buffering state updated", method, params)
        elif method == "account/rateLimits/updated":
            self._codex_notice("Rate limits updated", method, params)
        elif method == "mcpServer/startupStatus/updated":
            self._codex_notice("MCP server startup status updated", method, params)
        elif method == "turn/moderationMetadata":
            self._codex_notice("Moderation metadata updated", method, params)
        elif method == "error":
            self._record_and_broadcast({"type": "result", "error": params.get("message") or _json_text(params)})
        else:
            self._codex_notice("Unhandled Codex event: " + method, method, params)

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
                with self._lock:
                    webhook_body = common.notify_result_text(self.events)
                self._push("done", "Codex done - " + os.path.basename(self.cwd), self.cwd,
                           webhook_body=webhook_body or (self.cwd + " - done without final text"))
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
                if _extract_proposed_plan(text):
                    self._awaiting_plan_decision = True
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
        status_map = {"inProgress": "in_progress", "completed": "completed", "pending": "pending"}
        todos = [
            {"content": p.get("step") or "", "status": status_map.get(p.get("status"), p.get("status") or "pending")}
            for p in plan
            if isinstance(p, dict)
        ]
        if todos:
            self._record_and_broadcast({
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "id": "codex-plan", "name": "TodoWrite", "input": {"todos": todos}}]},
            })

    def _on_thread_settings_updated(self, settings):
        if not isinstance(settings, dict):
            return
        self.model = settings.get("model") or self.model
        self.model_provider = settings.get("modelProvider") or self.model_provider
        self.service_tier = settings.get("serviceTier") or self.service_tier
        mode = (((settings.get("collaborationMode") or {}).get("mode")) or "").lower()
        if mode in ("plan", "default"):
            new_plan = mode == "plan"
            if self.plan_mode != new_plan:
                self.plan_mode = new_plan
                if not new_plan:
                    self._awaiting_plan_decision = False
                self._broadcast({"type": "mode_state", "plan": self.plan_mode, "task": self.task_mode})

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

    @classmethod
    def history_snapshot(cls, thread_id):
        res = get_app_client().request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
            timeout=30,
        )
        thread = (res or {}).get("thread") or {}
        cwd = thread.get("cwd") or os.path.expanduser("~")
        dummy = cls("__history__", cwd, yolo=False)
        events = []
        if thread.get("cliVersion") or thread.get("modelProvider"):
            events.append({
                "type": "system",
                "model": thread.get("model") or thread.get("modelProvider") or "Codex",
                "version": thread.get("cliVersion"),
            })
        for turn in thread.get("turns") or []:
            before = len(events)
            for item in turn.get("items") or []:
                typ = item.get("type")
                if typ == "userMessage":
                    txt = _text_from_user_input(item.get("content") or [])
                    if txt:
                        events.append({"type": "user", "message": {"role": "user", "content": txt}})
                elif typ == "agentMessage":
                    txt = item.get("text") or ""
                    if txt:
                        events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}})
                elif typ == "reasoning":
                    txt = "\n".join((item.get("summary") or []) + (item.get("content") or []))
                    if txt:
                        events.append({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": txt}]}})
                else:
                    ev = dummy._tool_event_from_item(item)
                    if ev:
                        events.append(ev)
                    result = dummy._tool_result_from_item(item)
                    if result:
                        events.append(result)
            if len(events) > before:
                result_ev = {"type": "result", "duration_ms": turn.get("durationMs")}
                if turn.get("status") == "failed" or turn.get("error"):
                    result_ev["error"] = _compact_json(turn.get("error") or "Codex turn failed")
                    result_ev["is_error"] = True
                events.append(result_ev)
        return {
            "thread": thread,
            "events": events[-200:],
            "cwd": cwd,
            "title": _thread_title(thread),
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
        elif typ in ("agentMessage", "reasoning", "userMessage"):
            # These are first-class chat/reasoning items. Text/reasoning deltas and
            # completed items render them; exposing item/started as a tool card is noise.
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
            if params.get("mode") in ("form", "openai/form"):
                return self._await_form_input(req_id, method, params)
            return self._await_user_input(req_id, method, params)
        if method == "item/tool/call":
            return self._reject_dynamic_tool_call(req_id, method, params)
        if method == "attestation/generate":
            self._codex_notice(
                "Codex requested client attestation; Agents Cockpit cannot generate it yet.",
                method,
                params,
            )
            raise AppServerRequestError(-32601, "client attestation is not supported by Agents Cockpit")
        if method == "account/chatgptAuthTokens/refresh":
            self._codex_notice(
                "Codex requested ChatGPT auth token refresh; refresh the login in Codex CLI.",
                method,
                params,
            )
            raise AppServerRequestError(-32601, "ChatGPT auth token refresh is not supported by Agents Cockpit")
        if method == "currentTime/read":
            return {"utcTimestampMs": int(time.time() * 1000)}
        self._codex_notice("Unsupported app-server request: " + str(method or "unknown"), method, params)
        raise AppServerRequestError(-32601, "unsupported app-server request: %s" % method)

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
        questions = _clean_questions(params.get("questions") or [])
        fallback = params.get("message") or params.get("prompt") or _json_text(params)
        question_text = _question_text(questions, fallback)
        entry = {"event": threading.Event(), "kind": "ask", "method": method, "params": params, "answer": ""}
        with self._pending_lock:
            self._pending[req_id] = entry
        ev = {
            "type": "pending_ask",
            "tool_use_id": req_id,
            "question": question_text,
            "questions": questions,
        }
        if params.get("autoResolutionMs") is not None:
            ev["auto_resolution_ms"] = params.get("autoResolutionMs")
        self._broadcast(ev)
        self._push("confirm", "Codex waits for input - " + os.path.basename(self.cwd), question_text)
        timeout = 600
        try:
            if params.get("autoResolutionMs"):
                timeout = max(1, min(timeout, float(params.get("autoResolutionMs")) / 1000.0))
        except (TypeError, ValueError):
            pass
        entry["event"].wait(timeout=timeout)
        with self._pending_lock:
            self._pending.pop(req_id, None)
        ans = entry.get("answer") or ""
        if method == "item/tool/requestUserInput":
            return {"answers": _answers_for_questions(questions, ans)}
        if isinstance(ans, dict):
            content = {}
            for key, value in ans.items():
                values = _answer_list(value)
                if values:
                    content[key] = values[0] if len(values) == 1 else values
            return {"action": "accept" if content else "decline", "content": content or None}
        return {"action": "accept" if ans else "decline", "content": {"answer": ans} if ans else None}

    def _await_form_input(self, req_id, method, params):
        schema = params.get("requestedSchema")
        fields = _form_fields_from_schema(schema)
        msg = params.get("message") or "Codex requests form input"
        entry = {"event": threading.Event(), "kind": "form", "method": method, "params": params, "answer": None}
        with self._pending_lock:
            self._pending[req_id] = entry
        self._broadcast({
            "type": "pending_form",
            "tool_use_id": req_id,
            "message": msg,
            "mode": params.get("mode") or "form",
            "server_name": params.get("serverName") or "",
            "fields": fields,
            "schema_detail": _compact_json(schema, 2500) if schema is not None else "",
        })
        self._push("confirm", "Codex waits for form input - " + os.path.basename(self.cwd), msg)
        entry["event"].wait(timeout=600)
        with self._pending_lock:
            self._pending.pop(req_id, None)
        ans = entry.get("answer")
        if not isinstance(ans, dict):
            return {"action": "decline", "content": None}
        action = ans.get("action") or ("accept" if ans.get("content") else "decline")
        if action not in ("accept", "decline", "cancel"):
            action = "accept"
        content = ans.get("content") if action == "accept" else None
        return {"action": action, "content": content}

    def _reject_dynamic_tool_call(self, req_id, method, params):
        tool = params.get("tool") or "tool"
        namespace = params.get("namespace") or "dynamic"
        call_id = params.get("callId") or req_id
        name = ("%s.%s" % (namespace, tool)) if namespace else str(tool)
        args = params.get("arguments")
        self._record_and_broadcast({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": args or {}}]},
        })
        msg = (
            "Agents Cockpit cannot execute Codex dynamic tool calls yet. "
            "Continue in Codex CLI or wire this tool through an MCP passthrough."
        )
        self._record_and_broadcast({
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": msg}]},
        })
        self._codex_notice("Dynamic tool call was rejected by the Web adapter", method, params)
        return {"success": False, "contentItems": [{"type": "inputText", "text": msg}]}

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
        if not entry or entry.get("kind") not in ("ask", "form"):
            return False
        entry["answer"] = ans if ans is not None else ""
        entry["event"].set()
        if entry.get("kind") == "form":
            self._broadcast({"type": "form_answered", "tool_use_id": tool_use_id})
        else:
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

    def _push(self, event, title, body, webhook_body=None):
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


def list_thread_history(limit=60, archived=False, search=None):
    if not common.CODEX_BIN:
        return []
    params = {
        "limit": max(1, int(limit or 60)),
        "archived": bool(archived),
        "sortKey": "recency_at",
        "sortDirection": "desc",
    }
    if search:
        params["searchTerm"] = search
    res = get_app_client().request("thread/list", params, timeout=30)
    data = (res or {}).get("data") or (res or {}).get("threads") or []
    out = []
    for thread in data:
        item = _thread_history_item(thread, archived=archived)
        if item:
            out.append(item)
    return out


def delete_thread(thread_id):
    if not thread_id:
        return False
    get_app_client().request("thread/delete", {"threadId": thread_id}, timeout=30)
    return True
