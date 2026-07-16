# -*- coding: utf-8 -*-
"""Routing helpers for Codex app-server notifications and requests."""
import copy


def thread_id_from_params(params):
    if not isinstance(params, dict):
        return None
    if params.get("threadId"):
        return params.get("threadId")
    thread = params.get("thread")
    if isinstance(thread, dict):
        return thread.get("id") or thread.get("sessionId")
    turn = params.get("turn")
    if isinstance(turn, dict):
        if turn.get("threadId"):
            return turn.get("threadId")
        thread = turn.get("thread")
        if isinstance(thread, dict):
            return thread.get("id") or thread.get("sessionId")
    item = params.get("item")
    if isinstance(item, dict):
        if item.get("threadId"):
            return item.get("threadId")
        turn = item.get("turn")
        if isinstance(turn, dict):
            return turn.get("threadId")
    return None


def turn_id_from_params(params):
    if not isinstance(params, dict):
        return None
    if params.get("turnId"):
        return params.get("turnId")
    turn = params.get("turn")
    if isinstance(turn, dict):
        return turn.get("id") or turn.get("turnId")
    item = params.get("item")
    if isinstance(item, dict):
        return item.get("turnId")
    return None


def item_id_from_params(params):
    if not isinstance(params, dict):
        return None
    if params.get("itemId"):
        return params.get("itemId")
    item = params.get("item")
    if isinstance(item, dict):
        return item.get("id") or item.get("itemId")
    return None


def route_ids(params):
    return thread_id_from_params(params), turn_id_from_params(params), item_id_from_params(params)


def session_from_params(params, sessions, turn_sessions, item_sessions):
    thread_id, turn_id, item_id = route_ids(params)
    if thread_id and thread_id in sessions:
        return sessions.get(thread_id)
    if turn_id and turn_id in turn_sessions:
        return turn_sessions.get(turn_id)
    if item_id and item_id in item_sessions:
        return item_sessions.get(item_id)
    return None


def has_route_hint(params):
    return bool(thread_id_from_params(params) or turn_id_from_params(params) or item_id_from_params(params))


def remember_item_route(params, session, sessions, turn_sessions, item_sessions):
    thread_id, turn_id, item_id = route_ids(params)
    if thread_id:
        sessions[thread_id] = session
    if turn_id:
        turn_sessions[turn_id] = session
    if item_id:
        item_sessions[item_id] = session
    return thread_id, turn_id, item_id


def single_busy_session(sessions):
    seen = set()
    busy = []
    for session in list(sessions.values()):
        marker = id(session)
        if marker in seen:
            continue
        seen.add(marker)
        if getattr(session, "_busy", False) and not getattr(session, "_closed", False):
            busy.append(session)
    return busy[0] if len(busy) == 1 else None


def unrouted_entry(method, params, now):
    thread_id, turn_id, item_id = route_ids(params)
    return {
        "method": method,
        "params": copy.deepcopy(params),
        "ts": now,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "item_id": item_id,
    }


def buffered_unrouted(events, entry, now, ttl, max_events):
    kept = [event for event in events or [] if now - float(event.get("ts") or 0) < ttl]
    kept.append(entry)
    return kept[-max_events:]


def split_unrouted_for_session(events, session, thread_id=None, turn_id=None, item_id=None,
                               now=0.0, ttl=10.0, max_events=120):
    keep = []
    replay = []
    for entry in events or []:
        matched = (
            (thread_id and entry.get("thread_id") == thread_id)
            or (turn_id and entry.get("turn_id") == turn_id)
            or (item_id and entry.get("item_id") == item_id)
            or (entry.get("thread_id") and entry.get("thread_id") == getattr(session, "thread_id", None))
        )
        if matched:
            replay.append(entry)
        elif now - float(entry.get("ts") or 0) < ttl:
            keep.append(entry)
    return keep[-max_events:], replay
