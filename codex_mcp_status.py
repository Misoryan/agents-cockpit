# -*- coding: utf-8 -*-
"""MCP status and resource-list helpers for Codex sessions."""
import shlex
import time

import codex_text


DETAIL_ALIASES = {
    "": "full",
    "full": "full",
    "resources": "full",
    "resource": "full",
    "tools": "toolsAndAuthOnly",
    "tool": "toolsAndAuthOnly",
    "tools-only": "toolsAndAuthOnly",
    "toolsandauthonly": "toolsAndAuthOnly",
    "toolsAndAuthOnly": "toolsAndAuthOnly",
}


def split_words(text):
    try:
        return shlex.split(str(text or ""), posix=True)
    except ValueError:
        return str(text or "").split()


def normalize_detail(value):
    raw = str(value or "").strip()
    key = raw if raw == "toolsAndAuthOnly" else raw.lower()
    if key not in DETAIL_ALIASES:
        return None
    return DETAIL_ALIASES[key]


def display_name(server):
    if not isinstance(server, dict):
        return ""
    return str(server.get("name") or "").strip()


def _len(value):
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, (list, tuple)):
        return len(value)
    return 0


def _short_text(value, limit=240):
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _tools_list(tools):
    if isinstance(tools, dict):
        out = []
        for key, value in sorted(tools.items()):
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("name", key)
                out.append(tool_summary(item))
            else:
                out.append({"name": str(key)})
        return out
    return [tool_summary(item) for item in tools or [] if isinstance(item, dict)]


def resource_summary(item):
    if not isinstance(item, dict):
        return {}
    return {
        "name": item.get("name") or item.get("title") or "",
        "uri": item.get("uri") or "",
        "mimeType": item.get("mimeType") or "",
        "description": _short_text(item.get("description")),
    }


def resource_template_summary(item):
    if not isinstance(item, dict):
        return {}
    return {
        "name": item.get("name") or item.get("title") or "",
        "uriTemplate": item.get("uriTemplate") or "",
        "mimeType": item.get("mimeType") or "",
        "description": _short_text(item.get("description")),
    }


def tool_summary(item):
    if not isinstance(item, dict):
        return {}
    return {
        "name": item.get("name") or item.get("title") or "",
        "description": _short_text(item.get("description")),
    }


def server_summary(server, include_items=False):
    if not isinstance(server, dict):
        return {}
    resources = server.get("resources") or []
    templates = server.get("resourceTemplates") or []
    tools = server.get("tools") or {}
    info = server.get("serverInfo") or {}
    out = {
        "name": display_name(server),
        "authStatus": server.get("authStatus") or "unknown",
        "tools": _len(tools),
        "resources": _len(resources),
        "resourceTemplates": _len(templates),
    }
    if isinstance(info, dict) and info:
        out["serverInfo"] = {
            "name": info.get("name") or "",
            "title": info.get("title") or "",
            "version": info.get("version") or "",
            "websiteUrl": info.get("websiteUrl") or "",
        }
    if include_items:
        out["toolList"] = _tools_list(tools)
        out["resourceList"] = [resource_summary(item) for item in resources if isinstance(item, dict)]
        out["resourceTemplateList"] = [
            resource_template_summary(item) for item in templates if isinstance(item, dict)
        ]
    return out


def status_detail_payload(response, include_items=False):
    data = response.get("data") if isinstance(response, dict) else []
    return {
        "servers": [server_summary(server, include_items=include_items) for server in data or []],
        "nextCursor": response.get("nextCursor") if isinstance(response, dict) else None,
    }


def status_request_params(session, detail="full", cursor=None, limit=50):
    params = {
        "threadId": getattr(session, "thread_id", None),
        "limit": limit,
        "detail": detail,
    }
    if cursor:
        params["cursor"] = cursor
    return params


def emit_result_events(session, call_id, name, input_obj, result):
    if hasattr(session, "_mcp_result_events"):
        try:
            session._mcp_result_events(
                call_id, name, input_obj, result, "mcpServerStatus/list", result_limit=None
            )
        except TypeError:
            session._mcp_result_events(call_id, name, input_obj, result, "mcpServerStatus/list")
        return True
    if not hasattr(session, "_record_and_broadcast"):
        return False
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": input_obj or {}}]},
    })
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": call_id,
            "content": codex_text.json_text(result or {}),
        }]},
    })
    return True


def status_notice_message(response):
    data = response.get("data") if isinstance(response, dict) else []
    if not data:
        return "MCP status: no servers returned"
    parts = []
    for server in data:
        summary = server_summary(server)
        name = summary.get("name") or "(unnamed)"
        auth = summary.get("authStatus") or "unknown"
        counts = "tools=%d, resources=%d, templates=%d" % (
            summary.get("tools") or 0,
            summary.get("resources") or 0,
            summary.get("resourceTemplates") or 0,
        )
        if auth == "notLoggedIn":
            counts += ", login required"
        parts.append("%s (%s, %s)" % (name, auth, counts))
    suffix = "; more pages available" if response.get("nextCursor") else ""
    return "MCP status: " + "; ".join(parts) + suffix


def _request_status_page(session, detail="full", cursor=None, limit=50):
    params = status_request_params(session, detail=detail, cursor=cursor, limit=limit)
    return session._client().request("mcpServerStatus/list", params, timeout=30) or {}


def list_mcp_status(session, arg):
    words = split_words(arg)
    if len(words) > 1:
        return {"ok": False, "error": "usage: /mcp-status [full|tools]"}
    detail = normalize_detail(words[0] if words else "")
    if not detail:
        return {"ok": False, "error": "usage: /mcp-status [full|tools]"}
    response = _request_status_page(session, detail=detail)
    include_items = detail == "full"
    payload = status_detail_payload(response, include_items=include_items)
    params = status_request_params(session, detail=detail)
    emit_result_events(
        session,
        "mcp-status-%d" % int(time.time() * 1000),
        "mcpServerStatus.list",
        params,
        payload,
    )
    session._codex_notice(status_notice_message(response), "mcpServerStatus/list", payload)
    data = response.get("data") if isinstance(response, dict) else []
    return {
        "ok": True,
        "command": "mcp-status",
        "detail": detail,
        "servers": len(data or []),
        "next_cursor": response.get("nextCursor") if isinstance(response, dict) else None,
    }


def find_server(response, name):
    wanted = str(name or "").strip().lower()
    for server in (response.get("data") if isinstance(response, dict) else []) or []:
        if display_name(server).lower() == wanted:
            return server
    return None


def resource_browser_payload(server):
    return {
        "server": display_name(server),
        "authStatus": server.get("authStatus") or "unknown",
        "resources": [
            resource_summary(item) for item in (server.get("resources") or []) if isinstance(item, dict)
        ],
        "resourceTemplates": [
            resource_template_summary(item)
            for item in (server.get("resourceTemplates") or [])
            if isinstance(item, dict)
        ],
        "tools": _tools_list(server.get("tools") or {}),
    }


def resource_browser_message(payload):
    return "MCP resources for %s: %d resources, %d templates, %d tools" % (
        payload.get("server") or "(unnamed)",
        len(payload.get("resources") or []),
        len(payload.get("resourceTemplates") or []),
        len(payload.get("tools") or []),
    )


def list_mcp_resources(session, arg):
    words = split_words(arg)
    if len(words) != 1:
        return {"ok": False, "error": "usage: /mcp-resources <server>"}
    server_name = words[0]
    response = _request_status_page(session, detail="full")
    server = find_server(response, server_name)
    if not server:
        available = [display_name(item) for item in (response.get("data") or []) if display_name(item)]
        hint = "Available MCP servers: %s" % ", ".join(available) if available else "No MCP servers returned"
        return {"ok": False, "error": "MCP server not found: %s. %s" % (server_name, hint)}
    payload = resource_browser_payload(server)
    emit_result_events(
        session,
        "mcp-resources-%s-%d" % (display_name(server) or "server", int(time.time() * 1000)),
        "mcpServerStatus.resources",
        status_request_params(session, detail="full"),
        payload,
    )
    session._codex_notice(resource_browser_message(payload), "mcpServerStatus/list", payload)
    return {
        "ok": True,
        "command": "mcp-resources",
        "server": display_name(server),
        "resources": len(payload.get("resources") or []),
        "resource_templates": len(payload.get("resourceTemplates") or []),
        "tools": len(payload.get("tools") or []),
    }


def startup_status_message(params):
    if not isinstance(params, dict):
        return "MCP server status updated"
    name = str(params.get("name") or params.get("server") or "MCP server").strip()
    status = str(params.get("status") or "").strip() or "updated"
    error = str(params.get("error") or "").strip()
    if error:
        return "MCP %s: %s (%s)" % (name, status, error)
    return "MCP %s: %s" % (name, status)


def oauth_login_message(params):
    if not isinstance(params, dict):
        return "MCP OAuth login completed"
    name = str(params.get("name") or "MCP server").strip()
    success = bool(params.get("success"))
    if success:
        return "MCP OAuth login completed for %s" % name
    error = str(params.get("error") or "").strip()
    suffix = ": %s" % error if error else ""
    return "MCP OAuth login failed for %s%s. Use Codex CLI MCP login/retry if browser login is required." % (
        name,
        suffix,
    )


def compact_detail(obj, limit=1600):
    return codex_text.compact_json(obj or {}, limit=limit)
