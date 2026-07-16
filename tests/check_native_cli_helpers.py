"""Check extracted native CLI helper functions."""
import json
import sys
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_cli  # noqa: E402


class FakeProc:
    def __init__(self, stdout=None, stderr=None):
        self.stdout = stdout or []
        self.stderr = stderr or []
        self.killed = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class FakeSession:
    def __init__(self):
        self.sid = "s1"
        self.cwd = str(Path.cwd())
        self.claude_sid = ""
        self.model = ""
        self.last_activity = 0
        self._lock = threading.Lock()
        self._busy = False
        self._proc = None
        self._interrupted = False
        self._closed = False
        self.events = []
        self.broadcasts = []
        self.failures = []
        self.pushes = []
        self.persisted = 0
        self.one_round = (None, True, "")

    def _build_argv(self, prompt):
        return ["claude", "-p", prompt]

    def _process_env(self):
        return {"ENV": "1"}

    def _drain_stderr(self, proc, buf):
        native_cli.drain_stderr(proc, buf)

    def _record_event(self, event):
        copied = dict(event)
        self.events.append(copied)
        return copied

    def _broadcast(self, event):
        self.broadcasts.append(dict(event))

    def _record_and_broadcast(self, event):
        recorded = self._record_event(event)
        self._broadcast(recorded)
        return recorded

    def _run_one_round(self, prompt):
        return self.one_round

    def _dump_failure(self, tag, result_ev, stderr_text):
        self.failures.append((tag, result_ev, stderr_text))

    def _push(self, event, title, body, webhook_body=None):
        self.pushes.append((event, title, body, webhook_body))

    def _persist(self):
        self.persisted += 1


def main():
    session = FakeSession()
    proc = FakeProc(stdout=[
        "skip\n",
        json.dumps({"type": "system", "model": "sonnet", "session_id": "claude-sid"}) + "\n",
        json.dumps({"type": "assistant", "message": {"content": "hi"}}) + "\n",
        json.dumps({"type": "result", "ok": True}) + "\n",
    ], stderr=["warn\n"])
    old_popen = native_cli.subprocess.Popen
    try:
        native_cli.subprocess.Popen = lambda *args, **kwargs: proc
        result, clean, stderr_text = native_cli.run_one_round(session, "hello")
    finally:
        native_cli.subprocess.Popen = old_popen
    assert result == {"type": "result", "ok": True}
    assert clean is True
    assert stderr_text == "warn\n"
    assert session.claude_sid == "claude-sid"
    assert session.model == "sonnet"
    assert session.events[0]["type"] == "assistant"
    assert session.broadcasts[0]["type"] == "system"
    assert session.broadcasts[1]["type"] == "assistant"

    session = FakeSession()
    session.one_round = ({"type": "result", "message": {"content": [{"type": "text", "text": "done"}]}}, True, "")
    native_cli.run_cli(session, "hello", lambda _ev, _stderr: False, lambda _ev: "")
    assert session._busy is False
    assert session._proc is None
    assert session.persisted == 1
    assert session.pushes and session.pushes[0][0] == "done"

    session = FakeSession()
    session.one_round = ({"type": "result", "result": "API Error: 529 [1305]"}, True, "stderr")
    native_cli.run_cli(session, "hello", lambda _ev, _stderr: True, lambda _ev: "short")
    assert session.broadcasts[-1] == {"type": "rate_limited", "detail": "short"}
    assert session.failures[0][0] == "rate-limit/overload (1305/529)"
    assert session.pushes == []

    session = FakeSession()
    session.one_round = (None, True, "boom")
    native_cli.run_cli(session, "hello", lambda _ev, _stderr: False, lambda _ev: "")
    assert session.broadcasts[-1]["type"] == "result"
    assert "claude CLI" in session.broadcasts[-1]["error"]

    session = FakeSession()
    session._interrupted = True
    native_cli.run_cli(session, "hello", lambda _ev, _stderr: False, lambda _ev: "")
    assert session.broadcasts[-1] == {"type": "interrupted"}
    assert session._interrupted is False

    print("native cli helper checks passed")


if __name__ == "__main__":
    main()
