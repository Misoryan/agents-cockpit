# -*- coding: utf-8 -*-
"""Replay identity and snapshot helpers for Claude NativeSession."""
import time

import work_summary


def seq_value(obj):
    try:
        return int((obj or {}).get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def last_seq(session):
    return max(0, int(session._next_seq) - 1)


def decorate_event(session, obj):
    event = dict(obj or {})
    seq = seq_value(event)
    if seq <= 0:
        seq = session._next_seq
        event["seq"] = seq
    else:
        event["seq"] = seq
    if seq >= session._next_seq:
        session._next_seq = seq + 1
    if not event.get("event_id"):
        event["event_id"] = "%s:%d" % (session.sid, seq)
    return event


def record_event(session, obj, limit=200, stamp=True):
    event = decorate_event(session, obj)
    if stamp:
        event.setdefault("ts", int(time.time() * 1000))
    session.events.append(event)
    if len(session.events) > limit:
        session.events = session.events[-limit:]
    return event


def _event_ts_seconds(event):
    try:
        value = float((event or {}).get("ts") or 0)
    except (TypeError, ValueError):
        return 0
    if value > 100000000000:
        value = value / 1000.0
    return value if value > 0 else 0


def completion_ts_from_events(events):
    for event in reversed(list(events or [])):
        if not isinstance(event, dict):
            continue
        if event.get("type") not in ("result", "interrupted", "rate_limited"):
            continue
        ts = _event_ts_seconds(event)
        if ts:
            return ts
    return 0


def events_after_seq(session, after_seq=0):
    try:
        after = int(after_seq or 0)
    except (TypeError, ValueError):
        after = 0
    if after <= 0:
        return list(session.events)
    return [event for event in session.events if seq_value(event) > after]


def load_events(session, events, next_seq=None):
    session.events = []
    session._next_seq = 1
    for event in events or []:
        if isinstance(event, dict):
            record_event(session, event, stamp=False)
    try:
        stored_next = int(next_seq or 0)
    except (TypeError, ValueError):
        stored_next = 0
    if stored_next > session._next_seq:
        session._next_seq = stored_next


def pending_events_snapshot(pending_items):
    events = []
    for tool_use_id, entry in pending_items:
        kind = entry.get("kind")
        if kind == "approve":
            events.append({"type": "pending_approval",
                           "tool_use_id": tool_use_id,
                           "name": entry.get("tool") or "Approval",
                           "input": entry.get("input") or {},
                           "preview": entry.get("preview") or "",
                           "danger": bool(entry.get("danger"))})
        elif kind == "ask":
            events.append({"type": "pending_ask",
                           "tool_use_id": tool_use_id,
                           "question": entry.get("question") or "",
                           "questions": entry.get("questions") or []})
    return events


def replay_payload(session, events, pending, model="", after_seq=0, state_fn=None, view=None, turn=None):
    last = last_seq(session)
    state = state_fn() if state_fn else "idle"
    turn_started_at = getattr(session, "current_turn_started_at", None) if getattr(session, "_busy", False) else None
    now_ms = time.time() * 1000
    snapshot = {
        "type": "state_snapshot",
        "state": state,
        "model": model or "",
        "cwd": str(getattr(session, "cwd", "") or ""),
        "running": bool(session._busy),
        "plan": bool(session.plan_mode),
        "task": bool(session.task_mode),
        "pending": [{"id": event.get("tool_use_id"), "kind": event.get("type")} for event in pending],
        "last_seq": last,
        "turn_started_at": turn_started_at,
        "turn_started_at_ms": int(turn_started_at * 1000) if turn_started_at else None,
        "turn_elapsed_ms": int(now_ms - turn_started_at * 1000) if turn_started_at else None,
        "server_now_ms": int(now_ms),
    }
    pending_events = ([{"type": "system", "model": model}] if model and not after_seq else []) + pending
    view = str(view or "").lower()
    if view == "work":
        return work_summary.replay_payload_cached(session, lambda: events, snapshot, pending)
    if view in ("turn", "work_turn", "chat_turn"):
        return work_summary.turn_events_payload(events, snapshot, pending, turn=turn)
    return {
        "ok": True,
        "events": events,
        "snapshot": snapshot,
        "pending": pending_events,
        "last_seq": last,
    }
