# -*- coding: utf-8 -*-
"""Codex app-server backed structured sessions for Agents Cockpit.

This adapter keeps the browser-facing event shape close to native.py's Claude
stream-json events, while speaking Codex app-server JSONL/JSON-RPC on the
backend.
"""
import atexit
import base64
import json
import os
import re
import shlex
import threading
import time
import uuid

from codex_client import AppServerRequestError, CodexAppServerClient
import codex_config
import codex_events
import codex_forms
import codex_history
import codex_pending
import codex_replay_facade
import codex_requests
import codex_routing
import codex_session_events
import codex_terminal
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
_MENTION_RE = re.compile(r'(?<!\S)@(?:"([^"]+)"|([^\s@"]+))')
_IMAGE_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_IMAGE_DETAIL = {"auto", "low", "high", "original"}
_MAX_IMAGES_PER_TURN = 8
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


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
        text = (command or "").strip()
        if not text.startswith("/"):
            return {"ok": False, "error": "not a slash command"}
        name, _, rest = text.partition(" ")
        name = name.lower()
        arg = rest.strip()
        if name == "/model":
            return self.set_model(arg)
        if name == "/compact":
            return self.start_compaction()
        if name == "/approval":
            return self.set_approval_policy(arg)
        if name == "/sandbox":
            return self.set_sandbox_mode(arg)
        if name == "/search":
            return self.set_web_search(arg)
        if name == "/reasoning":
            return self.set_reasoning_effort(arg)
        if name == "/summary":
            return self.set_reasoning_summary(arg)
        if name == "/service-tier":
            return self.set_service_tier(arg)
        if name in ("/writable-roots", "/add-dir"):
            return self.set_writable_roots(arg)
        if name == "/rename":
            return self.rename_thread(arg)
        if name == "/archive":
            return self.archive_thread()
        if name == "/unarchive":
            return self.unarchive_thread()
        if name == "/fork":
            return self.fork_thread()
        if name == "/rollback":
            return self.rollback_thread(arg)
        if name == "/steer":
            return self.steer_turn(arg)
        if name == "/goal":
            return self.goal_command(arg)
        if name == "/mcp-resource":
            return self.read_mcp_resource(arg)
        if name == "/mcp-tool":
            return self.call_mcp_tool(arg)
        return {"ok": False, "error": "unsupported Codex slash command: %s" % name}

    def set_model(self, model):
        model = (model or "").strip()
        if not model:
            current = self.cfg.get("model") or self.model or "default"
            return {"ok": False, "error": "usage: /model <model-id> (current: %s)" % current}
        self.cfg["model"] = model
        self.model = model
        self._sync_collaboration_mode()
        self._record_and_broadcast({"type": "system", "model": model})
        self._codex_notice("Model set for subsequent Codex turns: %s" % model, "slash/model")
        self._persist()
        return {"ok": True, "command": "model", "model": model}

    def set_approval_policy(self, policy):
        policy = (policy or "").strip()
        if policy not in codex_config.APPROVAL_POLICIES:
            return {
                "ok": False,
                "error": "usage: /approval %s" % "|".join(codex_config.APPROVAL_POLICIES),
            }
        if self.yolo:
            return {"ok": False, "error": "auto approve is enabled for this session; restart with auto approve off first"}
        self.cfg["approval_policy"] = policy
        self._codex_notice("Approval policy set for subsequent Codex turns: %s" % policy, "slash/approval")
        self._persist()
        return {"ok": True, "command": "approval", "approval_policy": policy}

    def set_sandbox_mode(self, mode):
        mode = (mode or "").strip()
        if mode not in codex_config.SANDBOX_MODES:
            return {
                "ok": False,
                "error": "usage: /sandbox %s" % "|".join(codex_config.SANDBOX_MODES),
            }
        if self.yolo:
            return {"ok": False, "error": "auto approve is enabled for this session; restart with auto approve off first"}
        self.cfg["sandbox"] = mode
        self._codex_notice("Sandbox set for subsequent Codex turns: %s" % mode, "slash/sandbox")
        self._persist()
        return {"ok": True, "command": "sandbox", "sandbox": mode}

    def set_web_search(self, mode):
        mode = (mode or "").strip().lower()
        aliases = {"on": "live", "off": "disabled", "true": "live", "false": "disabled"}
        mode = aliases.get(mode, mode)
        if mode not in codex_config.WEB_SEARCH_MODES:
            return {
                "ok": False,
                "error": "usage: /search %s" % "|".join(codex_config.WEB_SEARCH_MODES),
            }
        if self.thread_id:
            return {
                "ok": False,
                "error": "web search is only configurable before the Codex thread starts; use the launch modal for existing threads",
            }
        self.cfg["web_search"] = mode
        self._codex_notice("Web search will be %s when this Codex thread starts" % mode, "slash/search")
        self._persist()
        return {"ok": True, "command": "search", "web_search": mode}

    def set_reasoning_effort(self, effort):
        effort = (effort or "").strip()
        if not effort:
            return {"ok": False, "error": "usage: /reasoning <effort> (for example low|medium|high)"}
        self.cfg["reasoning_effort"] = effort
        self._sync_collaboration_mode()
        self._codex_notice("Reasoning effort set for subsequent Codex turns: %s" % effort, "slash/reasoning")
        self._persist()
        return {"ok": True, "command": "reasoning", "reasoning_effort": effort}

    def set_reasoning_summary(self, summary):
        summary = (summary or "").strip().lower()
        if summary not in codex_config.REASONING_SUMMARIES:
            return {
                "ok": False,
                "error": "usage: /summary %s" % "|".join(codex_config.REASONING_SUMMARIES),
            }
        self.cfg["reasoning_summary"] = summary
        self._codex_notice("Reasoning summary set for subsequent Codex turns: %s" % summary, "slash/summary")
        self._persist()
        return {"ok": True, "command": "summary", "reasoning_summary": summary}

    def set_service_tier(self, tier):
        tier = (tier or "").strip()
        if not tier:
            self.cfg.pop("service_tier", None)
            self._codex_notice("Service tier override cleared for subsequent Codex turns", "slash/service-tier")
            self._persist()
            return {"ok": True, "command": "service-tier", "service_tier": ""}
        self.cfg["service_tier"] = tier
        self._codex_notice("Service tier set for subsequent Codex turns: %s" % tier, "slash/service-tier")
        self._persist()
        return {"ok": True, "command": "service-tier", "service_tier": tier}

    def set_writable_roots(self, roots_text):
        roots = codex_config.normalize_writable_roots(roots_text, cwd=self.cwd)
        denied = [root for root in roots if not common.path_allowed_for_user(self.user, root)]
        if denied:
            return {"ok": False, "error": "writable root is outside this user's workspaces: %s" % denied[0]}
        if not roots:
            self.cfg.pop("writable_roots", None)
            self._codex_notice("Additional writable roots cleared for subsequent Codex turns", "slash/writable-roots")
            self._persist()
            return {"ok": True, "command": "writable-roots", "writable_roots": []}
        self.cfg["writable_roots"] = roots
        self._codex_notice(
            "Additional writable roots set for subsequent Codex turns: %s" % ", ".join(roots),
            "slash/writable-roots",
        )
        self._persist()
        return {"ok": True, "command": "writable-roots", "writable_roots": roots}

    def start_compaction(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._busy = True
        self._compact_in_progress = True
        self.current_turn_started_at = time.time()
        try:
            self._client().request("thread/compact/start", {"threadId": self.thread_id}, timeout=30)
        except Exception:
            self._busy = False
            self._compact_in_progress = False
            self.current_turn_started_at = None
            raise
        self._codex_notice("Started Codex context compaction", "thread/compact/start")
        self._persist()
        return {"ok": True, "command": "compact"}

    def rename_thread(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "usage: /rename <thread name>"}
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request(
            "thread/name/set", {"threadId": self.thread_id, "name": name}, timeout=30)
        self._codex_notice("Thread renamed: %s" % name, "thread/name/set")
        self._persist()
        return {"ok": True, "command": "rename", "name": name}

    def archive_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request("thread/archive", {"threadId": self.thread_id}, timeout=30)
        self._codex_notice("Thread archived in Codex history", "thread/archive")
        self._persist()
        return {"ok": True, "command": "archive", "thread_id": self.thread_id}

    def unarchive_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request("thread/unarchive", {"threadId": self.thread_id}, timeout=30)
        self._codex_notice("Thread unarchived in Codex history", "thread/unarchive")
        self._persist()
        return {"ok": True, "command": "unarchive", "thread_id": self.thread_id}

    def fork_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        params = self._thread_params()
        params["threadId"] = self.thread_id
        res = self._client().request("thread/fork", params, timeout=30) or {}
        thread = res.get("thread") or {}
        fork_id = thread.get("id") or thread.get("sessionId") or ""
        if not fork_id:
            fork_id = codex_text.compact_json(thread or res)
        self._codex_notice("Thread forked: %s" % fork_id, "thread/fork")
        if thread.get("id") or thread.get("sessionId"):
            self._record_and_broadcast({
                "type": "thread_forked",
                "thread_id": fork_id,
                "cwd": self.cwd,
                "title": thread.get("title") or "Forked Codex thread",
            })
        return {"ok": True, "command": "fork", "thread_id": fork_id}

    def rollback_thread(self, count_text):
        try:
            count = int((count_text or "1").strip() or "1")
        except Exception:
            return {"ok": False, "error": "usage: /rollback [num-turns]"}
        if count < 1:
            return {"ok": False, "error": "rollback count must be >= 1"}
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        res = self._client().request(
            "thread/rollback",
            {"threadId": self.thread_id, "numTurns": count},
            timeout=30,
        ) or {}
        thread = res.get("thread") or {}
        self._replace_history_from_thread(thread)
        self._codex_notice("Rolled back %d Codex turn(s)" % count, "thread/rollback")
        self._persist()
        return {"ok": True, "command": "rollback", "num_turns": count}

    def steer_turn(self, prompt):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "usage: /steer <instruction for the running turn>"}
        if not self._busy or not self.thread_id or not self.last_turn_id:
            return {"ok": False, "error": "no running Codex turn to steer"}
        self._client().request(
            "turn/steer",
            {
                "threadId": self.thread_id,
                "expectedTurnId": self.last_turn_id,
                "input": self._user_input_items(prompt),
            },
            timeout=30,
        )
        self._codex_notice("Steered the running Codex turn", "turn/steer", {"prompt": prompt})
        return {"ok": True, "command": "steer"}

    def goal_command(self, arg):
        arg = (arg or "").strip()
        if not arg or arg.lower() == "get":
            return self.get_goal()
        action, _, rest = arg.partition(" ")
        action = action.strip().lower()
        rest = rest.strip()
        if action == "set":
            return self.set_goal(rest)
        if action == "clear":
            return self.clear_goal()
        if action == "status":
            return self.set_goal_status(rest)
        if action in [s.lower() for s in codex_config.GOAL_STATUSES]:
            return self.set_goal_status(action)
        return {
            "ok": False,
            "error": "usage: /goal [get|set <objective>|clear|status %s]" % "|".join(codex_config.GOAL_STATUSES),
        }

    def _ensure_goal_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return False
        return True

    def _goal_from_response(self, response):
        if isinstance(response, dict):
            goal = response.get("goal") or response.get("threadGoal")
            if isinstance(goal, dict):
                return goal
        return {}

    def _goal_summary(self, goal):
        if not isinstance(goal, dict) or not goal:
            return ""
        objective = str(goal.get("objective") or "").strip()
        status = str(goal.get("status") or "").strip()
        parts = []
        if status:
            parts.append(status)
        used = goal.get("tokensUsed")
        budget = goal.get("tokenBudget")
        if used is not None or budget is not None:
            if budget:
                parts.append("tokens %s/%s" % (used or 0, budget))
            elif used is not None:
                parts.append("tokens %s" % used)
        prefix = ("[%s] " % ", ".join(parts)) if parts else ""
        return prefix + (objective or "no objective")

    def get_goal(self):
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        res = self._client().request("thread/goal/get", {"threadId": self.thread_id}, timeout=30) or {}
        goal = self._goal_from_response(res)
        if goal:
            self._codex_notice("Goal: " + self._goal_summary(goal), "thread/goal/get", goal)
        else:
            self._codex_notice("No Codex goal is set", "thread/goal/get")
        return {"ok": True, "command": "goal", "action": "get", "goal": goal}

    def set_goal(self, objective):
        objective = (objective or "").strip()
        if not objective:
            return {"ok": False, "error": "usage: /goal set <objective>"}
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        params = {"threadId": self.thread_id, "objective": objective, "status": "active"}
        res = self._client().request("thread/goal/set", params, timeout=30) or {}
        goal = self._goal_from_response(res) or {"objective": objective, "status": "active"}
        self._codex_notice("Goal set: " + self._goal_summary(goal), "thread/goal/set", goal)
        self._persist()
        return {"ok": True, "command": "goal", "action": "set", "goal": goal}

    def set_goal_status(self, status):
        status = (status or "").strip()
        matches = {s.lower(): s for s in codex_config.GOAL_STATUSES}
        if status.lower() not in matches:
            return {
                "ok": False,
                "error": "usage: /goal status %s" % "|".join(codex_config.GOAL_STATUSES),
            }
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        status = matches[status.lower()]
        params = {"threadId": self.thread_id, "status": status}
        res = self._client().request("thread/goal/set", params, timeout=30) or {}
        goal = self._goal_from_response(res) or {"objective": "", "status": status}
        self._codex_notice("Goal status set: " + self._goal_summary(goal), "thread/goal/set", goal)
        self._persist()
        return {"ok": True, "command": "goal", "action": "status", "status": status, "goal": goal}

    def clear_goal(self):
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request("thread/goal/clear", {"threadId": self.thread_id}, timeout=30)
        self._codex_notice("Goal cleared", "thread/goal/clear")
        self._persist()
        return {"ok": True, "command": "goal", "action": "clear"}

    def _split_words(self, text, expected=0):
        try:
            words = shlex.split(str(text or ""), posix=True)
        except ValueError:
            words = str(text or "").split()
        if expected and len(words) < expected:
            return None
        return words

    def _mcp_result_events(self, call_id, name, input_obj, result, method):
        self._record_and_broadcast({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": input_obj or {}}]},
        })
        self._record_and_broadcast({
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": call_id,
                                      "content": codex_text.compact_json(result or {}, 5000)}]},
        })
        self._codex_notice("%s completed" % name, method, result, silent=True)

    def read_mcp_resource(self, arg):
        words = self._split_words(arg, expected=2)
        if not words:
            return {"ok": False, "error": "usage: /mcp-resource <server> <uri>"}
        server, uri = words[0], words[1]
        self._ensure_thread()
        params = {"server": server, "uri": uri, "threadId": self.thread_id}
        result = self._client().request("mcpServer/resource/read", params, timeout=45) or {}
        call_id = "mcp-resource-%s-%d" % (server, int(time.time() * 1000))
        self._mcp_result_events(call_id, "mcpServer.resource/read", params, result, "mcpServer/resource/read")
        return {"ok": True, "command": "mcp-resource", "server": server, "uri": uri}

    def call_mcp_tool(self, arg):
        parts = str(arg or "").split(None, 2)
        if len(parts) < 2:
            return {"ok": False, "error": "usage: /mcp-tool <server> <tool> [json-args]"}
        server, tool = parts[0], parts[1]
        args = {}
        if len(parts) > 2 and parts[2].strip():
            try:
                args = json.loads(parts[2])
            except Exception as exc:
                return {"ok": False, "error": "invalid JSON args: %s" % exc}
            if not isinstance(args, dict):
                return {"ok": False, "error": "json-args must be an object"}
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        params = {"server": server, "tool": tool, "threadId": self.thread_id, "arguments": args}
        result = self._client().request("mcpServer/tool/call", params, timeout=120) or {}
        call_id = "mcp-tool-%s-%s-%d" % (server, tool, int(time.time() * 1000))
        self._mcp_result_events(call_id, "%s.%s" % (server, tool), args, result, "mcpServer/tool/call")
        return {"ok": True, "command": "mcp-tool", "server": server, "tool": tool}

    def _path_within_cwd(self, path):
        try:
            cwd = os.path.normcase(os.path.abspath(self.cwd))
            candidate = os.path.normcase(os.path.abspath(path))
            return os.path.commonpath([cwd, candidate]) == cwd
        except Exception:
            return False

    def _resolve_mention_path(self, raw_path):
        raw_path = str(raw_path or "").strip().strip("\"'")
        if not raw_path:
            return ""
        candidate = raw_path if os.path.isabs(raw_path) else os.path.join(self.cwd, raw_path)
        candidate = os.path.abspath(candidate)
        if not self._path_within_cwd(candidate):
            return ""
        if self.user and not common.path_allowed_for_user(self.user, candidate):
            return ""
        if not os.path.exists(candidate):
            return ""
        return candidate

    def _image_upload_dir(self):
        return os.path.join(self.state_dir, "codex_uploads", self.sid)

    def image_file(self, image_id):
        image_id = os.path.basename(str(image_id or ""))
        if not image_id:
            return ""
        root = os.path.abspath(self._image_upload_dir())
        path = os.path.abspath(os.path.join(root, image_id))
        try:
            if os.path.commonpath([root, path]) != root:
                return ""
        except Exception:
            return ""
        return path if os.path.isfile(path) else ""

    def prepare_image_inputs(self, images):
        if not images:
            return []
        if not isinstance(images, list):
            raise ValueError("images must be an array")
        if len(images) > _MAX_IMAGES_PER_TURN:
            raise ValueError("too many images; max %d" % _MAX_IMAGES_PER_TURN)
        root = self._image_upload_dir()
        os.makedirs(root, exist_ok=True)
        out = []
        for idx, image in enumerate(images):
            if not isinstance(image, dict):
                raise ValueError("image %d is invalid" % (idx + 1))
            data_url = str(image.get("data_url") or image.get("dataUrl") or "")
            raw_b64 = str(image.get("data") or "")
            mime = str(image.get("mime") or image.get("type") or "").split(";", 1)[0].lower().strip()
            if data_url.startswith("data:"):
                header, sep, payload = data_url.partition(",")
                if not sep or ";base64" not in header:
                    raise ValueError("image %d must be base64 data URL" % (idx + 1))
                mime = header[5:].split(";", 1)[0].lower().strip()
                raw_b64 = payload
            if mime not in _IMAGE_MIME_EXT:
                raise ValueError("unsupported image type: %s" % (mime or "unknown"))
            try:
                raw = base64.b64decode(raw_b64, validate=True)
            except Exception:
                raise ValueError("image %d has invalid base64 data" % (idx + 1))
            if not raw:
                raise ValueError("image %d is empty" % (idx + 1))
            if len(raw) > _MAX_IMAGE_BYTES:
                raise ValueError("image %d exceeds %d MB" % (idx + 1, _MAX_IMAGE_BYTES // (1024 * 1024)))
            image_id = uuid.uuid4().hex + _IMAGE_MIME_EXT[mime]
            path = os.path.join(root, image_id)
            with open(path, "wb") as handle:
                handle.write(raw)
            detail = str(image.get("detail") or "auto").strip().lower()
            if detail not in _IMAGE_DETAIL:
                detail = "auto"
            out.append({
                "type": "localImage",
                "path": os.path.abspath(path),
                "name": str(image.get("name") or image_id),
                "image_id": image_id,
                "mime": mime,
                "size": len(raw),
                "detail": detail,
            })
        return out

    def _display_user_content(self, text, image_inputs=None):
        blocks = []
        if str(text or "").strip():
            blocks.append({"type": "text", "text": str(text or "")})
        for image in image_inputs or []:
            if not isinstance(image, dict):
                continue
            blocks.append({
                "type": "localImage",
                "path": image.get("path") or "",
                "name": image.get("name") or os.path.basename(image.get("path") or ""),
                "image_id": image.get("image_id") or "",
                "mime": image.get("mime") or "",
                "size": image.get("size") or 0,
            })
        return blocks if blocks else str(text or "")

    def _user_input_items(self, text, image_inputs=None):
        text = str(text or "")
        items = []
        if text.strip() or not image_inputs:
            items.append({"type": "text", "text": text, "text_elements": []})
        seen = set()
        for match in _MENTION_RE.finditer(text):
            raw_path = match.group(1) or match.group(2) or ""
            path = self._resolve_mention_path(raw_path)
            if not path or path in seen:
                continue
            seen.add(path)
            items.append({
                "type": "mention",
                "path": path,
                "name": os.path.basename(path) or path,
            })
        for image in image_inputs or []:
            if not isinstance(image, dict):
                continue
            path = image.get("path") or ""
            if not path:
                continue
            item = {"type": "localImage", "path": path}
            detail = image.get("detail")
            if detail in _IMAGE_DETAIL:
                item["detail"] = detail
            items.append(item)
        return items

    def _search_file_result(self, item):
        if not isinstance(item, dict):
            return None
        root = item.get("root") or self.cwd
        path = item.get("path") or ""
        if not path:
            return None
        abs_path = path if os.path.isabs(path) else os.path.abspath(os.path.join(root, path))
        if not self._path_within_cwd(abs_path):
            return None
        rel = os.path.relpath(abs_path, self.cwd)
        if rel == ".":
            rel = os.path.basename(abs_path)
        rel = rel.replace(os.sep, "/")
        return {
            "path": abs_path,
            "insert": rel,
            "name": item.get("file_name") or os.path.basename(abs_path) or rel,
            "match_type": item.get("match_type") or ("directory" if os.path.isdir(abs_path) else "file"),
            "score": item.get("score") or 0,
        }

    def search_files(self, query, limit=20):
        query = str(query or "").strip()
        if not query:
            return {"ok": True, "files": []}
        try:
            limit = max(1, min(50, int(limit or 20)))
        except Exception:
            limit = 20
        self._client().ensure()
        res = self._client().request(
            "fuzzyFileSearch",
            {"query": query, "roots": [self.cwd]},
            timeout=15,
        ) or {}
        files = []
        for item in (res.get("files") or []):
            result = self._search_file_result(item)
            if result:
                files.append(result)
            if len(files) >= limit:
                break
        return {"ok": True, "files": files}

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
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        with self.clients_lock:
            clients = list(self.clients)
        dead = []
        for client in clients:
            try:
                ws_send(client, data, 0x1)
            except OSError:
                dead.append(client)
        if dead:
            with self.clients_lock:
                for client in dead:
                    self.clients.discard(client)

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
        params = {"cwd": self.cwd}
        if self.cfg.get("model"):
            params["model"] = self.cfg["model"]
        if self.cfg.get("approval_policy"):
            params["approvalPolicy"] = self.cfg["approval_policy"]
        if self.cfg.get("sandbox"):
            params["sandbox"] = self.cfg["sandbox"]
        if self.cfg.get("service_tier"):
            params["serviceTier"] = self.cfg["service_tier"]
        config = codex_config.thread_config(self.cfg)
        if config:
            params["config"] = config
        if self.yolo:
            params["approvalPolicy"] = "never"
            params["sandbox"] = "danger-full-access"
        return params

    def _turn_params(self, prompt, image_inputs=None):
        text = prompt
        if self.task_mode:
            text = _TASK_SYSTEM + "\n\n" + text
        params = {
            "threadId": self.thread_id,
            "cwd": self.cwd,
            "input": self._user_input_items(text, image_inputs=image_inputs),
            "collaborationMode": self._collaboration_mode(),
        }
        if self.cfg.get("model"):
            params["model"] = self.cfg["model"]
        if self.cfg.get("service_tier"):
            params["serviceTier"] = self.cfg["service_tier"]
        if self.cfg.get("reasoning_effort"):
            params["effort"] = self.cfg["reasoning_effort"]
        if self.cfg.get("reasoning_summary"):
            params["summary"] = self.cfg["reasoning_summary"]
        if self.yolo:
            params["approvalPolicy"] = "never"
            params["sandboxPolicy"] = {"type": "dangerFullAccess"}
        else:
            if self.cfg.get("approval_policy"):
                params["approvalPolicy"] = self.cfg["approval_policy"]
            sandbox = codex_config.sandbox_policy(
                self.cfg.get("sandbox"), self.cwd, self.cfg.get("writable_roots"))
            if sandbox:
                params["sandboxPolicy"] = sandbox
        return params

    def _collaboration_mode(self):
        return {
            "mode": "plan" if self.plan_mode else "default",
            "settings": {
                "model": self.model or self.cfg.get("model") or "",
                "reasoning_effort": self.cfg.get("reasoning_effort") or None,
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
        self.model = res.get("model") or self.model or self.cfg.get("model") or ""
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

    def _run_turn(self, prompt, image_inputs=None):
        self._busy = True
        if not self.current_turn_started_at:
            self.current_turn_started_at = time.time()
        self.last_activity = time.time()
        try:
            self._ensure_thread()
            self._sync_collaboration_mode()
            res = self._client().request(
                "turn/start", self._turn_params(prompt, image_inputs=image_inputs), timeout=30)
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

    def _handle_dynamic_tool_call(self, req_id, method, params):
        return codex_requests.handle_dynamic_tool_call(
            self, req_id, method, params, common.codex_dynamic_tool_mappings())

    def _call_mcp_tool_for_dynamic(self, params):
        return self._client().request("mcpServer/tool/call", params, timeout=120) or {}

    def _approval_response(self, method, allow, always, params):
        return codex_requests.approval_response(method, allow, always, params)

    def approve(self, tool_use_id, allow, message=None, always=False):
        return codex_pending.approve(self, tool_use_id, allow, always=always)

    def answer(self, tool_use_id, ans):
        return codex_pending.answer(self, tool_use_id, ans)

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
        obj = self._replay.prepare_broadcast(obj)
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
        return self._replay.persist_if_due(obj)

    def _send_one(self, sock, obj):
        try:
            ws_send(sock, json.dumps(obj, ensure_ascii=False).encode("utf-8"), 0x1)
        except OSError:
            with self.clients_lock:
                self.clients.discard(sock)

    @staticmethod
    def _event_after_seq(ev, after_seq):
        return codex_replay_facade.CodexReplayFacade.event_after_seq(ev, after_seq)

    def _events_after_seq(self, after_seq=0):
        return self._replay.events_after_seq(after_seq)

    def replay_payload(self, after_seq=0):
        return self._replay.replay_payload(after_seq)

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
        return codex_pending.state_snapshot(self)

    def _pending_events_snapshot(self):
        return codex_pending.pending_events_snapshot(self)

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
        had_pending = codex_pending.clear_pending(self)
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
                        "cfg": self.cfg,
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
                     cfg=data.get("cfg") or {},
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
