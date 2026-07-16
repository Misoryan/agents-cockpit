# -*- coding: utf-8 -*-
"""Codex thread history normalization and local cache helpers."""
import json
import os
import time


def epoch(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    if value > 100000000000:
        value = value / 1000.0
    return value


def thread_id(thread):
    if not isinstance(thread, dict):
        return ""
    return thread.get("id") or thread.get("sessionId") or ""


def thread_title(thread):
    if not isinstance(thread, dict):
        return "(Untitled)"
    return (thread.get("name") or thread.get("preview") or thread.get("agentNickname")
            or thread_id(thread) or "(Untitled)")


def thread_history_item(thread, archived=False):
    tid = thread_id(thread)
    if not tid:
        return None
    return {
        "session_id": tid,
        "thread_id": tid,
        "cwd": thread.get("cwd") or os.path.expanduser("~"),
        "ts": epoch(thread.get("recencyAt") or thread.get("updatedAt") or thread.get("createdAt")),
        "title": thread_title(thread),
        "originator": thread.get("source") or "",
        "backend": "codex_native",
        "provider": "codex",
        "archived": bool(archived),
    }


def history_cache_path(state_dir=None, default_state_dir=None):
    return os.path.join(state_dir or default_state_dir or ".", "codex_history_cache.json")


def local_thread_history_items(state_dir=None, default_state_dir=None):
    state_dir = state_dir or default_state_dir or "."
    try:
        names = os.listdir(state_dir)
    except OSError:
        return []
    out = []
    for name in names:
        if not name.startswith("codex_s") or not name.endswith(".json"):
            continue
        path = os.path.join(state_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        tid = data.get("thread_id")
        if not tid:
            continue
        cwd = data.get("cwd") or os.path.expanduser("~")
        try:
            ts = os.path.getmtime(path)
        except OSError:
            ts = time.time()
        out.append({
            "session_id": tid,
            "thread_id": tid,
            "cwd": cwd,
            "ts": ts,
            "title": os.path.basename(str(cwd).rstrip("\\/")) or cwd or "(Untitled)",
            "originator": "local",
            "backend": "codex_native",
            "provider": "codex",
            "archived": False,
        })
    return out


def filter_thread_history_items(items, limit=60, search=None):
    merged = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = item.get("thread_id") or item.get("session_id")
        if not key:
            continue
        prev = merged.get(key)
        if prev is None or (item.get("ts") or 0) >= (prev.get("ts") or 0):
            merged[key] = dict(item)
    query = (search or "").strip().lower()
    out = []
    for item in sorted(merged.values(), key=lambda value: value.get("ts") or 0, reverse=True):
        if query:
            haystack = " ".join(str(item.get(key) or "") for key in ("title", "cwd", "session_id", "thread_id")).lower()
            if query not in haystack:
                continue
        out.append(item)
        if len(out) >= max(1, int(limit or 60)):
            break
    return out


def read_thread_history_cache(limit=60, archived=False, search=None, state_dir=None, default_state_dir=None):
    if archived:
        return []
    items = []
    try:
        with open(history_cache_path(state_dir, default_state_dir), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    cached = data.get("items") if isinstance(data, dict) else data
    if isinstance(cached, list):
        items.extend(cached)
    items.extend(local_thread_history_items(state_dir=state_dir, default_state_dir=default_state_dir))
    return filter_thread_history_items(items, limit=limit, search=search)


def write_thread_history_cache(items, state_dir=None, default_state_dir=None):
    try:
        target_dir = state_dir or default_state_dir or "."
        os.makedirs(target_dir, exist_ok=True)
        with open(history_cache_path(state_dir, default_state_dir), "w", encoding="utf-8") as handle:
            json.dump({"updated_at": time.time(), "items": list(items or [])[:500]}, handle, ensure_ascii=False)
    except OSError:
        pass
