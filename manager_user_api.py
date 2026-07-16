# -*- coding: utf-8 -*-
"""Browser-facing manager API handlers."""
import os
import urllib.parse

import common
import manager_sessions
from codex_native import CodexSession


def handle_get(handler, path, pr, ctx, owned_session_fn):
    if path == "/api/browse":
        query = urllib.parse.parse_qs(pr.query)
        handler._json(common.browse(query.get("path", [""])[0], user=ctx.get("user")))
    elif path == "/api/sessions":
        handler._json({"sessions": manager_sessions.session_items_for_user(
            ctx.get("user"), handler.headers.get("Host", ""))})
    elif path == "/api/nreplay":
        query = urllib.parse.parse_qs(pr.query)
        sid = (query.get("sid", [""])[0] or "").strip()
        try:
            after_seq = int(query.get("after", ["0"])[0] or 0)
        except Exception:
            after_seq = 0
        session = owned_session_fn(sid, ctx)
        if not session or not session.get("native"):
            handler._json({"ok": False, "error": "native session not found"}, 404)
            return
        native = session.get("native")
        if hasattr(native, "replay_payload"):
            handler._json(native.replay_payload(after_seq=after_seq))
        else:
            handler._json({"ok": False, "error": "replay not supported"}, 501)
    elif path == "/api/history":
        query = urllib.parse.parse_qs(pr.query)
        limit = int(query.get("limit", ["60"])[0] or 60)
        live_codex = (query.get("live_codex", ["0"])[0] or "").lower() in ("1", "true", "yes")
        hist = [item for item in common.load_history(limit * 3, ctx=ctx, live_codex=live_codex)
                if common.path_allowed_for_user(ctx.get("user"), item.get("cwd") or "")]
        handler._json({"history": hist[:limit]})
    elif path == "/api/recent_dirs":
        query = urllib.parse.parse_qs(pr.query)
        limit = int(query.get("limit", ["30"])[0] or 30)
        dirs = [item for item in common.recent_dirs(500, ctx=ctx)
                if common.path_allowed_for_user(ctx.get("user"), item.get("cwd") or "")]
        handler._json({"dirs": dirs[:limit]})
    elif path == "/api/backends":
        handler._json({"backends": list(common.BACKENDS.keys()),
                       "labels": {key: value.get("label", key) for key, value in common.BACKENDS.items()}})
    elif path == "/api/cc_usage":
        out = common.ccswitch_overview()
        if out.get("enabled"):
            out["balance"] = common.ccswitch_balance()
        handler._json(out)
    else:
        handler._json({"error": "not found"}, 404)


def resume_native(handler, data, ctx, launch_native_fn):
    session_id = (data.get("session_id") or "").strip()
    directory = (data.get("dir") or "").strip().strip('"')
    backend = common.normalize_backend(data.get("backend"))
    if not session_id:
        handler._json({"error": "missing session_id"}, 400)
        return
    events = []
    title = data.get("title") or "Resume"
    if common.is_codex_backend(backend):
        try:
            snap = CodexSession.history_snapshot(session_id, user=ctx.get("user", ""),
                                                 uid=ctx.get("uid", ""),
                                                 state_dir=ctx.get("state_dir"),
                                                 codex_home=ctx.get("codex_home"))
            events = snap.get("events") or []
            if snap.get("cwd") and not os.path.isdir(directory):
                directory = snap.get("cwd")
            if snap.get("title") and not data.get("title"):
                title = snap.get("title")
        except Exception as exc:
            events = [{"type": "codex_notice", "message": "Codex history read failed: %s" % exc}]
    if not directory or not os.path.isdir(directory):
        directory = directory or os.path.expanduser("~")
    if not common.path_allowed_for_user(ctx.get("user"), directory):
        handler._json({"error": "directory is outside this user's workspaces: %r" % directory}, 403)
        return
    if not common.is_codex_backend(backend):
        events = common.load_claude_transcript_events(session_id, ctx=ctx)
    auto_approve = common.AUTO_APPROVE if data.get("yolo") is None else bool(data.get("yolo"))
    try:
        sid = launch_native_fn(directory, title=title,
                               auto_approve=auto_approve, mode="resume",
                               session_id=session_id, events=events, backend=backend, ctx=ctx)
    except Exception as exc:
        handler._json({"error": str(exc)}, 500)
        return
    handler._json({"ok": True, "sid": sid, "dir": directory, "backend": backend,
                   "yolo": auto_approve, "session_path": "/t/%s/" % sid})


def handle_post(handler, path, data, ctx, native_from_payload_fn, owned_session_fn,
                launch_native_fn, kill_session_fn):
    if path == "/api/launch":
        directory = (data.get("dir") or "").strip().strip('"')
        if not directory or not os.path.isdir(directory):
            handler._json({"error": "invalid directory: %r" % directory}, 400)
            return
        if not common.path_allowed_for_user(ctx.get("user"), directory):
            handler._json({"error": "directory is outside this user's workspaces: %r" % directory}, 403)
            return
        auto_approve = common.AUTO_APPROVE if data.get("yolo") is None else bool(data.get("yolo"))
        backend = common.normalize_backend(data.get("backend"))
        try:
            sid = launch_native_fn(directory, title=data.get("title") or "",
                                   auto_approve=auto_approve, backend=backend, ctx=ctx)
        except Exception as exc:
            handler._json({"error": str(exc)}, 500)
            return
        handler._json({"ok": True, "sid": sid, "dir": directory, "backend": backend,
                       "yolo": auto_approve, "session_path": "/t/%s/" % sid})
    elif path in ("/api/resume", "/api/nresume"):
        resume_native(handler, data, ctx, launch_native_fn)
    elif path == "/api/stop":
        sid = (data.get("sid") or "").strip()
        if not owned_session_fn(sid, ctx):
            handler._json({"ok": False}, 404)
            return
        handler._json({"ok": kill_session_fn(sid)})
    elif path == "/api/ninterrupt":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        handler._json({"ok": native.interrupt()})
    elif path == "/api/nsend":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        prompt = (data.get("prompt") or "").strip()
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        if not prompt:
            handler._json({"error": "missing prompt"}, 400)
            return
        if getattr(native, "_busy", False) or getattr(native, "_pending", None):
            handler._json({"error": "session is busy"}, 409)
            return
        if "plan" in data:
            native.plan_mode = bool(data["plan"])
        if "task" in data:
            native.task_mode = bool(data["task"])
        native.send(prompt)
        handler._json({"ok": True})
    elif path == "/api/nmode":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        native.set_modes(data.get("plan"), data.get("task"))
        handler._json({"ok": True, "plan": native.plan_mode, "task": native.task_mode})
    elif path == "/api/napprove":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        tool_use_id = (data.get("tool_use_id") or "").strip()
        allow = bool(data.get("allow"))
        always = bool(data.get("always"))
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        handler._json({"ok": native.approve(tool_use_id, allow, data.get("message"), always)})
    elif path == "/api/nanswer":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        tool_use_id = (data.get("tool_use_id") or "").strip()
        answer = data.get("answers") if "answers" in data else (data.get("answer") or "")
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        handler._json({"ok": native.answer(tool_use_id, answer)})
    elif path == "/api/stop_all":
        for sid in manager_sessions.owned_sids(ctx.get("user")):
            kill_session_fn(sid)
        handler._json({"ok": True})
    elif path == "/api/history_delete":
        sid = (data.get("sid") or "").strip()
        try:
            if manager_sessions.history_belongs_to_other_user(sid, ctx.get("user")):
                handler._json({"error": "history belongs to another user"}, 403)
                return
            result = common.delete_history(sid, data.get("backend"), ctx=ctx)
        except Exception as exc:
            handler._json({"error": str(exc)}, 500)
            return
        handler._json({"ok": result["deleted"], "deleted": result["deleted"]})
    else:
        handler._json({"error": "not found"}, 404)
