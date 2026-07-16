# -*- coding: utf-8 -*-
"""Codex terminal-interaction adapter helpers."""
import base64


UNKNOWN_PROCESS = {"ok": False, "error": "unknown terminal process"}


def terminal_interaction_event(session, params):
    params = params or {}
    process_id = str(params.get("processId") or "").strip()
    if not process_id:
        return None
    item_id = str(params.get("itemId") or "")
    event = {
        "type": "terminal_interaction",
        "process_id": process_id,
        "item_id": item_id,
        "stdin": str(params.get("stdin") or ""),
    }
    with session._pending_lock:
        session._terminal_processes[process_id] = dict(event)
    return event


def terminal_known(session, process_id):
    process_id = str(process_id or "").strip()
    if not process_id:
        return ""
    with session._pending_lock:
        return process_id if process_id in session._terminal_processes else ""


def terminal_write(session, process_id, text="", close_stdin=False):
    process_id = terminal_known(session, process_id)
    if not process_id:
        return dict(UNKNOWN_PROCESS)
    params = {"processId": process_id}
    text = "" if text is None else str(text)
    if text:
        params["deltaBase64"] = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if close_stdin:
        params["closeStdin"] = True
    session._client().request("command/exec/write", params, timeout=15)
    if close_stdin:
        with session._pending_lock:
            session._terminal_processes.pop(process_id, None)
        session._record_and_broadcast({"type": "terminal_closed", "process_id": process_id})
    else:
        session._broadcast({"type": "terminal_input_sent", "process_id": process_id})
    return {"ok": True, "process_id": process_id, "closed": bool(close_stdin)}


def terminal_terminate(session, process_id):
    process_id = terminal_known(session, process_id)
    if not process_id:
        return dict(UNKNOWN_PROCESS)
    session._client().request("command/exec/terminate", {"processId": process_id}, timeout=15)
    with session._pending_lock:
        session._terminal_processes.pop(process_id, None)
    session._record_and_broadcast({"type": "terminal_closed", "process_id": process_id, "terminated": True})
    return {"ok": True, "process_id": process_id, "terminated": True}


def terminal_resize(session, process_id, cols, rows):
    process_id = terminal_known(session, process_id)
    if not process_id:
        return dict(UNKNOWN_PROCESS)
    try:
        cols = max(1, int(cols))
        rows = max(1, int(rows))
    except Exception:
        return {"ok": False, "error": "invalid terminal size"}
    session._client().request(
        "command/exec/resize",
        {"processId": process_id, "size": {"cols": cols, "rows": rows}},
        timeout=15,
    )
    return {"ok": True, "process_id": process_id, "cols": cols, "rows": rows}
