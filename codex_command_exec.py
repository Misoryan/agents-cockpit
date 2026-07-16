# -*- coding: utf-8 -*-
"""Standalone Codex command/exec helpers for explicit Web slash usage."""
import base64
import os
import shutil
import threading
import time

import codex_config
import codex_terminal


DEFAULT_TIMEOUT_MS = 60000
STREAM_TIMEOUT_MS = 300000
MAX_CAPTURE_CHARS = 24000
STREAM_EMIT_INTERVAL = 0.2


def _clip_text(value, limit=MAX_CAPTURE_CHARS):
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    head = max(1, limit // 2)
    tail = max(1, limit - head)
    omitted = len(text) - head - tail
    return (
        text[:head]
        + "\n\n... [truncated %d characters] ...\n\n" % omitted
        + text[-tail:]
    )


def _decode_delta(params):
    raw = (params or {}).get("deltaBase64") or ""
    if not raw:
        return ""
    try:
        return base64.b64decode(str(raw).encode("ascii")).decode("utf-8", "replace")
    except Exception:
        return ""


def shell_command_argv(command):
    """Return the shell tool name and argv used for command/exec."""
    command = str(command or "")
    if os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        return (
            "powershell",
            [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        )
    bash = shutil.which("bash")
    if bash:
        return "bash", [bash, "-lc", command]
    shell = shutil.which("sh") or "sh"
    return "bash", [shell, "-c", command]


def sandbox_policy_for_session(session):
    if getattr(session, "yolo", False):
        return {"type": "dangerFullAccess"}
    cfg = getattr(session, "cfg", {}) or {}
    return codex_config.sandbox_policy(
        cfg.get("sandbox"),
        getattr(session, "cwd", ""),
        cfg.get("writable_roots"),
    )


def build_exec_params(session, command, timeout_ms=DEFAULT_TIMEOUT_MS):
    tool_name, argv = shell_command_argv(command)
    params = {
        "command": argv,
        "cwd": os.path.abspath(getattr(session, "cwd", "") or os.getcwd()),
        "timeoutMs": int(timeout_ms or DEFAULT_TIMEOUT_MS),
    }
    sandbox = sandbox_policy_for_session(session)
    if sandbox:
        params["sandboxPolicy"] = sandbox
    cfg = getattr(session, "cfg", {}) or {}
    if getattr(session, "yolo", False):
        params["approvalPolicy"] = "never"
    elif cfg.get("approval_policy"):
        params["approvalPolicy"] = cfg["approval_policy"]
    return tool_name, params


def _emit_tool_use(session, call_id, tool_name, command, params):
    input_obj = {
        "command": command,
        "cwd": params.get("cwd") or "",
        "timeoutMs": params.get("timeoutMs") or DEFAULT_TIMEOUT_MS,
    }
    if params.get("sandboxPolicy"):
        input_obj["sandboxPolicy"] = params["sandboxPolicy"]
    if params.get("approvalPolicy"):
        input_obj["approvalPolicy"] = params["approvalPolicy"]
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": call_id,
            "name": tool_name,
            "input": input_obj,
        }]},
    })


def _emit_tool_result(session, call_id, result, duration_ms, error=None):
    result = result if isinstance(result, dict) else {}
    stdout = _clip_text(result.get("stdout") or "")
    stderr = _clip_text(result.get("stderr") or "")
    exit_code = result.get("exitCode")
    if error and not stderr:
        stderr = str(error)
    content = "exit code: %s\nduration ms: %d" % (
        "" if exit_code is None and error else (exit_code if exit_code is not None else ""),
        int(duration_ms),
    )
    block = {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": content,
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": exit_code if exit_code is not None else ("error" if error else ""),
        "durationMs": int(duration_ms),
    }
    if error:
        block["error"] = str(error)
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [block]},
    })


def _broadcast_tool_result(session, call_id, stdout, stderr, duration_ms, exit_code="running", error=None,
                           record=False):
    result = {"exitCode": exit_code, "stdout": stdout, "stderr": stderr}
    if record:
        _emit_tool_result(session, call_id, result, duration_ms, error=error)
        return
    block = {
        "type": "tool_result",
        "tool_use_id": call_id,
        "content": "exit code: %s\nduration ms: %d" % (exit_code, int(duration_ms)),
        "stdout": _clip_text(stdout),
        "stderr": _clip_text(stderr if not error else (stderr or str(error))),
        "exitCode": exit_code,
        "durationMs": int(duration_ms),
    }
    if error:
        block["error"] = str(error)
    session._broadcast({
        "type": "user",
        "message": {"content": [block]},
    })


def exec_notice_message(command, result, duration_ms, error=None):
    if error:
        return "Command exec failed after %dms: %s" % (int(duration_ms), error)
    exit_code = result.get("exitCode") if isinstance(result, dict) else None
    return "Command exec finished with exit %s in %dms: %s" % (
        exit_code if exit_code is not None else "unknown",
        int(duration_ms),
        str(command or "")[:120],
    )


def run_command_exec(session, arg):
    command = str(arg or "").strip()
    if not command:
        return {"ok": False, "error": "usage: /exec <shell command>"}
    call_id = "command-exec-%d" % int(time.time() * 1000)
    tool_name, params = build_exec_params(session, command)
    _emit_tool_use(session, call_id, tool_name, command, params)
    started = time.monotonic()
    old_busy = bool(getattr(session, "_busy", False))
    old_started = getattr(session, "current_turn_started_at", None)
    session._busy = True
    session.current_turn_started_at = time.time()
    result = {}
    error = None
    try:
        result = session._client().request("command/exec", params, timeout=(params["timeoutMs"] / 1000.0) + 15) or {}
    except Exception as exc:  # Surface app-server failures as replayed command results.
        error = str(exc)
    finally:
        session._busy = old_busy
        session.current_turn_started_at = old_started
    duration_ms = int((time.monotonic() - started) * 1000)
    _emit_tool_result(session, call_id, result, duration_ms, error=error)
    exit_code = result.get("exitCode") if isinstance(result, dict) else None
    failed = bool(error or (exit_code is not None and str(exit_code) != "0"))
    session._record_and_broadcast({
        "type": "result",
        "duration_ms": duration_ms,
        "is_error": failed,
        "stop_reason": "command/exec",
    })
    session._codex_notice(
        exec_notice_message(command, result, duration_ms, error=error),
        "command/exec",
        {
            "command": command,
            "cwd": params.get("cwd"),
            "exitCode": exit_code,
            "durationMs": duration_ms,
            "error": error or "",
        },
        level="warning" if failed else None,
        silent=True,
    )
    session._persist()
    return {
        "ok": True,
        "command": "exec",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "error": error or "",
    }


def _stream_process_id(session):
    return "command-exec-%s-%d" % (getattr(session, "sid", "session"), int(time.time() * 1000))


def _has_active_stream_exec(session):
    with session._pending_lock:
        return any(str(pid).startswith("command-exec-") for pid in session._terminal_processes)


def _streaming_allowed(session):
    if os.name != "nt":
        return True, ""
    if getattr(session, "yolo", False):
        return True, ""
    cfg = getattr(session, "cfg", {}) or {}
    if cfg.get("sandbox") == "danger-full-access":
        return True, ""
    return (
        False,
        "streamed command/exec requires danger-full-access on Windows; use /exec for buffered output "
        "or set /sandbox danger-full-access before /exec-stream",
    )


def _mark_stream_terminal(session, process_id, call_id):
    event = codex_terminal.terminal_interaction_event(
        session,
        {
            "processId": process_id,
            "itemId": call_id,
            "stdin": "Optional stdin for /exec-stream. Use Send and close stdin for commands waiting on input.",
        },
    )
    if event:
        session._broadcast(event)


def _close_stream_terminal(session, process_id, terminated=False):
    with session._pending_lock:
        existed = process_id in session._terminal_processes
        session._terminal_processes.pop(process_id, None)
    if existed:
        session._broadcast({
            "type": "terminal_closed",
            "process_id": process_id,
            "terminated": bool(terminated),
        })


def _run_stream_worker(session, call_id, process_id, params, command):
    client = session._client()
    started = time.monotonic()
    state = {"stdout": "", "stderr": "", "last_emit": 0.0}
    lock = threading.Lock()

    def snapshot():
        with lock:
            return state["stdout"], state["stderr"]

    def emit(force=False):
        now = time.monotonic()
        with lock:
            if not force and now - state["last_emit"] < STREAM_EMIT_INTERVAL:
                return
            state["last_emit"] = now
            stdout, stderr = state["stdout"], state["stderr"]
        _broadcast_tool_result(
            session,
            call_id,
            stdout,
            stderr,
            int((now - started) * 1000),
            exit_code="running",
            record=False,
        )

    def handle_delta(delta):
        text = _decode_delta(delta)
        if not text:
            return
        stream = str((delta or {}).get("stream") or "stdout").lower()
        with lock:
            key = "stderr" if stream == "stderr" else "stdout"
            state[key] += text
            state[key] = _clip_text(state[key])
        emit(force=False)

    result = {}
    error = None
    try:
        client.ensure()
        client.add_command_exec_output_handler(process_id, handle_delta)
        result = client.request("command/exec", params, timeout=(params["timeoutMs"] / 1000.0) + 15) or {}
    except Exception as exc:
        error = str(exc)
    finally:
        client.remove_command_exec_output_handler(process_id, handle_delta)

    stdout, stderr = snapshot()
    if not stdout and isinstance(result, dict) and result.get("stdout"):
        stdout = result.get("stdout") or ""
    if not stderr and isinstance(result, dict) and result.get("stderr"):
        stderr = result.get("stderr") or ""
    duration_ms = int((time.monotonic() - started) * 1000)
    exit_code = result.get("exitCode") if isinstance(result, dict) else None
    failed = bool(error or (exit_code is not None and str(exit_code) != "0"))
    _broadcast_tool_result(
        session,
        call_id,
        stdout,
        stderr,
        duration_ms,
        exit_code=exit_code if exit_code is not None else ("error" if error else ""),
        error=error,
        record=True,
    )
    _close_stream_terminal(session, process_id, terminated=failed)
    session._record_and_broadcast({
        "type": "result",
        "duration_ms": duration_ms,
        "is_error": failed,
        "stop_reason": "command/exec",
    })
    session._codex_notice(
        exec_notice_message(command, {"exitCode": exit_code}, duration_ms, error=error),
        "command/exec",
        {
            "command": command,
            "processId": process_id,
            "cwd": params.get("cwd"),
            "exitCode": exit_code,
            "durationMs": duration_ms,
            "error": error or "",
        },
        level="warning" if failed else None,
        silent=True,
    )
    session._persist()


def run_stream_command_exec(session, arg):
    command = str(arg or "").strip()
    if not command:
        return {"ok": False, "error": "usage: /exec-stream <shell command>"}
    allowed, reason = _streaming_allowed(session)
    if not allowed:
        return {"ok": False, "error": reason}
    if _has_active_stream_exec(session):
        return {"ok": False, "error": "another /exec-stream command is already running in this session"}
    process_id = _stream_process_id(session)
    call_id = process_id
    tool_name, params = build_exec_params(session, command, timeout_ms=STREAM_TIMEOUT_MS)
    params["processId"] = process_id
    params["streamStdoutStderr"] = True
    params["streamStdin"] = True
    _emit_tool_use(session, call_id, tool_name, command, params)
    _mark_stream_terminal(session, process_id, call_id)
    threading.Thread(
        target=_run_stream_worker,
        args=(session, call_id, process_id, params, command),
        daemon=True,
    ).start()
    session._persist()
    return {
        "ok": True,
        "command": "exec-stream",
        "process_id": process_id,
    }
