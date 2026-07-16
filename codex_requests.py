# -*- coding: utf-8 -*-
"""Codex app-server request, approval, ask, and form helpers."""
import os
import threading
import time

import codex_forms
import codex_text


DYNAMIC_TOOL_REJECTION = (
    "Agents Cockpit has no enabled MCP passthrough mapping for this dynamic tool. "
    "Add it under [codex_dynamic_tools] in config.ini if it is safe to run."
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
    display_args = args if args is not None else {}
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": display_args}]},
    })
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": call_id,
                                  "content": DYNAMIC_TOOL_REJECTION}]},
    })
    session._codex_notice("Dynamic tool call was rejected by the Web adapter", method, params)
    return {"success": False, "contentItems": [{"type": "inputText", "text": DYNAMIC_TOOL_REJECTION}]}


def _dynamic_tool_name(params):
    tool = str(params.get("tool") or "tool").strip() or "tool"
    namespace = str(params.get("namespace") or "").strip()
    return namespace, tool, ("%s.%s" % (namespace, tool)) if namespace else tool


def _dynamic_mapping_candidates(namespace, tool):
    if namespace:
        return [
            "%s.%s" % (namespace, tool),
            "%s/%s" % (namespace, tool),
            "%s.*" % namespace,
            "%s/*" % namespace,
        ]
    return [tool]


def dynamic_tool_target(params, mappings):
    """Return (server, tool) for an explicitly allowlisted dynamic tool."""
    if not isinstance(mappings, dict):
        return None
    namespace, tool, _name = _dynamic_tool_name(params)
    by_key = {str(key).strip().lower(): str(value).strip()
              for key, value in mappings.items() if str(key).strip() and str(value).strip()}
    target = ""
    for key in _dynamic_mapping_candidates(namespace, tool):
        target = by_key.get(key.lower())
        if target:
            break
    if not target:
        return None
    if target.lower().startswith("mcp:"):
        target = target[4:].strip()
    target = target.replace("{tool}", tool)
    for sep in ("/", ".", ":"):
        if sep in target:
            server, mcp_tool = target.split(sep, 1)
            server, mcp_tool = server.strip(), mcp_tool.strip()
            if server and mcp_tool:
                return server, mcp_tool
            return None
    return None


def _content_text_from_mcp(result):
    if not isinstance(result, dict):
        return codex_text.compact_json(result, 5000)
    parts = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text") is not None:
            parts.append(str(item.get("text")))
        elif item.get("type") == "image":
            parts.append("[image]")
        else:
            parts.append(codex_text.compact_json(item, 1000))
    if parts:
        return "\n".join(parts)
    return codex_text.compact_json(result or {}, 5000)


def dynamic_content_items_from_mcp(result):
    """Convert an MCP tool result into DynamicToolCallResponse content items."""
    items = []
    if isinstance(result, dict):
        for item in result.get("content") or []:
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ == "text" and item.get("text") is not None:
                items.append({"type": "inputText", "text": str(item.get("text"))})
            elif typ == "image":
                image_url = item.get("imageUrl") or item.get("url")
                if not image_url and item.get("data"):
                    mime = item.get("mimeType") or "image/png"
                    image_url = "data:%s;base64,%s" % (mime, item.get("data"))
                if image_url:
                    items.append({"type": "inputImage", "imageUrl": str(image_url)})
                else:
                    items.append({"type": "inputText", "text": codex_text.compact_json(item, 1000)})
            else:
                items.append({"type": "inputText", "text": codex_text.compact_json(item, 1000)})
    if not items:
        items.append({"type": "inputText", "text": _content_text_from_mcp(result)})
    return items


def handle_dynamic_tool_call(session, req_id, method, params, mappings):
    target = dynamic_tool_target(params, mappings)
    if not target:
        return reject_dynamic_tool_call(session, req_id, method, params)

    _namespace, _tool, name = _dynamic_tool_name(params)
    call_id = params.get("callId") or req_id
    args = params.get("arguments")
    display_args = args if args is not None else {}
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": display_args}]},
    })

    server, mcp_tool = target
    thread_id = params.get("threadId") or getattr(session, "thread_id", None)
    mcp_params = {"server": server, "tool": mcp_tool, "threadId": thread_id, "arguments": display_args}
    try:
        result = session._call_mcp_tool_for_dynamic(mcp_params)
        success = not bool(result.get("isError")) if isinstance(result, dict) else True
        content_items = dynamic_content_items_from_mcp(result)
        content_text = _content_text_from_mcp(result)
    except Exception as exc:
        success = False
        content_text = "MCP passthrough failed: %s" % exc
        content_items = [{"type": "inputText", "text": content_text}]
        result = {"error": content_text}

    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": content_text}]},
    })
    notice = "Dynamic tool %s passed through to MCP %s.%s" % (name, server, mcp_tool)
    session._codex_notice(notice, "mcpServer/tool/call", result, silent=True)
    return {"success": success, "contentItems": content_items}


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
        return session._handle_dynamic_tool_call(req_id, method, params)
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
