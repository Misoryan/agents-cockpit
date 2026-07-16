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
    return {
        "thread": thread,
        "events": events_from_thread(thread)[-200:],
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
