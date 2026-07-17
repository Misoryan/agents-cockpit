# -*- coding: utf-8 -*-
"""Internal manager endpoints used by gate MCP and web control calls."""
import os
import threading
import time


INTERNAL_GATE_POSTS = {"/api/_perm_gate", "/api/_ask_gate"}
INTERNAL_CONTROL_POSTS = {"/api/_exit", "/api/_soft_exit"}
INTERNAL_POST_ROUTE_RISKS = {
    "/api/_perm_gate": {
        "risk": "critical",
        "area": "internal_approval_gate",
        "guards": ("internal_auth", "optional_user_context", "session_owner"),
    },
    "/api/_ask_gate": {
        "risk": "critical",
        "area": "internal_answer_gate",
        "guards": ("internal_auth", "optional_user_context", "session_owner"),
    },
    "/api/_exit": {
        "risk": "critical",
        "area": "internal_control",
        "guards": ("internal_auth", "control_route_only"),
    },
    "/api/_soft_exit": {
        "risk": "critical",
        "area": "internal_control",
        "guards": ("internal_auth", "control_route_only"),
    },
}


def internal_post_risk(path):
    return INTERNAL_POST_ROUTE_RISKS.get(path)


def post_context(handler, path):
    if path in INTERNAL_GATE_POSTS:
        return handler._ctx(required=False)
    if path in INTERNAL_CONTROL_POSTS:
        return None
    return handler._ctx(required=True)


def native_from_payload(data, ctx, owned_session_fn):
    sid = (data.get("sid") or "").strip()
    session = owned_session_fn(sid, ctx)
    return sid, session, (session.get("native") if session else None)


def handle_gate(handler, path, data, ctx, native_from_payload_fn):
    if path == "/api/_perm_gate":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        if not native:
            handler._json({"behavior": "deny", "message": "session not found"}, 404)
            return True
        allow, msg = native.await_permission(data.get("tool_use_id") or "",
                                             data.get("tool_name") or "",
                                             data.get("input") or {})
        if allow:
            handler._json({"behavior": "allow", "updatedInput": data.get("input") or {}})
        else:
            handler._json({"behavior": "deny", "message": msg or "user denied"})
        return True
    if path == "/api/_ask_gate":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        if not native:
            handler._json({"answer": "(session not found)"}, 404)
            return True
        answer = native.await_answer(data.get("tool_use_id") or "",
                                     data.get("question") or "",
                                     data.get("questions"))
        handler._json({"answer": answer})
        return True
    return False


def handle_control(handler, path, kill_all_fn, persist_sessions_fn):
    if path == "/api/_exit":
        def _die():
            time.sleep(0.25)
            kill_all_fn()
            os._exit(0)
        threading.Thread(target=_die, daemon=True).start()
        handler._json({"ok": True, "restarting": True})
        return True
    if path == "/api/_soft_exit":
        def _soft_die():
            time.sleep(0.25)
            persist_sessions_fn()
            os._exit(0)
        threading.Thread(target=_soft_die, daemon=True).start()
        handler._json({"ok": True, "restarting": True, "soft": True})
        return True
    return False
