# -*- coding: utf-8 -*-
"""Codex thread history conversion and live app-server history helpers."""
import os

import codex_events
import codex_history
import codex_text


def events_from_thread(thread):
    thread = thread or {}
    cwd = thread.get("cwd") or os.path.expanduser("~")
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
                text = codex_text.text_from_user_input(item.get("content") or [])
                if text:
                    events.append({"type": "user", "message": {"role": "user", "content": text}})
            elif typ == "agentMessage":
                text = item.get("text") or ""
                if text:
                    events.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
            elif typ == "plan":
                event = codex_text.plan_text_event(item.get("text") or codex_text.extract_text(item))
                if event:
                    events.append(event)
            elif typ == "reasoning":
                text = "\n".join((item.get("summary") or []) + (item.get("content") or []))
                if text:
                    events.append({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": text}]}})
            else:
                event = codex_events.tool_event_from_item(item, cwd=cwd)
                if event:
                    events.append(event)
                result = codex_events.tool_result_from_item(item)
                if result:
                    events.append(result)
        if len(events) > before:
            result_event = {"type": "result", "duration_ms": turn.get("durationMs")}
            if turn.get("status") == "failed" or turn.get("error"):
                result_event["error"] = codex_text.compact_json(turn.get("error") or "Codex turn failed")
                result_event["is_error"] = True
            events.append(result_event)
    return events


def snapshot_from_thread(thread):
    thread = thread or {}
    events = events_from_thread(thread)
    return {
        "thread": thread,
        "events": events,
        "cwd": thread.get("cwd") or os.path.expanduser("~"),
        "title": codex_history.thread_title(thread),
    }


def history_snapshot(thread_id, user="", uid="", state_dir=None, codex_home=None,
                     get_client_fn=None):
    client = get_client_fn(user=user, uid=uid, state_dir=state_dir, codex_home=codex_home)
    response = client.request(
        "thread/read",
        {"threadId": thread_id, "includeTurns": True},
        timeout=30,
    )
    thread = (response or {}).get("thread") or {}
    return snapshot_from_thread(thread)


def history_action(thread_id, action, name="", objective="", status="", user="", uid="",
                   state_dir=None, codex_home=None, get_client_fn=None):
    thread_id = str(thread_id or "").strip()
    action = str(action or "").strip().lower()
    if not thread_id:
        return {"ok": False, "error": "missing thread_id"}
    client = get_client_fn(user=user, uid=uid, state_dir=state_dir, codex_home=codex_home)
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


def list_thread_history(limit=60, archived=False, search=None, user="", uid="", state_dir=None,
                        codex_home=None, live=True, codex_enabled=True, get_client_fn=None,
                        default_state_dir=None):
    if not live or not codex_enabled:
        return codex_history.read_thread_history_cache(
            limit=limit, archived=archived, search=search,
            state_dir=state_dir, default_state_dir=default_state_dir)
    params = {
        "limit": max(1, int(limit or 60)),
        "archived": bool(archived),
        "sortKey": "recency_at",
        "sortDirection": "desc",
    }
    if search:
        params["searchTerm"] = search
    try:
        response = get_client_fn(user=user, uid=uid, state_dir=state_dir, codex_home=codex_home).request(
            "thread/list", params, timeout=30)
    except Exception:
        cached = codex_history.read_thread_history_cache(
            limit=limit, archived=archived, search=search,
            state_dir=state_dir, default_state_dir=default_state_dir)
        if cached:
            return cached
        raise
    data = (response or {}).get("data") or (response or {}).get("threads") or []
    out = []
    for thread in data:
        item = codex_history.thread_history_item(thread, archived=archived)
        if item:
            out.append(item)
    if not archived and not search:
        codex_history.write_thread_history_cache(out, state_dir=state_dir, default_state_dir=default_state_dir)
    return out


def delete_thread(thread_id, user="", uid="", state_dir=None, codex_home=None, get_client_fn=None):
    if not thread_id:
        return False
    get_client_fn(user=user, uid=uid, state_dir=state_dir, codex_home=codex_home).request(
        "thread/delete", {"threadId": thread_id}, timeout=30)
    return True
