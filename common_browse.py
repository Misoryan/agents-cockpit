# -*- coding: utf-8 -*-
"""Folder browsing and session-list projection helpers."""
import os


def _event_ts_seconds(event):
    try:
        value = float((event or {}).get("ts") or 0)
    except (TypeError, ValueError):
        return 0
    if value > 100000000000:
        value = value / 1000.0
    return value if value > 0 else 0


def _completion_ts_from_events(events):
    for event in reversed(list(events or [])):
        if not isinstance(event, dict):
            continue
        if event.get("type") not in ("result", "interrupted", "rate_limited"):
            continue
        ts = _event_ts_seconds(event)
        if ts:
            return ts
    return 0


def _session_completed_at(ns, session):
    value = getattr(ns, "last_completed_at", None) if ns else session.get("last_completed_at")
    try:
        if value:
            return float(value)
    except (TypeError, ValueError):
        pass
    if ns:
        for source in (getattr(ns, "timeline", None), getattr(ns, "events", None)):
            ts = _completion_ts_from_events(source)
            if ts:
                return ts
    return 0


def parent_of(path):
    if not path:
        return ""
    parent = os.path.dirname(path)
    return "" if parent == path else parent


def browse(path, user=None, workspace_overview_fn=None, path_allowed_fn=None):
    if not path:
        if user and workspace_overview_fn:
            roots = workspace_overview_fn(user)
            return {"path": "", "parent": "", "entries": roots, "roots": roots}
        drives = []
        for idx in range(26):
            letter = chr(ord("A") + idx)
            drive = letter + ":\\"
            if os.path.isdir(drive):
                drives.append({"name": letter + ":", "path": drive})
        return {"path": "", "parent": "", "entries": drives}
    path = os.path.abspath(path)
    if user and path_allowed_fn and not path_allowed_fn(user, path):
        return {"error": "path is outside this user's workspaces", "path": path}
    if not os.path.isdir(path):
        return {"error": "not a directory", "path": path}
    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        entries.append({"name": entry.name, "path": entry.path})
                except OSError:
                    pass
    except OSError as exc:
        return {"error": str(exc), "path": path}
    entries.sort(key=lambda item: item["name"].lower())
    parent = parent_of(path)
    if user and parent and path_allowed_fn and not path_allowed_fn(user, parent):
        parent = ""
    return {"path": path, "parent": parent, "entries": entries}


def session_obj(sid, session, host="", normalize_backend_fn=None, is_codex_backend_fn=None):
    ns = session.get("native")
    backend = session.get("backend") or (normalize_backend_fn("") if normalize_backend_fn else "")
    provider = session.get("provider")
    if not provider:
        provider = "codex" if (is_codex_backend_fn and is_codex_backend_fn(backend)) else "claude"
    session_id = getattr(ns, "claude_sid", None) or getattr(ns, "thread_id", None) or session.get("session_id")
    state = ns.state() if ns else "idle"
    last_completed_at = _session_completed_at(ns, session)
    last_activity = getattr(ns, "last_activity", 0) if ns else 0
    if state in ("running", "confirm", "plan"):
        last_output_ts = last_activity
    else:
        last_output_ts = last_completed_at
    return {
        "sid": sid,
        "dir": session["dir"],
        "title": getattr(ns, "convo_title", None) or session["title"],
        "mode": session["mode"],
        "session_id": session_id,
        "thread_id": getattr(ns, "thread_id", None) or session.get("thread_id"),
        "started": session["started"],
        "session_path": "/t/%s/" % sid,
        "backend": backend,
        "provider": provider,
        "native": True,
        "state": state,
        "yolo": bool(getattr(ns, "yolo", False) if ns else session.get("yolo")),
        "current_turn_started_at": getattr(ns, "current_turn_started_at", None) if ns else session.get("current_turn_started_at"),
        "last_completed_at": last_completed_at,
        "last_input_ts": last_activity,
        "last_output_ts": last_output_ts,
        "cols": 0,
        "rows": 0,
    }
