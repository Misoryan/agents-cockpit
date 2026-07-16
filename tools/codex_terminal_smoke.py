#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adapter-level smoke for Codex terminalInteraction.

The real interactive command is owned by Codex app-server. This smoke validates
the Web adapter's side of that long-running path: terminalInteraction
notification -> tracked process -> multiple stdin writes -> resize -> close or
terminate -> replayable terminal_closed event -> unknown-process rejection.
"""
import argparse
import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import codex_session_events  # noqa: E402
from codex_native import CodexSession  # noqa: E402


class FakeCodexClient:
    def __init__(self):
        self.calls = []

    def request(self, method, params=None, timeout=None):
        self.calls.append({
            "method": method,
            "params": dict(params or {}),
            "timeout": timeout,
        })
        return {"ok": True}


def _decode_delta(call):
    delta = ((call or {}).get("params") or {}).get("deltaBase64") or ""
    if not delta:
        return ""
    return base64.b64decode(delta.encode("ascii")).decode("utf-8")


def _events_of(session, event_type):
    return [event for event in session.poll_events if event.get("type") == event_type]


def run_smoke(cwd):
    fake = FakeCodexClient()
    with tempfile.TemporaryDirectory(prefix="codex-terminal-smoke-") as state_dir:
        session = CodexSession(
            "s-terminal-smoke",
            cwd or os.getcwd(),
            yolo=False,
            user="terminal-smoke",
            uid="terminal-smoke",
            state_dir=state_dir,
        )
        session._client = lambda: fake

        codex_session_events.handle_notification(session, "item/commandExecution/terminalInteraction", {
            "processId": "proc-1",
            "itemId": "item-1",
            "stdin": "password:",
        })
        term_events = _events_of(session, "terminal_interaction")
        assert len(term_events) == 1 and term_events[0]["process_id"] == "proc-1"

        first = session.terminal_write("proc-1", "alpha\n")
        second = session.terminal_write("proc-1", "beta\n")
        resize = session.terminal_resize("proc-1", 120, 40)
        closed = session.terminal_write("proc-1", "done\n", close_stdin=True)
        rejected_after_close = session.terminal_write("proc-1", "late\n")

        codex_session_events.handle_notification(session, "item/commandExecution/terminalInteraction", {
            "processId": "proc-2",
            "itemId": "item-2",
            "stdin": "",
        })
        terminate = session.terminal_terminate("proc-2")
        rejected_after_terminate = session.terminal_resize("proc-2", 80, 24)

        write_calls = [call for call in fake.calls if call["method"] == "command/exec/write"]
        resize_calls = [call for call in fake.calls if call["method"] == "command/exec/resize"]
        terminate_calls = [call for call in fake.calls if call["method"] == "command/exec/terminate"]
        terminal_closed = _events_of(session, "terminal_closed")
        terminal_sent = _events_of(session, "terminal_input_sent")

        assert first == {"ok": True, "process_id": "proc-1", "closed": False}
        assert second == {"ok": True, "process_id": "proc-1", "closed": False}
        assert resize == {"ok": True, "process_id": "proc-1", "cols": 120, "rows": 40}
        assert closed == {"ok": True, "process_id": "proc-1", "closed": True}
        assert rejected_after_close["ok"] is False
        assert terminate == {"ok": True, "process_id": "proc-2", "terminated": True}
        assert rejected_after_terminate["ok"] is False

        assert [_decode_delta(call) for call in write_calls] == ["alpha\n", "beta\n", "done\n"]
        assert write_calls[-1]["params"].get("closeStdin") is True
        assert resize_calls[-1]["params"] == {"processId": "proc-1", "size": {"cols": 120, "rows": 40}}
        assert terminate_calls[-1]["params"] == {"processId": "proc-2"}
        assert len(terminal_sent) == 2
        assert [event["process_id"] for event in terminal_closed] == ["proc-1", "proc-2"]
        assert terminal_closed[-1].get("terminated") is True
        assert len({event.get("seq") for event in terminal_closed + terminal_sent if event.get("seq")}) == 4

        return {
            "ok": True,
            "writes": [_decode_delta(call) for call in write_calls],
            "resize": resize_calls[-1]["params"],
            "terminate": terminate_calls[-1]["params"],
            "terminal_interactions": len(term_events) + 1,
            "terminal_input_sent": len(terminal_sent),
            "terminal_closed": terminal_closed,
            "rejected_after_close": rejected_after_close.get("error"),
            "rejected_after_terminate": rejected_after_terminate.get("error"),
        }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for the temporary CodexSession.")
    args = parser.parse_args(argv)
    result = run_smoke(args.cwd)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
