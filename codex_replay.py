# -*- coding: utf-8 -*-
"""Timeline, replay, and pending-state helpers for CodexSession."""
import copy
import time

import work_summary


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


def stream_delta_info(event):
    if not isinstance(event, dict) or event.get("type") != "stream_event":
        return "", ""
    delta = ((event.get("event") or {}).get("delta") or {})
    field = "text" if delta.get("type") == "text_delta" else "thinking" if delta.get("type") == "thinking_delta" else ""
    if not field:
        return "", ""
    return field, delta.get(field) or ""


def _seq_value(event):
    try:
        return int((event or {}).get("seq") or 0)
    except Exception:
        return 0


def _trim_stream_chunks(chunks, max_chars):
    """Keep the newest model-emitted stream chunks up to max_chars."""
    if max_chars <= 0:
        return list(chunks or [])
    kept = []
    remaining = max_chars
    for chunk in reversed(chunks or []):
        text = str((chunk or {}).get("text") or "")
        if not text:
            continue
        if len(text) > remaining:
            text = text[-remaining:]
        kept.append({"seq": int((chunk or {}).get("seq") or 0), "text": text})
        remaining -= len(text)
        if remaining <= 0:
            break
    kept.reverse()
    return kept


def _public_event(event):
    out = copy.deepcopy(event)
    out.pop("_stream_chunks", None)
    return out


def trim_stream_event_after(event, after_seq):
    """Return only unseen stream text for merged replay events.

    Live reconnects request events after the last rendered seq. A persisted
    timeline may hold several stream chunks merged into one event, so replaying
    that whole event would duplicate text already visible in the browser.
    """
    field, _text = stream_delta_info(event)
    if not field:
        return event
    seq = _seq_value(event)
    try:
        merged_seq = int(event.get("merged_seq") or seq)
    except Exception:
        merged_seq = seq
    if seq > after_seq:
        return event
    chunks = event.get("_stream_chunks") or []
    if not chunks:
        # Old persisted timelines have no chunk map. Prefer missing a tiny
        # partial delta over duplicating a whole assistant paragraph on reconnect.
        return None if merged_seq > after_seq else event
    unseen = [chunk for chunk in chunks if _seq_value(chunk) > after_seq]
    if not unseen:
        return None
    out = copy.deepcopy(event)
    delta = ((out.get("event") or {}).get("delta") or {})
    delta[field] = "".join(str((chunk or {}).get("text") or "") for chunk in unseen)
    out["seq"] = _seq_value(unseen[0])
    out["merged_seq"] = _seq_value(unseen[-1])
    out["event_id"] = "%s-after-%d" % (event.get("event_id") or event.get("seq") or "stream", int(after_seq or 0))
    out["_stream_chunks"] = list(unseen)
    return out


def merge_timeline_event(session, out, stream_max_chars):
    typ = out.get("type")
    if typ == "stream_event":
        field, text = stream_delta_info(out)
        if not field or not text or not session.timeline:
            return False
        last = session.timeline[-1]
        last_field, last_text = stream_delta_info(last)
        if last.get("type") != "stream_event" or last_field != field:
            return False
        chunks = list(last.get("_stream_chunks") or [{"seq": _seq_value(last), "text": last_text}])
        chunks.append({"seq": _seq_value(out), "text": text})
        merged = last_text + text
        if len(merged) > stream_max_chars:
            merged = "... (stream truncated)\n" + merged[-stream_max_chars:]
            chunks = _trim_stream_chunks(chunks, stream_max_chars)
        ((last.get("event") or {}).get("delta") or {})[field] = merged
        last["_stream_chunks"] = chunks
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
    out.setdefault("ts", int(time.time() * 1000))
    if not out.get("seq"):
        seq, event_id = event_identity(session, out)
        out["seq"] = seq
        out["event_id"] = event_id
    elif not out.get("event_id"):
        out["event_id"] = "%s-%06d-%s" % (session.sid, int(out.get("seq") or 0), out.get("type") or "event")
    field, text = stream_delta_info(out)
    if field and text and not out.get("_stream_chunks"):
        out["_stream_chunks"] = [{"seq": int(out.get("seq") or 0), "text": text}]
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


def _event_has_seq(event):
    try:
        return int((event or {}).get("seq") or 0) > 0
    except Exception:
        return False


def _normalize_history_events(session, events, replay_max_events, stream_max_chars):
    clean = [dict(event) for event in events or [] if isinstance(event, dict)]
    if not clean:
        return []
    if all(_event_has_seq(event) for event in clean):
        max_seq = max(int(event.get("seq") or 0) for event in clean)
        session._next_seq = max(int(session._next_seq or 1), max_seq + 1)
        return clean
    session.timeline = []
    session._next_seq = 1
    normalized = []
    for event in clean:
        item = dict(event)
        for key in ("seq", "merged_seq", "event_id"):
            item.pop(key, None)
        recorded = record_timeline(session, item, replay_max_events, stream_max_chars)
        if recorded.get("type") not in ("replay_batch", "state_snapshot", "codex_usage"):
            normalized.append(dict(recorded))
    return normalized


def adopt_history_replay(session, events, replay_max_events, stream_max_chars=24000):
    if not events:
        return
    normalized = _normalize_history_events(session, events, replay_max_events, stream_max_chars)
    session.events = list(normalized)[-200:]
    if replay_content_score(events) > replay_content_score(session.timeline):
        session.timeline = list(normalized)[-replay_max_events:]


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
        snapshot = list(source)
    if after_seq > 0:
        snapshot = [event for event in snapshot if event_after_seq(event, after_seq)]
        snapshot = [trim_stream_event_after(event, after_seq) for event in snapshot]
        snapshot = [event for event in snapshot if event]
    return [_public_event(event) for event in snapshot]


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


def _work_replay_events(session):
    with session._lock:
        snapshot = list(session.timeline or session.events)
    return [_public_event(event) for event in snapshot]


def replay_payload(session, after_seq=0, view=None, turn=None):
    state = session._state_snapshot()
    if isinstance(state, dict):
        cfg_model = (getattr(session, "cfg", None) or {}).get("model") or ""
        state["model"] = getattr(session, "model", "") or cfg_model
        state["cwd"] = str(getattr(session, "cwd", "") or "")
    pending = session._pending_events_snapshot()
    view = str(view or "").lower()
    if view == "work":
        return work_summary.replay_payload(_work_replay_events(session), state, pending)
    if view in ("turn", "work_turn", "chat_turn"):
        return work_summary.turn_events_payload(_work_replay_events(session), state, pending, turn=turn)
    return {
        "ok": True,
        "events": session._events_after_seq(after_seq),
        "snapshot": state,
        "pending": pending,
        "last_seq": state.get("last_seq") or 0,
    }
