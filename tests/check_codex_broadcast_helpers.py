"""Checks for Codex broadcast/push helper behavior."""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_broadcast import CodexBroadcastAdapter


class FakeReplay:
    def __init__(self):
        self.prepared = []

    def prepare_broadcast(self, event):
        out = dict(event)
        out["seq"] = len(self.prepared) + 1
        self.prepared.append(out)
        return out


class FakeSession:
    def __init__(self):
        self.clients_lock = threading.Lock()
        self.clients = {"ok", "dead"}
        self._replay = FakeReplay()
        self.persisted = []
        self._last_notify = {}
        self.last_activity = 0.0

    def _persist_if_due(self, event):
        self.persisted.append(event)


class FakeNotify:
    NOTIFY_MIN_INTERVAL = 10

    def __init__(self):
        self.enabled = True
        self.calls = []

    def _notify_enabled_for(self, event):
        return self.enabled and event != "off"

    def push_notify(self, title, body, event, webhook_body=None):
        self.calls.append((title, body, event, webhook_body))


class ImmediateThread:
    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        self.target(*self.args)


def test_broadcast_prunes_dead_clients_and_persists():
    sent = []

    def ws_send(sock, data, opcode):
        if sock == "dead":
            raise OSError("closed")
        sent.append((sock, data.decode("utf-8"), opcode))

    session = FakeSession()
    adapter = CodexBroadcastAdapter(session, ws_send, FakeNotify(), time_fn=lambda: 123.5)
    out = adapter.broadcast({"type": "assistant", "text": "你好"})

    assert out["seq"] == 1
    assert session.last_activity == 123.5
    assert session.persisted == [out]
    assert session.clients == {"ok"}
    assert sent == [("ok", '{"type": "assistant", "text": "你好", "seq": 1}', 0x1)]


def test_transient_skips_replay_and_persist():
    sent = []
    session = FakeSession()
    adapter = CodexBroadcastAdapter(
        session, lambda sock, data, opcode: sent.append((sock, data, opcode)), FakeNotify())

    adapter.broadcast_transient({"type": "state_snapshot"})

    assert session._replay.prepared == []
    assert session.persisted == []
    assert len(sent) == 2


def test_status_broadcast_does_not_refresh_activity():
    session = FakeSession()
    adapter = CodexBroadcastAdapter(session, lambda *_: None, FakeNotify(), time_fn=lambda: 123.5)

    adapter.broadcast({"type": "codex_usage", "usage": {}})

    assert session.last_activity == 0.0


def test_send_one_prunes_failed_socket():
    session = FakeSession()
    adapter = CodexBroadcastAdapter(
        session, lambda sock, data, opcode: (_ for _ in ()).throw(OSError("closed")),
        FakeNotify())

    adapter.send_one("ok", {"type": "state_snapshot"})

    assert "ok" not in session.clients


def test_push_notify_throttle_and_disabled():
    now = [100.0]
    notify = FakeNotify()
    session = FakeSession()
    adapter = CodexBroadcastAdapter(
        session, lambda *_: None, notify, thread_factory=ImmediateThread,
        time_fn=lambda: now[0])

    assert adapter.push("done", "Title", "Body", webhook_body="final answer") is True
    assert notify.calls == [("Title", "Body", "done", "final answer")]
    assert adapter.push("done", "Again", "Body") is False
    now[0] = 111.0
    assert adapter.push("done", "Again", "Body") is True
    assert len(notify.calls) == 2
    assert adapter.push("off", "Off", "Body") is False


if __name__ == "__main__":
    test_broadcast_prunes_dead_clients_and_persists()
    test_transient_skips_replay_and_persist()
    test_status_broadcast_does_not_refresh_activity()
    test_send_one_prunes_failed_socket()
    test_push_notify_throttle_and_disabled()
    print("codex broadcast helper checks passed")
