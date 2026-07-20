# -*- coding: utf-8 -*-
"""Claude CLI process execution helpers for NativeSession."""
import json
import subprocess
import threading
import time
import traceback

import common


def run_one_round(session, prompt):
    """Spawn one Claude CLI turn and stream non-result events to the session."""
    argv = session._build_argv(prompt)
    proc = subprocess.Popen(
        argv, cwd=session.cwd,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        env=session._process_env())
    session._proc = proc

    stderr_buf = []
    threading.Thread(target=session._drain_stderr, args=(proc, stderr_buf), daemon=True).start()

    result_ev = None
    for line in proc.stdout:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        with session._lock:
            if ev.get("session_id"):
                session.claude_sid = ev["session_id"]
            if ev.get("type") == "system" and ev.get("model"):
                session.model = ev["model"]
        if ev.get("type") == "result":
            result_ev = ev
            continue
        if ev.get("type") in ("assistant", "user"):
            ev = session._record_event(ev)
        session._broadcast(ev)
        session.last_activity = time.time()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
    return result_ev, True, "".join(stderr_buf)


def drain_stderr(proc, buf):
    try:
        for line in proc.stderr:
            buf.append(line)
    except Exception:
        pass


def dump_failure(session, tag, result_ev, stderr_text):
    try:
        print("[native %s] === %s ===" % (session.sid, tag))
        if result_ev:
            print("[native %s] result: %s"
                  % (session.sid, json.dumps(result_ev, ensure_ascii=False)))
        if stderr_text and stderr_text.strip():
            print("[native %s] stderr:\n%s" % (session.sid, stderr_text))
    except Exception:
        pass


def run_cli(session, prompt, is_overloaded_fn, short_err_fn):
    session._busy = True
    session.last_activity = time.time()
    session.current_turn_started_at = session.last_activity
    success = False
    try:
        result_ev, _ran_clean, stderr_text = session._run_one_round(prompt)
        if session._interrupted or session._closed:
            pass
        elif result_ev is not None:
            if is_overloaded_fn(result_ev, stderr_text):
                session._dump_failure("rate-limit/overload (1305/529)", result_ev, stderr_text)
                session._record_and_broadcast({"type": "rate_limited",
                                               "detail": short_err_fn(result_ev)})
            else:
                result_ev = session._record_event(result_ev)
                session._broadcast(result_ev)
                success = not (result_ev.get("is_error") or result_ev.get("error"))
        elif stderr_text.strip():
            session._dump_failure("process crash (no result event)", None, stderr_text)
            session._record_and_broadcast({"type": "result",
                                           "error": "claude CLI 异常退出,见 manager 日志"})
        else:
            session._record_and_broadcast({"type": "result", "error": "未收到 claude 结果事件"})
    except Exception:
        traceback.print_exc()
        session._record_and_broadcast({"type": "result", "error": "claude CLI 执行异常,见 manager 日志"})
    finally:
        finished_at = time.time()
        session._busy = False
        session.current_turn_started_at = None
        if not session._closed:
            session.last_completed_at = finished_at
        session._proc = None
        if session._interrupted and not session._closed:
            session._interrupted = False
            session._record_and_broadcast({"type": "interrupted"})
        elif success and not session._closed:
            with session._lock:
                webhook_body = common.notify_result_text(session.events)
            title, body = common.notify_copy("done", session.cwd, "Claude")
            session._push("done", title, body,
                          webhook_body=webhook_body or (session.cwd + " · 已完成但没有文本结果"))
        session._persist()
