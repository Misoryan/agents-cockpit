# -*- coding: utf-8 -*-
"""Timeline, replay, and pending-state helpers for CodexSession."""
import time


def is_dangerous(text):
    value = str(text or "").lower()
    return any(word in value for word in ("rm -rf", "rmdir", "del /f", "format ",
                                          "shutdown", "reg delete", "mkfs"))


def event_identity(session, obj):
    seq = session._next_seq
    session._next_seq += 1
    typ = obj.get("type") or "event"
    key = obj.get("tool_use_id") or obj.get("turn_id") or obj.get("event_id")
    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    if not key and isinstance(msg, dict):
        key = msg.get("uuid") or msg.get("id")
        blocks = msg.get("content") or []
        if not key and isinstance(blocks, list) and blocks:
            first = blocks[0] or {}
            key = first.get("id") or first.get("tool_use_id") or first.get("type")
    return seq, "%s-%06d-%s" % (session.sid, seq, str(key or typ))


def tool_result_id(event):
    if not isinstance(event, dict) or event.get("type") != "user":
        return ""
    blocks = ((event.get("message") or {}).get("content") or [])
    if not isinstance(blocks, list) or not blocks:
        return ""
    first = blocks[0] or {}
    if first.get("type") != "tool_result":
        return ""
    return str(first.get("tool_use_id") or "")


def merge_timeline_event(session, out, stream_max_chars):
    typ = out.get("type")
    if typ == "stream_event":
        delta = ((out.get("event") or {}).get("delta") or {})
        field = "text" if delta.get("type") == "text_delta" else "thinking" if delta.get("type") == "thinking_delta" else ""
        if not field or not delta.get(field) or not session.timeline:
            return False
        last = session.timeline[-1]
        last_delta = ((last.get("event") or {}).get("delta") or {})
        if last.get("type") != "stream_event" or last_delta.get("type") != delta.get("type"):
            return False
        merged = (last_delta.get(field) or "") + (delta.get(field) or "")
        if len(merged) > stream_max_chars:
            merged = "... (stream truncated)\n" + merged[-stream_max_chars:]
        last_delta[field] = merged
        last["merged_seq"] = out.get("seq")
        return True
    tool_id = tool_result_id(out)
    if not tool_id:
        return False
    for prev in reversed(session.timeline[-80:]):
        if tool_result_id(prev) == tool_id:
            prev["message"] = out.get("message")
            prev["merged_seq"] = out.get("seq")
            return True
    return False


def record_timeline(session, obj, replay_max_events, stream_max_chars):
    if obj.get("type") in ("replay_batch", "state_snapshot", "codex_usage"):
        return obj
    out = dict(obj)
    if not out.get("seq"):
        seq, event_id = event_identity(session, out)
        out["seq"] = seq
        out["event_id"] = event_id
    elif not out.get("event_id"):
        out["event_id"] = "%s-%06d-%s" % (session.sid, int(out.get("seq") or 0), out.get("type") or "event")
    if merge_timeline_event(session, out, stream_max_chars):
        return out
    session.timeline.append(out)
    if len(session.timeline) > replay_max_events:
        session.timeline = session.timeline[-replay_max_events:]
    return out


def replay_content_score(events):
    """Score replay usefulness; mode/notices alone are not conversation history."""
    score = 0
    for event in events or []:
        if not isinstance(event, dict):
            continue
        typ = event.get("type")
        if typ in ("assistant", "user", "result", "stream_event", "interrupted"):
            score += 1
        elif typ in ("pending_approval", "pending_ask", "pending_form", "compacted"):
            score += 1
    return score


def drop_recover_noise(events):
    out = []
    for event in events or []:
        if (
            isinstance(event, dict)
            and event.get("type") == "result"
            and "Codex app-server exited" in str(event.get("error") or "")
        ):
            continue
        out.append(event)
    return out


def adopt_history_replay(session, events, replay_max_events):
    if not events:
        return
    session.events = list(events)[-200:]
    if replay_content_score(events) > replay_content_score(session.timeline):
        session.timeline = list(events)[-replay_max_events:]


def event_after_seq(event, after_seq):
    try:
        seq = int(event.get("seq") or 0)
        merged = int(event.get("merged_seq") or 0)
    except Exception:
        return after_seq <= 0
    return seq > after_seq or merged > after_seq


def events_after_seq(session, after_seq=0):
    try:
        after_seq = int(after_seq or 0)
    except Exception:
        after_seq = 0
    with session._lock:
        source = session.poll_events if after_seq > 0 and session.poll_events else (session.timeline or session.events)
        snapshot = [dict(event) for event in source]
    if after_seq > 0:
        snapshot = [event for event in snapshot if event_after_seq(event, after_seq)]
    return snapshot


def state_snapshot(session, pending_items, now_fn=None):
    now_fn = now_fn or time.time
    pending = [{"id": req_id, "kind": entry.get("kind")} for req_id, entry in pending_items]
    turn_started_at = session.current_turn_started_at if session._busy else None
    turn_elapsed_ms = None
    now = now_fn()
    if turn_started_at:
        turn_elapsed_ms = max(0, int((now - turn_started_at) * 1000))
    return {
        "type": "state_snapshot",
        "state": session.state(),
        "running": bool(session._busy),
        "plan": bool(session.plan_mode),
        "task": bool(session.task_mode),
        "pending": pending,
        "last_seq": max(0, int(session._next_seq or 1) - 1),
        "turn_started_at": turn_started_at,
        "turn_started_at_ms": int(turn_started_at * 1000) if turn_started_at else None,
        "turn_elapsed_ms": turn_elapsed_ms,
        "server_now_ms": int(now * 1000),
        "route_debug": session._route_debug[-10:],
    }


def pending_events_snapshot(pending_items):
    events = []
    for req_id, entry in pending_items:
        kind = entry.get("kind")
        if kind == "approve":
            events.append({
                "type": "pending_approval",
                "tool_use_id": req_id,
                "name": entry.get("name") or entry.get("method") or "Approval",
                "input": entry.get("params") or {},
                "preview": entry.get("preview") or "",
                "danger": bool(entry.get("danger")),
            })
        elif kind == "ask":
            event = {
                "type": "pending_ask",
                "tool_use_id": req_id,
                "question": entry.get("question") or "",
                "questions": entry.get("questions") or [],
            }
            if entry.get("auto_resolution_ms") is not None:
                event["auto_resolution_ms"] = entry.get("auto_resolution_ms")
            events.append(event)
        elif kind == "form":
            events.append({
                "type": "pending_form",
                "tool_use_id": req_id,
                "message": entry.get("message") or "Codex requests form input",
                "mode": (entry.get("params") or {}).get("mode") or "form",
                "server_name": (entry.get("params") or {}).get("serverName") or "",
                "fields": entry.get("fields") or [],
                "schema_detail": entry.get("schema_detail") or "",
            })
    return events


def replay_payload(session, after_seq=0):
    state = session._state_snapshot()
    return {
        "ok": True,
        "events": session._events_after_seq(after_seq),
        "snapshot": state,
        "pending": session._pending_events_snapshot(),
        "last_seq": state.get("last_seq") or 0,
    }
