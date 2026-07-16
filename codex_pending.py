# -*- coding: utf-8 -*-
"""Codex pending approval/input/form helpers."""
import codex_replay


def has_pending(session):
    with session._pending_lock:
        return bool(session._pending)


def clear_pending(session):
    """Wake pending app-server request waiters and clear the pending map."""
    with session._pending_lock:
        had_pending = bool(session._pending)
        for entry in session._pending.values():
            try:
                entry["event"].set()
            except Exception:
                pass
        session._pending.clear()
    return had_pending


def approve(session, tool_use_id, allow, always=False):
    with session._pending_lock:
        entry = session._pending.get(tool_use_id)
    if not entry or entry.get("kind") != "approve":
        return False
    entry["allow"] = bool(allow)
    entry["always"] = bool(always)
    entry["event"].set()
    session._broadcast({"type": "approval_decision", "tool_use_id": tool_use_id, "allow": bool(allow)})
    if always and allow:
        session._broadcast({"type": "auto_allow_added", "tool": entry.get("method") or "Codex"})
    return True


def answer(session, tool_use_id, ans):
    with session._pending_lock:
        entry = session._pending.get(tool_use_id)
    if not entry or entry.get("kind") not in ("ask", "form"):
        return False
    entry["answer"] = ans if ans is not None else ""
    entry["event"].set()
    session._broadcast({
        "type": "form_answered" if entry.get("kind") == "form" else "ask_answered",
        "tool_use_id": tool_use_id,
    })
    return True


def state_snapshot(session):
    with session._pending_lock:
        pending = list(session._pending.items())
    return codex_replay.state_snapshot(session, pending)


def pending_events_snapshot(session):
    with session._pending_lock:
        pending = list(session._pending.items())
        terminals = [dict(value) for value in session._terminal_processes.values()]
    return codex_replay.pending_events_snapshot(pending) + terminals
