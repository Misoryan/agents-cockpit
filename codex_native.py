# -*- coding: utf-8 -*-
"""Codex app-server backed structured sessions for Agents Cockpit.

This adapter keeps the browser-facing event shape close to native.py's Claude
stream-json events, while speaking Codex app-server JSONL/JSON-RPC on the
backend.
"""
import atexit
import os
import threading
import time

from codex_client import AppServerRequestError, CodexAppServerClient
import codex_broadcast
import codex_config
import codex_forms
import codex_history
import codex_input
import codex_notifications
import codex_pending
import codex_replay_facade
import codex_requests
import codex_routing
import codex_slash
import codex_state
import codex_terminal
import codex_text
import codex_thread_history
import codex_turn
import common
from common import ws_send, ws_recv, STATE_DIR


_CLIENT_LOCK = threading.Lock()
_CLIENTS = {}

_REPLAY_MAX_EVENTS = 400
_REPLAY_STREAM_MAX_CHARS = 24000


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
        self.cfg = codex_config.normalize_launch_config(cfg, cwd=self.cwd)
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
        self._terminal_processes = {}
        self._codex_debug_notices = []
        self._route_debug = []
        self.timeline = []
        self.poll_events = []
        self._replay = codex_replay_facade.CodexReplayFacade(
            self, _REPLAY_MAX_EVENTS, _REPLAY_STREAM_MAX_CHARS)
        self._state = codex_state.CodexSessionState(self, _REPLAY_MAX_EVENTS)
        self._notifications = codex_notifications.CodexNotificationAdapter(self)
        self._turn = codex_turn.CodexTurnRunner(self)
        self._input = codex_input.CodexInputAdapter(self)
        self._slash = codex_slash.CodexSlashAdapter(self)
        self._requests = codex_requests.CodexRequestAdapter(
            self, AppServerRequestError, common.codex_dynamic_tool_mappings)
        self._broadcast_adapter = codex_broadcast.CodexBroadcastAdapter(self, ws_send, common)
        self._next_seq = 1
        self._last_usage = None
        self.plan_mode = False
        self.task_mode = False
        self._awaiting_plan_decision = False
        self._compact_in_progress = False
        self.last_activity = time.time()
        self._last_persist = 0.0

    def _client(self):
        return get_app_client(user=self.user, uid=self.uid, state_dir=self.state_dir, codex_home=self.codex_home)

    def start(self):
        res = self._client().request("thread/start", self._thread_params(), timeout=30)
        self._apply_thread_response(res)
        self._thread_ready = True
        self._persist()

    def send(self, prompt, image_inputs=None):
        image_inputs = list(image_inputs or [])
        with self._lock:
            self._awaiting_plan_decision = False
        self.last_activity = time.time()
        self._busy = True
        self.current_turn_started_at = self.last_activity
        self._record_and_broadcast({
            "type": "user",
            "message": {"role": "user", "content": self._display_user_content(prompt, image_inputs)},
        })
        threading.Thread(target=self._run_turn, args=(prompt, image_inputs), daemon=True).start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.alive = False
        codex_pending.clear_pending(self)
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
        if codex_pending.has_pending(self):
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

    def handle_slash_command(self, command):
        return self._slash.handle_slash_command(command)

    def set_model(self, model):
        return self._slash.set_model(model)

    def set_approval_policy(self, policy):
        return self._slash.set_approval_policy(policy)

    def set_sandbox_mode(self, mode):
        return self._slash.set_sandbox_mode(mode)

    def set_web_search(self, mode):
        return self._slash.set_web_search(mode)

    def set_reasoning_effort(self, effort):
        return self._slash.set_reasoning_effort(effort)

    def set_reasoning_summary(self, summary):
        return self._slash.set_reasoning_summary(summary)

    def set_service_tier(self, tier):
        return self._slash.set_service_tier(tier)

    def set_writable_roots(self, roots_text):
        return self._slash.set_writable_roots(roots_text)

    def start_compaction(self):
        return self._slash.start_compaction()

    def rename_thread(self, name):
        return self._slash.rename_thread(name)

    def archive_thread(self):
        return self._slash.archive_thread()

    def unarchive_thread(self):
        return self._slash.unarchive_thread()

    def fork_thread(self):
        return self._slash.fork_thread()

    def rollback_thread(self, count_text):
        return self._slash.rollback_thread(count_text)

    def steer_turn(self, prompt):
        return self._slash.steer_turn(prompt)

    def goal_command(self, arg):
        return self._slash.goal_command(arg)

    def _ensure_goal_thread(self):
        return self._slash._ensure_goal_thread()

    def _goal_from_response(self, response):
        return self._slash._goal_from_response(response)

    def _goal_summary(self, goal):
        return self._slash._goal_summary(goal)

    def get_goal(self):
        return self._slash.get_goal()

    def set_goal(self, objective):
        return self._slash.set_goal(objective)

    def set_goal_status(self, status):
        return self._slash.set_goal_status(status)

    def clear_goal(self):
        return self._slash.clear_goal()

    def _split_words(self, text, expected=0):
        return self._slash._split_words(text, expected=expected)

    def _mcp_result_events(self, call_id, name, input_obj, result, method):
        return self._slash._mcp_result_events(call_id, name, input_obj, result, method)

    def read_mcp_resource(self, arg):
        return self._slash.read_mcp_resource(arg)

    def call_mcp_tool(self, arg):
        return self._slash.call_mcp_tool(arg)

    def _path_within_cwd(self, path):
        return self._input.path_within_cwd(path)

    def _resolve_mention_path(self, raw_path):
        return self._input.resolve_mention_path(raw_path)

    def _image_upload_dir(self):
        return self._input.image_upload_dir()

    def image_file(self, image_id):
        return self._input.image_file(image_id)

    def prepare_image_inputs(self, images):
        return self._input.prepare_image_inputs(images)

    def _display_user_content(self, text, image_inputs=None):
        return self._input.display_user_content(text, image_inputs=image_inputs)

    def _user_input_items(self, text, image_inputs=None):
        return self._input.user_input_items(text, image_inputs=image_inputs)

    def _search_file_result(self, item):
        return self._input.search_file_result(item)

    def search_files(self, query, limit=20):
        return self._input.search_files(query, limit=limit)

    def terminal_interaction_event(self, params):
        return codex_terminal.terminal_interaction_event(self, params)

    def _terminal_known(self, process_id):
        return codex_terminal.terminal_known(self, process_id)

    def terminal_write(self, process_id, text="", close_stdin=False):
        return codex_terminal.terminal_write(self, process_id, text=text, close_stdin=close_stdin)

    def terminal_terminate(self, process_id):
        return codex_terminal.terminal_terminate(self, process_id)

    def terminal_resize(self, process_id, cols, rows):
        return codex_terminal.terminal_resize(self, process_id, cols, rows)

    def _broadcast_transient(self, obj):
        return self._broadcast_adapter.broadcast_transient(obj)

    def _replace_history_from_thread(self, thread):
        events = codex_thread_history.events_from_thread(thread)
        with self._lock:
            self.events = list(events)[-200:]
            self.timeline = []
            self.poll_events = []
            self._next_seq = 1
            for event in events[-_REPLAY_MAX_EVENTS:]:
                self._record_timeline_locked(dict(event))
        snapshot = self._events_after_seq(0)
        self._broadcast_transient({"type": "replay_replace", "events": snapshot})
        self._broadcast_transient(self._state_snapshot())

    def _thread_params(self):
        return self._turn.thread_params()

    def _turn_params(self, prompt, image_inputs=None):
        return self._turn.turn_params(prompt, image_inputs=image_inputs)

    def _collaboration_mode(self):
        return self._turn.collaboration_mode()

    def _sync_collaboration_mode(self):
        return self._turn.sync_collaboration_mode()

    def _apply_thread_response(self, res):
        return self._turn.apply_thread_response(res)

    def _ensure_thread(self):
        return self._turn.ensure_thread()

    def _run_turn(self, prompt, image_inputs=None):
        return self._turn.run_turn(prompt, image_inputs=image_inputs)

    def _remember_codex_debug_notice(self, message, method=None, params=None):
        return self._notifications.remember_codex_debug_notice(message, method=method, params=params)

    def _remember_route_debug(self, message, method=None, params=None):
        return self._notifications.remember_route_debug(message, method=method, params=params)

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        return self._notifications.codex_notice(
            message, method=method, params=params, level=level, silent=silent)

    def _updated_event_notice_message(self, params):
        return codex_notifications.CodexNotificationAdapter.updated_event_notice_message(params)

    def _handle_updated_event(self, method, params):
        return self._notifications.handle_updated_event(method, params)

    def handle_notification(self, method, params):
        return self._notifications.handle_notification(method, params)

    def _on_turn_completed(self, turn):
        return self._notifications.on_turn_completed(turn)

    def _on_item_started(self, item):
        return self._notifications.on_item_started(item)

    def _on_item_completed(self, item):
        return self._notifications.on_item_completed(item)

    def _flush_pending_plan_items(self):
        return self._notifications.flush_pending_plan_items()

    def _on_plan_updated(self, params):
        return self._notifications.on_plan_updated(params)

    def _on_thread_settings_updated(self, settings):
        return self._notifications.on_thread_settings_updated(settings)

    @staticmethod
    def _usage_for_meta(usage):
        return codex_notifications.CodexNotificationAdapter.usage_for_meta(usage)

    @classmethod
    def history_snapshot(cls, thread_id, user="", uid="", state_dir=None, codex_home=None):
        return codex_thread_history.history_snapshot(
            thread_id, user=user, uid=uid, state_dir=state_dir,
            codex_home=codex_home, get_client_fn=get_app_client)

    @staticmethod
    def launch_options(cwd="", user="", uid="", state_dir=None, codex_home=None):
        client = get_app_client(user=user, uid=uid, state_dir=state_dir, codex_home=codex_home)
        return codex_config.load_launch_options(client, cwd=cwd)

    @staticmethod
    def history_action(thread_id, action, name="", objective="", status="", user="", uid="",
                       state_dir=None, codex_home=None):
        thread_id = str(thread_id or "").strip()
        action = str(action or "").strip().lower()
        if not thread_id:
            return {"ok": False, "error": "missing thread_id"}
        client = get_app_client(user=user, uid=uid, state_dir=state_dir, codex_home=codex_home)
        if action == "fork":
            res = client.request("thread/fork", {"threadId": thread_id}, timeout=30) or {}
            thread = res.get("thread") or res.get("forkedThread") or res
            fork_id = (thread or {}).get("id") if isinstance(thread, dict) else ""
            fork_id = fork_id or ((thread or {}).get("sessionId") if isinstance(thread, dict) else "")
            return {"ok": True, "action": action, "thread_id": fork_id or codex_text.compact_json(thread or res)}
        if action == "archive":
            client.request("thread/archive", {"threadId": thread_id}, timeout=30)
            return {"ok": True, "action": action, "thread_id": thread_id}
        if action == "unarchive":
            client.request("thread/unarchive", {"threadId": thread_id}, timeout=30)
            return {"ok": True, "action": action, "thread_id": thread_id}
        if action == "rename":
            name = str(name or "").strip()
            if not name:
                return {"ok": False, "error": "missing thread name"}
            client.request("thread/name/set", {"threadId": thread_id, "name": name}, timeout=30)
            return {"ok": True, "action": action, "thread_id": thread_id, "name": name}
        if action == "goal_get":
            res = client.request("thread/goal/get", {"threadId": thread_id}, timeout=30) or {}
            return {"ok": True, "action": action, "thread_id": thread_id, "goal": res.get("goal") or res}
        if action == "goal_set":
            objective = str(objective or "").strip()
            if not objective:
                return {"ok": False, "error": "missing goal objective"}
            params = {"threadId": thread_id, "objective": objective, "status": status or "active"}
            res = client.request("thread/goal/set", params, timeout=30) or {}
            return {"ok": True, "action": action, "thread_id": thread_id, "goal": res.get("goal") or res}
        if action == "goal_clear":
            client.request("thread/goal/clear", {"threadId": thread_id}, timeout=30)
            return {"ok": True, "action": action, "thread_id": thread_id}
        return {"ok": False, "error": "unsupported Codex history action: %s" % action}

    def _tool_event_from_item(self, item):
        return self._request_adapter().tool_event_from_item(item)

    def _tool_result_from_item(self, item):
        return self._request_adapter().tool_result_from_item(item)

    def _append_tool_output(self, item_id, delta, replace=False):
        return self._request_adapter().append_tool_output(item_id, delta, replace=replace)

    def handle_server_request(self, req_id, method, params):
        return self._request_adapter().handle_server_request(req_id, method, params)

    def _await_approval(self, req_id, method, params, name, preview):
        return self._request_adapter().await_approval(req_id, method, params, name, preview)

    def _await_user_input(self, req_id, method, params):
        return self._request_adapter().await_user_input(req_id, method, params)

    def _await_form_input(self, req_id, method, params):
        return self._request_adapter().await_form_input(req_id, method, params)

    def _reject_dynamic_tool_call(self, req_id, method, params):
        return self._request_adapter().reject_dynamic_tool_call(req_id, method, params)

    def _handle_dynamic_tool_call(self, req_id, method, params):
        return self._request_adapter().handle_dynamic_tool_call(req_id, method, params)

    def _call_mcp_tool_for_dynamic(self, params):
        return self._request_adapter().call_mcp_tool_for_dynamic(params)

    def _approval_response(self, method, allow, always, params):
        return self._request_adapter().approval_response(method, allow, always, params)

    def approve(self, tool_use_id, allow, message=None, always=False):
        return self._request_adapter().approve(tool_use_id, allow, always=always)

    def answer(self, tool_use_id, ans):
        return self._request_adapter().answer(tool_use_id, ans)

    def _request_adapter(self):
        adapter = getattr(self, "_requests", None)
        if adapter is None:
            adapter = codex_requests.CodexRequestAdapter(
                self, AppServerRequestError, common.codex_dynamic_tool_mappings)
            self._requests = adapter
        return adapter

    @staticmethod
    def _is_dangerous(text):
        return codex_replay_facade.CodexReplayFacade.is_dangerous(text)

    def _record_and_broadcast(self, obj):
        with self._lock:
            if obj.get("type") in ("assistant", "user", "result", "system", "compacted"):
                self.events.append(obj)
                if len(self.events) > 200:
                    self.events = self.events[-200:]
        self._broadcast(obj)

    def _event_identity_locked(self, obj):
        return self._replay.event_identity_locked(obj)

    def _record_timeline_locked(self, obj):
        return self._replay.record_timeline_locked(obj)

    def _merge_timeline_event_locked(self, out):
        return self._replay.merge_timeline_event_locked(out)

    @staticmethod
    def _tool_result_id(ev):
        return codex_replay_facade.CodexReplayFacade.tool_result_id(ev)

    @staticmethod
    def _replay_content_score(events):
        return codex_replay_facade.CodexReplayFacade.replay_content_score(events)

    @staticmethod
    def _drop_recover_noise(events):
        return codex_replay_facade.CodexReplayFacade.drop_recover_noise(events)

    def _adopt_history_replay(self, events):
        return self._replay.adopt_history_replay(events)

    def _decorate_for_broadcast(self, obj):
        return self._replay.decorate_for_broadcast(obj)

    def _broadcast(self, obj):
        return self._broadcast_adapter.broadcast(obj)

    def _persist_if_due(self, obj):
        return self._replay.persist_if_due(obj)

    def _send_one(self, sock, obj):
        return self._broadcast_adapter.send_one(sock, obj)

    @staticmethod
    def _event_after_seq(ev, after_seq):
        return codex_replay_facade.CodexReplayFacade.event_after_seq(ev, after_seq)

    def _events_after_seq(self, after_seq=0):
        return self._replay.events_after_seq(after_seq)

    def replay_payload(self, after_seq=0):
        return self._replay.replay_payload(after_seq)

    def add_client(self, sock, after_seq=0):
        return self._replay.add_client(
            sock,
            after_seq=after_seq,
            send_one=self._send_one,
            ws_send_fn=ws_send,
            ws_recv_fn=ws_recv,
        )

    def _state_snapshot(self):
        return codex_pending.state_snapshot(self)

    def _pending_events_snapshot(self):
        return codex_pending.pending_events_snapshot(self)

    def _push(self, event, title, body, webhook_body=None):
        return self._broadcast_adapter.push(event, title, body, webhook_body=webhook_body)

    def on_client_exit(self):
        was_busy = bool(self._busy)
        had_pending = codex_pending.clear_pending(self)
        self._busy = False
        self.current_turn_started_at = None
        self._thread_ready = False
        if not self._closed and (was_busy or had_pending):
            self._broadcast({"type": "result", "error": "Codex app-server exited. It will be restarted on the next send."})

    def _state_path(self):
        return self._state.path()

    def _persist(self):
        return self._state.persist()

    @classmethod
    def recover(cls, sid, cwd, expected_thread_id=None, user="", uid="", state_dir=None, codex_home=None):
        return codex_state.recover_session(
            cls, sid, cwd, expected_thread_id=expected_thread_id, user=user, uid=uid,
            state_dir=state_dir, codex_home=codex_home, default_state_dir=STATE_DIR,
            replay_max_events=_REPLAY_MAX_EVENTS, drop_noise_fn=cls._drop_recover_noise)


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
