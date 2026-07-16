# -*- coding: utf-8 -*-
"""Codex app-server request, approval, ask, and form helpers."""
import os
import threading
import time

import codex_forms
import codex_text


DYNAMIC_TOOL_REJECTION = (
    "Agents Cockpit cannot execute Codex dynamic tool calls yet. "
    "Continue in Codex CLI or wire this tool through an MCP passthrough."
)


def approval_response(method, allow, always, params):
    if method == "item/commandExecution/requestApproval":
        return {"decision": ("acceptForSession" if always else "accept") if allow else "decline"}
    if method == "item/fileChange/requestApproval":
        return {"decision": ("acceptForSession" if always else "accept") if allow else "decline"}
    if method == "item/permissions/requestApproval":
        permissions = params.get("permissions") if allow else {}
        return {"permissions": permissions or {}, "scope": "session" if always else "turn"}
    return {"decision": "accept" if allow else "decline"}


def await_approval(session, req_id, method, params, name, preview, timeout=600):
    danger = session._is_dangerous(preview)
    entry = {"event": threading.Event(), "kind": "approve", "method": method, "params": params,
             "name": name, "preview": preview, "danger": danger,
             "allow": None, "always": False}
    with session._pending_lock:
        session._pending[req_id] = entry
    session._broadcast({
        "type": "pending_approval",
        "tool_use_id": req_id,
        "name": name,
        "input": params,
        "preview": preview,
        "danger": danger,
    })
    session._push("confirm", "Codex needs confirmation - " + os.path.basename(session.cwd), str(preview or name))
    entry["event"].wait(timeout=timeout)
    with session._pending_lock:
        session._pending.pop(req_id, None)
    if not entry.get("allow"):
        return approval_response(method, False, False, params)
    return approval_response(method, True, bool(entry.get("always")), params)


def user_input_response(method, questions, answer):
    answer = answer or ""
    if method == "item/tool/requestUserInput":
        return {"answers": codex_text.answers_for_questions(questions, answer)}
    if isinstance(answer, dict):
        content = {}
        for key, value in answer.items():
            values = codex_text.answer_list(value)
            if values:
                content[key] = values[0] if len(values) == 1 else values
        return {"action": "accept" if content else "decline", "content": content or None}
    return {"action": "accept" if answer else "decline", "content": {"answer": answer} if answer else None}


def await_user_input(session, req_id, method, params, timeout=600):
    questions = codex_text.clean_questions(params.get("questions") or [])
    fallback = params.get("message") or params.get("prompt") or codex_text.json_text(params)
    question_text = codex_text.question_text(questions, fallback)
    entry = {"event": threading.Event(), "kind": "ask", "method": method, "params": params,
             "question": question_text, "questions": questions,
             "auto_resolution_ms": params.get("autoResolutionMs"), "answer": ""}
    with session._pending_lock:
        session._pending[req_id] = entry
    event = {
        "type": "pending_ask",
        "tool_use_id": req_id,
        "question": question_text,
        "questions": questions,
    }
    if params.get("autoResolutionMs") is not None:
        event["auto_resolution_ms"] = params.get("autoResolutionMs")
    session._broadcast(event)
    session._push("confirm", "Codex waits for input - " + os.path.basename(session.cwd), question_text)
    wait_timeout = timeout
    try:
        if params.get("autoResolutionMs"):
            wait_timeout = max(1, min(timeout, float(params.get("autoResolutionMs")) / 1000.0))
    except (TypeError, ValueError):
        pass
    entry["event"].wait(timeout=wait_timeout)
    with session._pending_lock:
        session._pending.pop(req_id, None)
    return user_input_response(method, questions, entry.get("answer"))


def form_response(answer):
    if not isinstance(answer, dict):
        return {"action": "decline", "content": None}
    action = answer.get("action") or ("accept" if answer.get("content") else "decline")
    if action not in ("accept", "decline", "cancel"):
        action = "accept"
    content = answer.get("content") if action == "accept" else None
    return {"action": action, "content": content}


def await_form_input(session, req_id, method, params, timeout=600):
    schema = params.get("requestedSchema")
    fields = codex_forms.form_fields_from_schema(schema)
    message = params.get("message") or "Codex requests form input"
    schema_detail = codex_text.compact_json(schema, 2500) if schema is not None else ""
    entry = {"event": threading.Event(), "kind": "form", "method": method, "params": params,
             "message": message, "fields": fields, "schema_detail": schema_detail, "answer": None}
    with session._pending_lock:
        session._pending[req_id] = entry
    session._broadcast({
        "type": "pending_form",
        "tool_use_id": req_id,
        "message": message,
        "mode": params.get("mode") or "form",
        "server_name": params.get("serverName") or "",
        "fields": fields,
        "schema_detail": schema_detail,
    })
    session._push("confirm", "Codex waits for form input - " + os.path.basename(session.cwd), message)
    entry["event"].wait(timeout=timeout)
    with session._pending_lock:
        session._pending.pop(req_id, None)
    return form_response(entry.get("answer"))


def reject_dynamic_tool_call(session, req_id, method, params):
    tool = params.get("tool") or "tool"
    namespace = params.get("namespace") or "dynamic"
    call_id = params.get("callId") or req_id
    name = ("%s.%s" % (namespace, tool)) if namespace else str(tool)
    args = params.get("arguments")
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": args or {}}]},
    })
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": call_id,
                                  "content": DYNAMIC_TOOL_REJECTION}]},
    })
    session._codex_notice("Dynamic tool call was rejected by the Web adapter", method, params)
    return {"success": False, "contentItems": [{"type": "inputText", "text": DYNAMIC_TOOL_REJECTION}]}


def handle_server_request(session, req_id, method, params, app_error_cls):
    if method == "item/commandExecution/requestApproval":
        return session._await_approval(req_id, method, params, "Command", params.get("command") or "")
    if method == "item/fileChange/requestApproval":
        preview = params.get("reason") or params.get("grantRoot") or "File change approval"
        return session._await_approval(req_id, method, params, "FileChange", preview)
    if method == "item/permissions/requestApproval":
        return session._await_approval(req_id, method, params, "Permissions",
                                       params.get("reason") or codex_text.json_text(params.get("permissions")))
    if method == "item/tool/requestUserInput":
        return session._await_user_input(req_id, method, params)
    if method == "mcpServer/elicitation/request":
        if params.get("mode") in ("form", "openai/form"):
            return session._await_form_input(req_id, method, params)
        return session._await_user_input(req_id, method, params)
    if method == "item/tool/call":
        return session._reject_dynamic_tool_call(req_id, method, params)
    if method == "attestation/generate":
        session._codex_notice(
            "Codex requested client attestation; Agents Cockpit cannot generate it yet.",
            method,
            params,
        )
        raise app_error_cls(-32601, "client attestation is not supported by Agents Cockpit")
    if method == "account/chatgptAuthTokens/refresh":
        session._codex_notice(
            "Codex requested ChatGPT auth token refresh; refresh the login in Codex CLI.",
            method,
            params,
        )
        raise app_error_cls(-32601, "ChatGPT auth token refresh is not supported by Agents Cockpit")
    if method == "currentTime/read":
        return {"utcTimestampMs": int(time.time() * 1000)}
    session._codex_notice("Unsupported app-server request: " + str(method or "unknown"), method, params)
    raise app_error_cls(-32601, "unsupported app-server request: %s" % method)
