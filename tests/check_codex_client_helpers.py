"""Check extracted Codex app-server client helpers."""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_client  # noqa: E402
import codex_native  # noqa: E402


class FakeStdin:
    def __init__(self):
        self.lines = []
        self.flushed = False

    def write(self, line):
        self.lines.append(line)

    def flush(self):
        self.flushed = True


class FakeProc:
    def __init__(self):
        self.stdin = FakeStdin()
        self.stdout = []
        self.stderr = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class FakeSession:
    def __init__(self, thread_id="thread-1", busy=False, closed=False):
        self.thread_id = thread_id
        self._busy = busy
        self._closed = closed
        self.notifications = []
        self.debug = []
        self.requests = []
        self.exited = False

    def handle_notification(self, method, params):
        self.notifications.append((method, params))

    def handle_server_request(self, req_id, method, params):
        self.requests.append((req_id, method, params))
        return {"handled": method}

    def _remember_route_debug(self, message, method=None, params=None):
        self.debug.append((message, method, params))

    def on_client_exit(self):
        self.exited = True


def main():
    err = codex_client.AppServerRequestError(-1, "bad")
    assert err.code == -1
    assert err.message == "bad"
    assert codex_native.CodexAppServerClient is codex_client.CodexAppServerClient
    assert codex_native.AppServerRequestError is codex_client.AppServerRequestError

    with tempfile.TemporaryDirectory() as td:
        client = codex_client.CodexAppServerClient(user="alice", uid="u1", state_dir=td)
        assert client.codex_home.endswith("codex-home")
        assert client._thread_id_from_params({"thread": {"sessionId": "t1"}}) == "t1"
        assert client._turn_id_from_params({"item": {"turnId": "turn-1"}}) == "turn-1"
        assert client._item_id_from_params({"item": {"id": "item-1"}}) == "item-1"

        for idx in range(45):
            client._log_tail("line-%d" % idx)
        assert len(client.stderr_tail) == 40
        assert client.stderr_tail[0] == "line-5"

        waiter = {"event": threading.Event(), "result": None, "error": None}
        client.pending["1"] = waiter
        client._dispatch({"id": "1", "result": {"ok": True}})
        assert waiter["event"].is_set()
        assert waiter["result"] == {"ok": True}
        assert "1" not in client.pending

        session = FakeSession()
        client.sessions["thread-1"] = session
        client._dispatch({"method": "item/updated", "params": {"threadId": "thread-1", "itemId": "item-1"}})
        assert session.notifications == [("item/updated", {"threadId": "thread-1", "itemId": "item-1"})]
        assert client.item_sessions["item-1"] is session

        busy = FakeSession(thread_id="busy-thread", busy=True)
        client.sessions = {"busy-thread": busy}
        client._dispatch({"method": "global/event", "params": {}})
        assert busy.notifications == [("global/event", {})]
        assert busy.debug[0][0] == "single-busy global fallback"

        client.unrouted_events = []
        client._buffer_unrouted("item/updated", {"threadId": "future", "itemId": "future-item"})
        assert len(client.unrouted_events) == 1
        future = FakeSession(thread_id="future")
        client._flush_unrouted(future, thread_id="future")
        assert client.unrouted_events == []
        assert future.notifications[0][0] == "item/updated"
        assert client.item_sessions["future-item"] is future

        proc = FakeProc()
        client.proc = proc
        client.initialized = True

        def resolve_request():
            deadline = time.time() + 1
            while time.time() < deadline:
                waiter = client.pending.get("1")
                if waiter:
                    waiter["result"] = {"done": True}
                    waiter["event"].set()
                    return
                time.sleep(0.01)

        threading.Thread(target=resolve_request, daemon=True).start()
        assert client.request("thread/list", {"limit": 1}, timeout=2, ensure_started=False) == {"done": True}
        written = json.loads(proc.stdin.lines[-1])
        assert written == {"id": "1", "method": "thread/list", "params": {"limit": 1}}
        assert proc.stdin.flushed is True

        try:
            client.request("slow", {}, timeout=0.01, ensure_started=False)
            raise AssertionError("expected timeout")
        except RuntimeError as exc:
            assert "timed out" in str(exc)

        pending = {"event": threading.Event(), "result": None, "error": None}
        client.pending["stopped"] = pending
        client.shutdown()
        assert proc.terminated is True
        assert pending["event"].is_set()
        assert pending["error"] == "Codex app-server stopped"
        assert client.proc is None
        assert client.initialized is False

    print("codex client helper checks passed")


if __name__ == "__main__":
    main()
