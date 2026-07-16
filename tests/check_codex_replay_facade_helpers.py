"""Check the Codex replay facade preserves replay helper behavior."""
import sys
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_replay  # noqa: E402
from codex_replay_facade import CodexReplayFacade  # noqa: E402


class FakeSession:
    def __init__(self):
        self.sid = "facade"
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self.clients_lock = threading.Lock()
        self.clients = set()
        self._closed = False
        self._next_seq = 1
        self.timeline = []
        self.events = []
        self.poll_events = []
        self._last_persist = 0.0
        self.persisted = []
        self._busy = False
        self.plan_mode = False
        self.task_mode = False
        self.current_turn_started_at = None
        self._route_debug = []
        self.facade = CodexReplayFacade(self, 5, 80)

    def state(self):
        return "idle"

    def _events_after_seq(self, after_seq=0):
        return self.facade.events_after_seq(after_seq)

    def _state_snapshot(self):
        return {"type": "state_snapshot", "state": self.state(), "last_seq": self._next_seq - 1}

    def _pending_events_snapshot(self):
        with self._pending_lock:
            return codex_replay.pending_events_snapshot(list(self._pending.items()))

    def _persist(self):
        self.persisted.append(self._last_persist)


class FakeSock:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeThread:
    started = []

    def __init__(self, target=None, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.started.append(self.daemon)


def main():
    assert CodexReplayFacade.is_dangerous("rm -rf /tmp/x")
    assert not CodexReplayFacade.is_dangerous("echo ok")

    identity_session = FakeSession()
    seq, event_id = identity_session.facade.event_identity_locked({"type": "assistant"})
    assert seq == 1
    assert event_id == "facade-000001-assistant"

    session = FakeSession()
    first = session.facade.prepare_broadcast({"type": "assistant"})
    assert first["seq"] == 1
    assert first["event_id"] == "facade-000001-assistant"
    assert session.poll_events == [first]
    assert session.facade.prepare_broadcast({"type": "state_snapshot"})["type"] == "state_snapshot"
    assert [event["type"] for event in session.poll_events] == ["assistant"]

    second = session.facade.prepare_broadcast({"type": "result"})
    assert second["seq"] == 2
    assert [event["seq"] for event in session.facade.events_after_seq(1)] == [2]
    assert CodexReplayFacade.event_after_seq(second, 1)

    payload = session.facade.replay_payload(after_seq=1)
    assert payload["ok"] is True
    assert [event["seq"] for event in payload["events"]] == [2]
    assert payload["snapshot"]["type"] == "state_snapshot"
    session._pending = {
        "approve": {"kind": "approve", "name": "Run", "params": {"cmd": "x"}}
    }
    initial = session.facade.initial_client_events(after_seq=1)
    assert [event["type"] for event in initial] == ["replay_batch", "state_snapshot", "pending_approval"]
    assert [event["seq"] for event in initial[0]["events"]] == [2]

    assert session.facade.persist_if_due({"type": "mode_state"}, now_fn=lambda: 1.0) is False
    assert session.persisted == []
    assert session.facade.persist_if_due({"type": "mode_state"}, now_fn=lambda: 2.0) is True
    assert session.persisted == [2.0]
    assert session.facade.persist_if_due({"type": "assistant"}, now_fn=lambda: 2.1) is True
    assert session.persisted == [2.0, 2.1]

    history = [{"type": "user"}, {"type": "assistant"}, {"type": "result"}]
    session.facade.adopt_history_replay(history)
    assert [event["seq"] for event in session.timeline] == [1, 2, 3]
    assert CodexReplayFacade.replay_content_score(session.timeline) == 3
    assert CodexReplayFacade.drop_recover_noise([
        {"type": "result", "error": "Codex app-server exited. restart"},
        {"type": "result", "error": "real failure"},
    ]) == [{"type": "result", "error": "real failure"}]

    client_session = FakeSession()
    client_session.facade.prepare_broadcast({"type": "assistant"})
    client_session._pending = {
        "approve": {"kind": "approve", "name": "Run", "params": {"cmd": "x"}}
    }
    sock = FakeSock()
    sent = []
    FakeThread.started = []
    client_session.facade.add_client(
        sock,
        after_seq=0,
        send_one=lambda _sock, event: sent.append(event),
        ws_send_fn=lambda *_args: None,
        ws_recv_fn=lambda _sock: (0x8, b""),
        thread_factory=FakeThread,
    )
    assert [event["type"] for event in sent] == ["replay_batch", "state_snapshot", "pending_approval"]
    assert sock not in client_session.clients
    assert sock.closed is True
    assert FakeThread.started == [True]

    print("codex replay facade helper checks passed")


if __name__ == "__main__":
    main()
