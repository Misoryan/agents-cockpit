# -*- coding: utf-8 -*-
"""Codex notification adapter and helper implementation."""
import os
import time

from codex_client import CodexAppServerClient
import codex_text
import common


def remember_codex_debug_notice(session, message, method=None, params=None):
    session._codex_debug_notices.append({
        "ts": time.time(),
        "message": str(message or ""),
        "method": method,
        "detail": codex_text.compact_json(params) if params is not None else None,
    })
    session._codex_debug_notices = session._codex_debug_notices[-50:]


def remember_route_debug(session, message, method=None, params=None):
    session._route_debug.append({
        "ts": time.time(),
        "message": str(message or ""),
        "method": method,
        "thread_id": CodexAppServerClient._thread_id_from_params(params or {}) if params else None,
        "turn_id": CodexAppServerClient._turn_id_from_params(params or {}) if params else None,
        "item_id": CodexAppServerClient._item_id_from_params(params or {}) if params else None,
    })
    session._route_debug = session._route_debug[-30:]


def codex_notice(session, message, method=None, params=None, level=None, silent=False):
    if silent:
        remember_codex_debug_notice(session, message, method, params)
        return
    event = {"type": "codex_notice", "message": message}
    if method:
        event["method"] = method
    if params is not None:
        event["detail"] = codex_text.compact_json(params)
    if level:
        event["level"] = level
    session._broadcast(event)


def updated_event_notice_message(params):
    if not isinstance(params, dict):
        return ""
    for key in ("message", "text", "error"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("message") or value.get("text")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def handle_updated_event(session, method, params):
    message = updated_event_notice_message(params)
    if message:
        codex_notice(session, message, method, params)
    else:
        codex_notice(session, "Codex status updated", method, params, level="debug", silent=True)


def goal_summary(goal):
    if not isinstance(goal, dict) or not goal:
        return ""
    objective = str(goal.get("objective") or "").strip()
    status = str(goal.get("status") or "").strip()
    tokens_used = goal.get("tokensUsed")
    token_budget = goal.get("tokenBudget")
    parts = []
    if status:
        parts.append(status)
    if tokens_used is not None or token_budget is not None:
        if token_budget:
            parts.append("tokens %s/%s" % (tokens_used or 0, token_budget))
        elif tokens_used is not None:
            parts.append("tokens %s" % tokens_used)
    prefix = ("[%s] " % ", ".join(parts)) if parts else ""
    return prefix + (objective or "no objective")


def handle_notification(session, method, params):
    if not method:
        return
    session.last_activity = time.time()
    if method == "thread/started":
        session._apply_thread_response({"thread": params.get("thread") or {}})
    elif method == "turn/started":
        turn = params.get("turn") or {}
        session.last_turn_id = turn.get("id") or session.last_turn_id
        if session.last_turn_id:
            session._client().register_turn(session.last_turn_id, session)
        session._busy = True
        if not session.current_turn_started_at:
            session.current_turn_started_at = time.time()
        session._broadcast({
            "type": "turn_started",
            "provider": "codex",
            "turn_id": session.last_turn_id,
            "started_at": session.current_turn_started_at,
            "started_at_ms": int(session.current_turn_started_at * 1000),
            "elapsed_ms": max(0, int((time.time() - session.current_turn_started_at) * 1000)),
        })
        session._persist()
    elif method == "turn/completed":
        on_turn_completed(session, params.get("turn") or {})
    elif method == "thread/status/changed":
        status = params.get("status")
        if status == "idle" or (isinstance(status, dict) and status.get("type") == "idle"):
            session._busy = False
            session.current_turn_started_at = None
    elif method == "thread/settings/updated":
        on_thread_settings_updated(session, params.get("threadSettings") or {})
    elif method == "item/agentMessage/delta":
        delta = params.get("delta")
        if delta:
            session._broadcast({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": delta}}})
    elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
        delta = params.get("delta")
        if delta:
            session._broadcast({"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": delta}}})
    elif method == "item/started":
        on_item_started(session, params.get("item") or {})
    elif method == "item/completed":
        on_item_completed(session, params.get("item") or {})
    elif method == "item/commandExecution/outputDelta":
        session._append_tool_output(params.get("itemId"), params.get("delta") or "")
    elif method == "item/fileChange/patchUpdated":
        item_id = params.get("itemId")
        changes = params.get("changes") or []
        session._item_changes[item_id] = changes
        session._append_tool_output(item_id, codex_text.changes_to_diff(changes), replace=True)
    elif method == "item/mcpToolCall/progress":
        session._append_tool_output(params.get("itemId"), params.get("message") or "")
    elif method == "turn/diff/updated":
        diff = params.get("diff") or ""
        if diff:
            session._append_tool_output("turn-diff", diff, replace=True)
    elif method == "turn/plan/updated":
        on_plan_updated(session, params)
    elif method == "thread/tokenUsage/updated":
        usage = params.get("tokenUsage") or {}
        session._last_usage = usage_for_meta(usage)
        session._broadcast({"type": "codex_usage", "usage": usage})
    elif method == "thread/compacted":
        if getattr(session, "_compact_in_progress", False):
            session._compact_in_progress = False
            session._busy = False
            session.current_turn_started_at = None
        session._record_and_broadcast({"type": "compacted"})
    elif method == "thread/unarchived":
        codex_notice(session, "Thread unarchived in Codex history", method, params)
    elif method == "thread/goal/updated":
        goal = params.get("goal") or {}
        message = "Goal updated"
        summary = goal_summary(goal)
        if summary:
            message += ": " + summary
        codex_notice(session, message, method, params)
    elif method == "thread/goal/cleared":
        codex_notice(session, "Goal cleared", method, params)
    elif method in ("warning", "guardianWarning", "configWarning", "deprecationNotice"):
        message = params.get("message") or params.get("text") or codex_text.json_text(params)
        session._broadcast({"type": "codex_notice", "message": message})
    elif method == "item/reasoning/summaryPartAdded":
        text = codex_text.extract_text(params)
        if text:
            session._broadcast({"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": text}}})
    elif method == "item/commandExecution/terminalInteraction":
        event = session.terminal_interaction_event(params) if hasattr(session, "terminal_interaction_event") else None
        if event:
            session._record_and_broadcast(event)
        else:
            codex_notice(session, "Command requires terminal interaction; continue in CLI if input is required.", method, params)
    elif method == "item/fileChange/outputDelta":
        session._append_tool_output(params.get("itemId"), params.get("delta") or codex_text.extract_text(params) or "")
    elif method == "item/plan/delta":
        text = params.get("delta") or codex_text.extract_text(params)
        if text:
            item_id = params.get("itemId") or params.get("id") or "turn-plan"
            session._plan_output[item_id] = session._plan_output.get(item_id, "") + text
            session._broadcast({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": text}}})
    elif method == "model/rerouted":
        codex_notice(session, "Model rerouted", method, params)
    elif method in ("model/safetyBuffering/updated", "account/rateLimits/updated",
                    "mcpServer/startupStatus/updated", "turn/moderationMetadata"):
        handle_updated_event(session, method, params)
    elif method == "error":
        session._record_and_broadcast({"type": "result", "error": params.get("message") or codex_text.json_text(params)})
    elif method.endswith("/updated"):
        handle_updated_event(session, method, params)
    else:
        codex_notice(session, "Unhandled Codex event: " + method, method, params)


def on_turn_completed(session, turn):
    session._busy = False
    session.current_turn_started_at = None
    session.last_turn_id = turn.get("id") or session.last_turn_id
    status = turn.get("status") or ""
    error = turn.get("error")
    if status == "interrupted":
        session._record_and_broadcast({"type": "interrupted"})
    else:
        flush_pending_plan_items(session)
        event = {"type": "result", "duration_ms": turn.get("durationMs"), "usage": session._last_usage or {}}
        if status == "failed" or error:
            event["error"] = codex_text.json_text(error or "Codex turn failed")
            event["is_error"] = True
        session._record_and_broadcast(event)
        if not event.get("error") and not session._closed:
            with session._lock:
                webhook_body = common.notify_result_text(session.events)
            session._push("done", "Codex done - " + os.path.basename(session.cwd), session.cwd,
                          webhook_body=webhook_body or (session.cwd + " - done without final text"))
    session._persist()


def on_item_started(session, item):
    event = session._tool_event_from_item(item)
    if event:
        session._record_and_broadcast(event)


def on_item_completed(session, item):
    typ = item.get("type")
    if typ == "agentMessage":
        text = item.get("text") or ""
        if text:
            if codex_text.extract_proposed_plan(text):
                session._awaiting_plan_decision = True
                session._push("plan", "Codex Plan needs review - " + os.path.basename(session.cwd),
                              session.cwd + " - tap to review the plan")
            session._record_and_broadcast({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
    elif typ == "reasoning":
        content = "\n".join((item.get("summary") or []) + (item.get("content") or []))
        if content:
            session._record_and_broadcast({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": content}]}})
    elif typ == "plan":
        item_id = item.get("id") or "turn-plan"
        buffered = session._plan_output.pop(item_id, "")
        text = item.get("text") or buffered or codex_text.extract_text(item)
        event = codex_text.plan_text_event(text)
        if event:
            session._awaiting_plan_decision = True
            session._push("plan", "Codex Plan needs review - " + os.path.basename(session.cwd),
                          session.cwd + " - tap to review the plan")
            session._record_and_broadcast(event)
    else:
        result = session._tool_result_from_item(item)
        if result:
            session._record_and_broadcast(result)


def flush_pending_plan_items(session):
    if not session._plan_output:
        return
    pending = session._plan_output
    session._plan_output = {}
    for _item_id, text in pending.items():
        event = codex_text.plan_text_event(text)
        if event:
            session._awaiting_plan_decision = True
            session._push("plan", "Codex Plan needs review - " + os.path.basename(session.cwd),
                          session.cwd + " - tap to review the plan")
            session._record_and_broadcast(event)


def on_plan_updated(session, params):
    plan = params.get("plan") or []
    status_map = {"inProgress": "in_progress", "completed": "completed", "pending": "pending"}
    todos = [
        {"content": item.get("step") or "",
         "status": status_map.get(item.get("status"), item.get("status") or "pending")}
        for item in plan
        if isinstance(item, dict)
    ]
    if todos:
        session._record_and_broadcast({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "codex-plan", "name": "TodoWrite", "input": {"todos": todos}}]},
        })


def on_thread_settings_updated(session, settings):
    if not isinstance(settings, dict):
        return
    session.model = settings.get("model") or session.model
    session.model_provider = settings.get("modelProvider") or session.model_provider
    session.service_tier = settings.get("serviceTier") or session.service_tier
    mode = (((settings.get("collaborationMode") or {}).get("mode")) or "").lower()
    if mode in ("plan", "default"):
        new_plan = mode == "plan"
        if session.plan_mode != new_plan:
            session.plan_mode = new_plan
            if not new_plan:
                session._awaiting_plan_decision = False
            session._broadcast({"type": "mode_state", "plan": session.plan_mode, "task": session.task_mode})


def usage_for_meta(usage):
    last = (usage or {}).get("last") or {}
    return {
        "input_tokens": last.get("inputTokens") or 0,
        "output_tokens": last.get("outputTokens") or 0,
        "cache_read_input_tokens": last.get("cachedInputTokens") or 0,
        "cache_creation_input_tokens": 0,
        "reasoning_output_tokens": last.get("reasoningOutputTokens") or 0,
    }



class CodexNotificationAdapter:
    def __init__(self, session):
        self.session = session

    def remember_codex_debug_notice(self, message, method=None, params=None):
        return remember_codex_debug_notice(self.session, message, method=method, params=params)

    def remember_route_debug(self, message, method=None, params=None):
        return remember_route_debug(self.session, message, method=method, params=params)

    def codex_notice(self, message, method=None, params=None, level=None, silent=False):
        return codex_notice(self.session, message, method=method, params=params, level=level, silent=silent)

    @staticmethod
    def updated_event_notice_message(params):
        return updated_event_notice_message(params)

    def handle_updated_event(self, method, params):
        return handle_updated_event(self.session, method, params)

    def handle_notification(self, method, params):
        return handle_notification(self.session, method, params)

    def on_turn_completed(self, turn):
        return on_turn_completed(self.session, turn)

    def on_item_started(self, item):
        return on_item_started(self.session, item)

    def on_item_completed(self, item):
        return on_item_completed(self.session, item)

    def flush_pending_plan_items(self):
        return flush_pending_plan_items(self.session)

    def on_plan_updated(self, params):
        return on_plan_updated(self.session, params)

    def on_thread_settings_updated(self, settings):
        return on_thread_settings_updated(self.session, settings)

    @staticmethod
    def usage_for_meta(usage):
        return usage_for_meta(usage)
