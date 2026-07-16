# -*- coding: utf-8 -*-
"""Codex app-server backed structured sessions for Agents Cockpit.

This adapter keeps the browser-facing event shape close to native.py's Claude
stream-json events, while speaking Codex app-server JSONL/JSON-RPC on the
backend.
"""
import atexit
import json
import os
import threading
import time

from codex_client import AppServerRequestError, CodexAppServerClient
import codex_events
import codex_forms
import codex_history
import codex_replay
import codex_requests
import codex_routing
import codex_session_events
import codex_text
import codex_thread_history
import common
from common import ws_send, ws_recv, STATE_DIR


_CLIENT_LOCK = threading.Lock()
_CLIENTS = {}

_TASK_SYSTEM = (
    "Task mode: for multi-step work, keep a concise todo list and update it as "
    "you make progress so the user can follow the task state."
)

_REPLAY_MAX_EVENTS = 400
_REPLAY_STREAM_MAX_CHARS = 24000


def _push_notify_worker(title, body, event, webhook_body=None):
    try:
        common.push_notify(title, body, event, webhook_body=webhook_body)
    except Exception:
        pass


def _text_from_user_input(items):
    return codex_text.text_from_user_input(items)


def _clean_questions(questions):
    return codex_text.clean_questions(questions)


def _question_text(questions, fallback=""):
    return codex_text.question_text(questions, fallback=fallback)


def _answer_list(value):
    return codex_text.answer_list(value)


def _answers_for_questions(questions, answer):
    return codex_text.answers_for_questions(questions, answer)


def _json_text(obj):
    return codex_text.json_text(obj)


def _compact_json(obj, limit=900):
    return codex_text.compact_json(obj, limit=limit)


def _changes_to_diff(changes):
    return codex_text.changes_to_diff(changes)


def _epoch(value):
    return codex_history.epoch(value)


def _thread_id(thread):
    return codex_history.thread_id(thread)


def _thread_title(thread):
    return codex_history.thread_title(thread)


def _thread_history_item(thread, archived=False):
    return codex_history.thread_history_item(thread, archived=archived)


def _history_cache_path(state_dir=None):
    return codex_history.history_cache_path(state_dir, STATE_DIR)


def _local_thread_history_items(state_dir=None):
    return codex_history.local_thread_history_items(state_dir=state_dir, default_state_dir=STATE_DIR)


def _filter_thread_history_items(items, limit=60, search=None):
    return codex_history.filter_thread_history_items(items, limit=limit, search=search)


def _read_thread_history_cache(limit=60, archived=False, search=None, state_dir=None):
    return codex_history.read_thread_history_cache(
        limit=limit, archived=archived, search=search, state_dir=state_dir, default_state_dir=STATE_DIR)


def _write_thread_history_cache(items, state_dir=None):
    return codex_history.write_thread_history_cache(items, state_dir=state_dir, default_state_dir=STATE_DIR)


def _status_text(status):
    return codex_text.status_text(status)


def _extract_text(obj):
    return codex_text.extract_text(obj)


def _extract_proposed_plan(text):
    return codex_text.extract_proposed_plan(text)


def _as_proposed_plan(text):
    return codex_text.as_proposed_plan(text)


def _plan_text_event(text):
    return codex_text.plan_text_event(text)


def _option_list(spec):
    return codex_forms.option_list(spec)


def _schema_type(spec):
    return codex_forms.schema_type(spec)


def _form_input_type(spec, options):
    return codex_forms.form_input_type(spec, options)


def _field_from_spec(key, spec, required=False):
    return codex_forms.field_from_spec(key, spec, required=required)


def _form_fields_from_schema(schema):
    return codex_forms.form_fields_from_schema(schema)


def _client_key(user="", uid="", state_dir=None):
    return uid or (common.safe_user_id(user) if user else None) or os.path.abspath(state_dir or common.STATE_DIR)


def get_app_client(user="", uid="", state_dir=None, codex_home=None):
    key = _client_key(user, uid, state_dir)
    with _CLIENT_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = CodexAppServerClient(user=user, uid=uid or key, state_dir=state_dir, codex_home=codex_home)
            _CLIENTS[key] = client
        return client


def shutdown_app_server(user=None, uid=None, state_dir=None):
    with _CLIENT_LOCK:
        if user or uid or state_dir:
            key = _client_key(user or "", uid or "", state_dir)
            client = _CLIENTS.pop(key, None)
            if client is not None:
                client.shutdown()
            return
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        client.shutdown()


atexit.register(shutdown_app_server)


class CodexSession:
    provider = "codex"

    def __init__(self, sid, cwd, yolo=False, cfg=None, user="", uid="", state_dir=None, codex_home=None):
        self.sid = sid
        self.cwd = os.path.abspath(cwd)
        self.yolo = bool(yolo)
        self.user = user or ""
        self.uid = uid or ""
        self.state_dir = state_dir or STATE_DIR
        self.codex_home = codex_home
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.events = []
        self.thread_id = None
        self.last_turn_id = None
        self.current_turn_started_at = None
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
        self._plan_output = {}
        self._codex_debug_notices = []
        self._route_debug = []
        self.timeline = []
        self.poll_events = []
        self._next_seq = 1
        self._last_usage = None
        self.plan_mode = False
        self.task_mode = False
        self._awaiting_plan_decision = False
        self.last_activity = time.time()
        self._last_persist = 0.0

    def _client(self):
        return get_app_client(user=self.user, uid=self.uid, state_dir=self.state_dir, codex_home=self.codex_home)

    def start(self):
        res = self._client().request("thread/start", self._thread_params(), timeout=30)
        self._apply_thread_response(res)
        self._thread_ready = True
        self._persist()

    def send(self, prompt):
        with self._lock:
            self._awaiting_plan_decision = False
        self.last_activity = time.time()
        self._busy = True
        self.current_turn_started_at = self.last_activity
        self._record_and_broadcast({"type": "user", "message": {"role": "user", "content": prompt}})
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
            self._client().unregister(self)
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
            self._client().request(
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
            self._client().request(
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
        new_thread_id = thread.get("id") or thread.get("sessionId")
        if self.thread_id and new_thread_id and new_thread_id != self.thread_id:
            self._codex_notice(
                "Ignored Codex thread update for a different thread",
                "thread/started",
                {"currentThreadId": self.thread_id, "incomingThreadId": new_thread_id},
                level="debug",
                silent=True,
            )
            return
        self.thread_id = new_thread_id or self.thread_id
        self.model = res.get("model") or self.model
        self.model_provider = res.get("modelProvider") or self.model_provider
        self.service_tier = res.get("serviceTier") or self.service_tier
        if self.thread_id:
            self._client().register(self.thread_id, self)
        if self.model:
            self._record_and_broadcast({"type": "system", "model": self.model, "version": thread.get("cliVersion")})

    def _ensure_thread(self):
        client = self._client()
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
        if not self.current_turn_started_at:
            self.current_turn_started_at = time.time()
        self.last_activity = time.time()
        try:
            self._ensure_thread()
            self._sync_collaboration_mode()
            res = self._client().request("turn/start", self._turn_params(prompt), timeout=30)
            turn = (res or {}).get("turn") or {}
            self.last_turn_id = turn.get("id") or self.last_turn_id
            if self.last_turn_id:
                self._client().register_turn(self.last_turn_id, self)
            self._persist()
        except Exception as e:
            self._busy = False
            self.current_turn_started_at = None
            self._record_and_broadcast({"type": "result", "error": "Codex turn failed: %s" % e})
            self._persist()

    def _remember_codex_debug_notice(self, message, method=None, params=None):
        return codex_session_events.remember_codex_debug_notice(self, message, method=method, params=params)

    def _remember_route_debug(self, message, method=None, params=None):
        return codex_session_events.remember_route_debug(self, message, method=method, params=params)

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        return codex_session_events.codex_notice(
            self, message, method=method, params=params, level=level, silent=silent)

    def _updated_event_notice_message(self, params):
        return codex_session_events.updated_event_notice_message(params)

    def _handle_updated_event(self, method, params):
        return codex_session_events.handle_updated_event(self, method, params)

    def handle_notification(self, method, params):
        return codex_session_events.handle_notification(self, method, params)

    def _on_turn_completed(self, turn):
        return codex_session_events.on_turn_completed(self, turn)

    def _on_item_started(self, item):
        return codex_session_events.on_item_started(self, item)

    def _on_item_completed(self, item):
        return codex_session_events.on_item_completed(self, item)

    def _flush_pending_plan_items(self):
        return codex_session_events.flush_pending_plan_items(self)

    def _on_plan_updated(self, params):
        return codex_session_events.on_plan_updated(self, params)

    def _on_thread_settings_updated(self, settings):
        return codex_session_events.on_thread_settings_updated(self, settings)

    @staticmethod
    def _usage_for_meta(usage):
        return codex_session_events.usage_for_meta(usage)

    @classmethod
    def history_snapshot(cls, thread_id, user="", uid="", state_dir=None, codex_home=None):
        return codex_thread_history.history_snapshot(
            thread_id, user=user, uid=uid, state_dir=state_dir,
            codex_home=codex_home, get_client_fn=get_app_client)

    def _tool_event_from_item(self, item):
        return codex_events.tool_event_from_item(item, cwd=self.cwd)

    def _tool_result_from_item(self, item):
        return codex_events.tool_result_from_item(item)

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
        return codex_requests.handle_server_request(
            self, req_id, method, params, AppServerRequestError)

    def _await_approval(self, req_id, method, params, name, preview):
        return codex_requests.await_approval(self, req_id, method, params, name, preview)

    def _await_user_input(self, req_id, method, params):
        return codex_requests.await_user_input(self, req_id, method, params)

    def _await_form_input(self, req_id, method, params):
        return codex_requests.await_form_input(self, req_id, method, params)

    def _reject_dynamic_tool_call(self, req_id, method, params):
        return codex_requests.reject_dynamic_tool_call(self, req_id, method, params)

    def _approval_response(self, method, allow, always, params):
        return codex_requests.approval_response(method, allow, always, params)

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
        return codex_replay.is_dangerous(text)

    def _record_and_broadcast(self, obj):
        with self._lock:
            if obj.get("type") in ("assistant", "user", "result", "system", "compacted"):
                self.events.append(obj)
                if len(self.events) > 200:
                    self.events = self.events[-200:]
        self._broadcast(obj)

    def _event_identity_locked(self, obj):
        return codex_replay.event_identity(self, obj)

    def _record_timeline_locked(self, obj):
        return codex_replay.record_timeline(
            self, obj, _REPLAY_MAX_EVENTS, _REPLAY_STREAM_MAX_CHARS)

    def _merge_timeline_event_locked(self, out):
        return codex_replay.merge_timeline_event(self, out, _REPLAY_STREAM_MAX_CHARS)

    @staticmethod
    def _tool_result_id(ev):
        return codex_replay.tool_result_id(ev)

    @staticmethod
    def _replay_content_score(events):
        return codex_replay.replay_content_score(events)

    @staticmethod
    def _drop_recover_noise(events):
        return codex_replay.drop_recover_noise(events)

    def _adopt_history_replay(self, events):
        return codex_replay.adopt_history_replay(self, events, _REPLAY_MAX_EVENTS)

    def _decorate_for_broadcast(self, obj):
        with self._lock:
            return self._record_timeline_locked(obj)

    def _broadcast(self, obj):
        obj = self._decorate_for_broadcast(obj)
        if obj.get("type") not in ("replay_batch", "state_snapshot", "codex_usage"):
            with self._lock:
                self.poll_events.append(dict(obj))
                if len(self.poll_events) > _REPLAY_MAX_EVENTS:
                    self.poll_events = self.poll_events[-_REPLAY_MAX_EVENTS:]
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
        self._persist_if_due(obj)

    def _persist_if_due(self, obj):
        typ = obj.get("type") if isinstance(obj, dict) else ""
        now = time.time()
        important = typ in ("assistant", "user", "result", "pending_approval", "pending_ask", "pending_form", "interrupted")
        if important or now - self._last_persist >= 1.5:
            self._last_persist = now
            self._persist()

    def _send_one(self, sock, obj):
        try:
            ws_send(sock, json.dumps(obj, ensure_ascii=False).encode("utf-8"), 0x1)
        except OSError:
            with self.clients_lock:
                self.clients.discard(sock)

    @staticmethod
    def _event_after_seq(ev, after_seq):
        return codex_replay.event_after_seq(ev, after_seq)

    def _events_after_seq(self, after_seq=0):
        return codex_replay.events_after_seq(self, after_seq)

    def replay_payload(self, after_seq=0):
        return codex_replay.replay_payload(self, after_seq)

    def add_client(self, sock, after_seq=0):
        snapshot = self._events_after_seq(after_seq)
        if snapshot:
            self._send_one(sock, {"type": "replay_batch", "events": snapshot})
        self._send_one(sock, self._state_snapshot())
        for ev in self._pending_events_snapshot():
            self._send_one(sock, ev)
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

    def _state_snapshot(self):
        with self._pending_lock:
            pending = list(self._pending.items())
        return codex_replay.state_snapshot(self, pending)

    def _pending_events_snapshot(self):
        with self._pending_lock:
            pending = list(self._pending.items())
        return codex_replay.pending_events_snapshot(pending)

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
        was_busy = bool(self._busy)
        with self._pending_lock:
            had_pending = bool(self._pending)
            for entry in self._pending.values():
                try:
                    entry["event"].set()
                except Exception:
                    pass
            self._pending.clear()
        self._busy = False
        self.current_turn_started_at = None
        self._thread_ready = False
        if not self._closed and (was_busy or had_pending):
            self._broadcast({"type": "result", "error": "Codex app-server exited. It will be restarted on the next send."})

    def _state_path(self):
        return os.path.join(self.state_dir, "codex_%s.json" % self.sid)

    def _persist(self):
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(self._state_path(), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "thread_id": self.thread_id,
                        "last_turn_id": self.last_turn_id,
                        "cwd": self.cwd,
                        "yolo": self.yolo,
                        "user": self.user, "uid": self.uid,
                        "codex_home": self.codex_home,
                        "model": self.model,
                        "model_provider": self.model_provider,
                        "service_tier": self.service_tier,
                        "events": self.events[-50:],
                        "timeline": self.timeline[-_REPLAY_MAX_EVENTS:],
                        "next_seq": self._next_seq,
                    },
                    f,
                    ensure_ascii=False,
                )
        except OSError:
            pass

    @classmethod
    def recover(cls, sid, cwd, expected_thread_id=None, user="", uid="", state_dir=None, codex_home=None):
        state_dir = state_dir or STATE_DIR
        try:
            with open(os.path.join(state_dir, "codex_%s.json" % sid), "r", encoding="utf-8") as f:
                data = json.load(f)
            ns = cls(sid, data.get("cwd") or cwd, yolo=bool(data.get("yolo")),
                     user=user or data.get("user", ""), uid=uid or data.get("uid", ""),
                     state_dir=state_dir,
                     codex_home=codex_home or data.get("codex_home"))
            ns.thread_id = expected_thread_id or data.get("thread_id")
            ns.last_turn_id = data.get("last_turn_id")
            ns.model = data.get("model") or ""
            ns.model_provider = data.get("model_provider") or ""
            ns.service_tier = data.get("service_tier") or ""
            ns.events = cls._drop_recover_noise(data.get("events") or [])
            ns.timeline = cls._drop_recover_noise(data.get("timeline") or list(ns.events))
            try:
                ns._next_seq = max([int(e.get("seq") or 0) for e in ns.timeline] + [int(data.get("next_seq") or 1) - 1]) + 1
            except Exception:
                ns._next_seq = int(data.get("next_seq") or 1)
            if ns.thread_id:
                # Startup recovery must stay local-only; thread/read starts the
                # Codex app-server and can stall the whole manager on boot.
                ns._client().register(ns.thread_id, ns)
            return ns
        except (OSError, ValueError):
            return None


def list_thread_history(limit=60, archived=False, search=None, user="", uid="", state_dir=None, codex_home=None, live=True):
    return codex_thread_history.list_thread_history(
        limit=limit, archived=archived, search=search, user=user, uid=uid,
        state_dir=state_dir, codex_home=codex_home, live=live,
        codex_enabled=bool(common.CODEX_BIN), get_client_fn=get_app_client,
        default_state_dir=STATE_DIR)


def delete_thread(thread_id, user="", uid="", state_dir=None, codex_home=None):
    return codex_thread_history.delete_thread(
        thread_id, user=user, uid=uid, state_dir=state_dir,
        codex_home=codex_home, get_client_fn=get_app_client)
