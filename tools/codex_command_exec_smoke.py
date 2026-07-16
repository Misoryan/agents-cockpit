#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live smoke for Codex app-server standalone command/exec.

This exercises the real app-server path outside a model turn:
buffered command execution, streamed stdout/stderr, streamed stdin, and
termination of a long-running process. It is intentionally safe and local.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import codex_command_exec  # noqa: E402
from codex_client import CodexAppServerClient  # noqa: E402


def _b64(text):
    return base64.b64encode((text or "").encode("utf-8")).decode("ascii")


def _decode_delta(params):
    raw = (params or {}).get("deltaBase64") or ""
    if not raw:
        return ""
    return base64.b64decode(raw.encode("ascii")).decode("utf-8", "replace")


def _wait_for(predicate, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _request_in_thread(client, method, params, timeout):
    box = {"done": threading.Event(), "result": None, "error": None}

    def run():
        try:
            box["result"] = client.request(method, params, timeout=timeout)
        except Exception as exc:  # pragma: no cover - surfaced by caller
            box["error"] = str(exc)
        finally:
            box["done"].set()

    threading.Thread(target=run, daemon=True).start()
    return box


class _HelperSession:
    def __init__(self, client, cwd):
        self.sid = "command-exec-helper-smoke"
        self.cwd = cwd
        self.cfg = {"sandbox": "danger-full-access", "approval_policy": "never"}
        self.yolo = False
        self._pending_lock = threading.Lock()
        self._terminal_processes = {}
        self.records = []
        self.broadcasts = []
        self.notices = []
        self.persisted = 0
        self.client = client

    def _client(self):
        return self.client

    def _record_and_broadcast(self, obj):
        self.records.append(obj)

    def _broadcast(self, obj):
        self.broadcasts.append(obj)

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        self.notices.append({
            "message": message,
            "method": method,
            "params": params,
            "level": level,
            "silent": silent,
        })

    def _persist(self):
        self.persisted += 1


def _tool_stdout(events):
    out = []
    for event in events or []:
        if event.get("type") != "user":
            continue
        blocks = ((event.get("message") or {}).get("content") or [])
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                out.append(str(block.get("stdout") or ""))
    return "\n".join(out)


def _helper_command(py):
    code = "import sys; print('web-ready', flush=True); data=sys.stdin.read(); print('web:'+data.strip(), flush=True)"
    if os.name == "nt":
        return '& "%s" -u -c "%s"' % (py, code)
    return "'%s' -u -c \"%s\"" % (py.replace("'", "'\\''"), code)


def _run_browser_helper_smoke(client, cwd, py):
    session = _HelperSession(client, cwd)
    started = codex_command_exec.run_stream_command_exec(session, _helper_command(py))
    assert started.get("ok") is True, started
    process_id = started.get("process_id")
    assert process_id, started
    assert _wait_for(lambda: "web-ready" in _tool_stdout(session.broadcasts + session.records)), (
        session.broadcasts,
        session.records,
    )
    client.request("command/exec/write", {
        "processId": process_id,
        "deltaBase64": _b64("gamma\n"),
        "closeStdin": True,
    }, timeout=10)
    assert _wait_for(lambda: session.notices, timeout=20), "helper command did not finish"
    combined = _tool_stdout(session.broadcasts + session.records)
    assert "web-ready" in combined and "web:gamma" in combined, combined
    assert any(event.get("type") == "terminal_interaction" for event in session.broadcasts)
    assert any(event.get("type") == "terminal_closed" for event in session.broadcasts)
    return {
        "processId": process_id,
        "records": len(session.records),
        "broadcasts": len(session.broadcasts),
        "output": combined.replace("\r\n", "\n").replace("\r", "\n"),
    }


def run_smoke(cwd):
    cwd = os.path.abspath(cwd or os.getcwd())
    py = sys.executable
    sandbox = {"type": "dangerFullAccess"}
    with tempfile.TemporaryDirectory(prefix="codex-command-exec-", ignore_cleanup_errors=True) as state_dir:
        client = CodexAppServerClient(
            user="command-exec-smoke",
            uid="command-exec-smoke",
            state_dir=state_dir,
        )
        try:
            buffered = client.request("command/exec", {
                "command": [
                    py,
                    "-c",
                    "import sys; print('buffered-ok'); print('buffered-err', file=sys.stderr)",
                ],
                "cwd": cwd,
                "sandboxPolicy": sandbox,
                "timeoutMs": 15000,
            }, timeout=30)
            assert buffered.get("exitCode") == 0, buffered
            assert "buffered-ok" in (buffered.get("stdout") or "")
            assert "buffered-err" in (buffered.get("stderr") or "")

            stream_chunks = []
            stream_id = "agents-cockpit-stream-smoke"
            client.add_command_exec_output_handler(stream_id, stream_chunks.append)
            streamed = _request_in_thread(client, "command/exec", {
                "command": [
                    py,
                    "-u",
                    "-c",
                    "import sys; print('ready', flush=True); data=sys.stdin.read(); print('stdin:'+data.strip(), flush=True)",
                ],
                "cwd": cwd,
                "processId": stream_id,
                "streamStdin": True,
                "streamStdoutStderr": True,
                "sandboxPolicy": sandbox,
                "timeoutMs": 20000,
            }, timeout=30)
            assert _wait_for(lambda: "ready" in "".join(_decode_delta(c) for c in stream_chunks)), stream_chunks
            write = client.request("command/exec/write", {
                "processId": stream_id,
                "deltaBase64": _b64("alpha\nbeta\n"),
                "closeStdin": True,
            }, timeout=10)
            assert write == {} or write is None or isinstance(write, dict)
            assert streamed["done"].wait(20), "streamed command did not finish"
            if streamed["error"]:
                raise RuntimeError(streamed["error"])
            assert streamed["result"].get("exitCode") == 0, streamed["result"]
            stream_text = "".join(_decode_delta(c) for c in stream_chunks)
            normalized_stream = stream_text.replace("\r\n", "\n").replace("\r", "\n")
            assert "ready" in normalized_stream and "stdin:alpha\nbeta" in normalized_stream, stream_text

            term_chunks = []
            term_id = "agents-cockpit-terminate-smoke"
            client.add_command_exec_output_handler(term_id, term_chunks.append)
            long_running = _request_in_thread(client, "command/exec", {
                "command": [
                    py,
                    "-u",
                    "-c",
                    "import time; print('started', flush=True); time.sleep(30)",
                ],
                "cwd": cwd,
                "processId": term_id,
                "streamStdoutStderr": True,
                "sandboxPolicy": sandbox,
                "timeoutMs": 60000,
            }, timeout=70)
            assert _wait_for(lambda: "started" in "".join(_decode_delta(c) for c in term_chunks)), term_chunks
            terminate = client.request("command/exec/terminate", {"processId": term_id}, timeout=10)
            assert terminate == {} or terminate is None or isinstance(terminate, dict)
            assert long_running["done"].wait(20), "terminated command did not finish"
            assert "started" in "".join(_decode_delta(c) for c in term_chunks)

            browser_helper = _run_browser_helper_smoke(client, cwd, py)

            return {
                "ok": True,
                "buffered": {
                    "exitCode": buffered.get("exitCode"),
                    "stdout": buffered.get("stdout"),
                    "stderr": buffered.get("stderr"),
                },
                "streamed": {
                    "exitCode": streamed["result"].get("exitCode"),
                    "output": normalized_stream,
                    "chunks": len(stream_chunks),
                },
                "terminated": {
                    "result": long_running["result"],
                    "error": long_running["error"],
                    "chunks": len(term_chunks),
                },
                "browser_helper": browser_helper,
            }
        finally:
            client.remove_command_exec_output_handler("agents-cockpit-stream-smoke")
            client.remove_command_exec_output_handler("agents-cockpit-terminate-smoke")
            client.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for command/exec smoke commands.")
    args = parser.parse_args(argv)
    result = run_smoke(args.cwd)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
