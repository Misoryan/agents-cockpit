# -*- coding: utf-8 -*-
"""Browser-facing manager API handlers."""
import os
import mimetypes
import urllib.parse

import common
import codex_config
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
        archived = (query.get("archived", ["0"])[0] or "").lower() in ("1", "true", "yes")
        hist = [item for item in common.load_history(
                    limit * 3, ctx=ctx, live_codex=live_codex, archived=archived)
                if common.path_allowed_for_user(ctx.get("user"), item.get("cwd") or "")]
        handler._json({"history": hist[:limit]})
    elif path == "/api/codex_options":
        query = urllib.parse.parse_qs(pr.query)
        directory = (query.get("dir", [""])[0] or "").strip().strip('"')
        if directory and not common.path_allowed_for_user(ctx.get("user"), directory):
            handler._json({"error": "directory is outside this user's workspaces: %r" % directory}, 403)
            return
        try:
            options = CodexSession.launch_options(
                directory, user=ctx.get("user", ""), uid=ctx.get("uid", ""),
                state_dir=ctx.get("state_dir"), codex_home=ctx.get("codex_home"))
        except Exception as exc:
            options = codex_config.default_launch_options(error=str(exc))
        handler._json(options)
    elif path == "/api/nfiles":
        query = urllib.parse.parse_qs(pr.query)
        sid = (query.get("sid", [""])[0] or "").strip()
        q = (query.get("q", [""])[0] or "").strip()
        try:
            limit = int(query.get("limit", ["20"])[0] or 20)
        except Exception:
            limit = 20
        session = owned_session_fn(sid, ctx)
        if not session or not session.get("native"):
            handler._json({"ok": False, "error": "native session not found"}, 404)
            return
        native = session.get("native")
        if not hasattr(native, "search_files"):
            handler._json({"ok": False, "error": "file search is only supported for Codex sessions"}, 400)
            return
        try:
            handler._json(native.search_files(q, limit=limit))
        except Exception as exc:
            handler._json({"ok": False, "error": str(exc), "files": []}, 500)
    elif path == "/api/nimage":
        query = urllib.parse.parse_qs(pr.query)
        sid = (query.get("sid", [""])[0] or "").strip()
        image_id = (query.get("id", [""])[0] or query.get("name", [""])[0] or "").strip()
        session = owned_session_fn(sid, ctx)
        if not session or not session.get("native"):
            handler._json({"ok": False, "error": "native session not found"}, 404)
            return
        native = session.get("native")
        if not hasattr(native, "image_file"):
            handler._json({"ok": False, "error": "image attachments are not supported for this session"}, 400)
            return
        path = native.image_file(image_id)
        if not path:
            handler._json({"ok": False, "error": "image not found"}, 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            handler.send_response(200)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Cache-Control", "private, max-age=3600")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except OSError as exc:
            handler._json({"ok": False, "error": str(exc)}, 500)
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
        cfg = codex_config.normalize_launch_config(data.get("codex") or {})
        try:
            sid = launch_native_fn(directory, title=data.get("title") or "",
                                   auto_approve=auto_approve, backend=backend, ctx=ctx,
                                   codex_config=cfg if common.is_codex_backend(backend) else None)
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
        images = data.get("images") or []
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        if getattr(native, "_busy", False) or getattr(native, "_pending", None):
            handler._json({"error": "session is busy"}, 409)
            return
        if images and not hasattr(native, "prepare_image_inputs"):
            handler._json({"error": "image input is only supported for Codex sessions"}, 400)
            return
        try:
            image_inputs = native.prepare_image_inputs(images) if images else []
        except ValueError as exc:
            handler._json({"error": str(exc)}, 400)
            return
        if not prompt and not image_inputs:
            handler._json({"error": "missing prompt"}, 400)
            return
        if "plan" in data:
            native.plan_mode = bool(data["plan"])
        if "task" in data:
            native.task_mode = bool(data["task"])
        try:
            native.send(prompt, image_inputs=image_inputs)
        except TypeError:
            native.send(prompt)
        handler._json({"ok": True})
    elif path == "/api/nslash":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        command = (data.get("command") or "").strip()
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        if not command:
            handler._json({"error": "missing command"}, 400)
            return
        is_steer = command.lower().startswith("/steer")
        if getattr(native, "_pending", None) or (getattr(native, "_busy", False) and not is_steer):
            handler._json({"error": "session is busy"}, 409)
            return
        if not hasattr(native, "handle_slash_command"):
            handler._json({"error": "slash commands are only supported for Codex sessions"}, 400)
            return
        try:
            result = native.handle_slash_command(command)
        except Exception as exc:
            handler._json({"error": str(exc)}, 500)
            return
        if not result.get("ok"):
            handler._json(result, 400)
            return
        handler._json(result)
    elif path == "/api/nterminal":
        _sid, _session, native = native_from_payload_fn(data, ctx)
        if not native:
            handler._json({"error": "native session not found"}, 404)
            return
        process_id = (data.get("process_id") or data.get("processId") or "").strip()
        action = (data.get("action") or "write").strip().lower()
        try:
            if action == "terminate":
                result = native.terminal_terminate(process_id)
            elif action == "resize":
                result = native.terminal_resize(process_id, data.get("cols"), data.get("rows"))
            elif action in ("write", "close"):
                result = native.terminal_write(
                    process_id,
                    data.get("input") or "",
                    close_stdin=bool(data.get("close") or action == "close"),
                )
            else:
                result = {"ok": False, "error": "unsupported terminal action"}
        except Exception as exc:
            handler._json({"error": str(exc)}, 500)
            return
        if not result.get("ok"):
            handler._json(result, 400)
            return
        handler._json(result)
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
    elif path == "/api/codex_history_action":
        thread_id = (data.get("thread_id") or data.get("session_id") or data.get("sid") or "").strip()
        action = (data.get("action") or "").strip().lower()
        backend = common.normalize_backend(data.get("backend") or "codex_native")
        if not common.is_codex_backend(backend):
            handler._json({"error": "history action is only supported for Codex threads"}, 400)
            return
        if not thread_id:
            handler._json({"error": "missing thread_id"}, 400)
            return
        try:
            if manager_sessions.history_belongs_to_other_user(thread_id, ctx.get("user")):
                handler._json({"error": "history belongs to another user"}, 403)
                return
            result = CodexSession.history_action(
                thread_id, action,
                name=data.get("name") or "",
                objective=data.get("objective") or "",
                status=data.get("status") or "",
                user=ctx.get("user", ""), uid=ctx.get("uid", ""),
                state_dir=ctx.get("state_dir"), codex_home=ctx.get("codex_home"))
        except Exception as exc:
            handler._json({"error": str(exc)}, 500)
            return
        if not result.get("ok"):
            handler._json(result, 400)
            return
        handler._json(result)
    else:
        handler._json({"error": "not found"}, 404)
