# -*- coding: utf-8 -*-
"""Codex history/item conversion helpers for browser replay events."""
import os
import time

import codex_text


def tool_event_from_item(item, cwd="", os_name=None, now_ms=None):
    typ = item.get("type")
    item_id = item.get("id") or ("item-%d" % int(now_ms if now_ms is not None else time.time() * 1000))
    os_name = os.name if os_name is None else os_name
    if typ == "commandExecution":
        command = item.get("command") or ""
        name = "PowerShell" if os_name == "nt" else "Bash"
        inp = {"command": command, "cwd": item.get("cwd") or cwd}
    elif typ == "fileChange":
        changes = item.get("changes") or []
        inp = {"file_path": ", ".join(change.get("path", "") for change in changes if isinstance(change, dict)),
               "changes": changes}
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
        return codex_text.plan_text_event(item.get("text") or codex_text.extract_text(item))
    elif typ in ("agentMessage", "reasoning", "userMessage"):
        return None
    else:
        name = typ or "CodexItem"
        inp = item
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": item_id, "name": name, "input": inp}
    ]}}


def tool_result_from_item(item):
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
        if item.get("durationMs") is not None:
            pieces.append("duration ms: %s" % item.get("durationMs"))
        text = "\n".join(pieces).strip()
    elif typ == "fileChange":
        text = codex_text.changes_to_diff(item.get("changes") or [])
        if item.get("status"):
            text = (text + "\n\nstatus: " + item.get("status")).strip()
    elif typ == "mcpToolCall":
        text = codex_text.json_text(item.get("result") or item.get("error") or {})
    elif typ == "dynamicToolCall":
        text = codex_text.json_text(item.get("contentItems") or {"success": item.get("success")})
    elif typ in ("webSearch", "imageGeneration", "imageView", "sleep", "contextCompaction"):
        text = codex_text.json_text(item)
    else:
        return None
    block = {"type": "tool_result", "tool_use_id": item_id, "content": text}
    if typ == "commandExecution":
        if item.get("exitCode") is not None:
            block["exit_code"] = item.get("exitCode")
        if item.get("durationMs") is not None:
            block["duration_ms"] = item.get("durationMs")
        if item.get("aggregatedOutput"):
            block["aggregated_output"] = item.get("aggregatedOutput")
    return {"type": "user", "message": {"content": [block]}}
