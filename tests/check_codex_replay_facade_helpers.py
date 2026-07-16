"""Check the Codex replay facade preserves replay helper behavior."""
import sys
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_replay_facade import CodexReplayFacade  # noqa: E402


class FakeSession:
    def __init__(self):
        self.sid = "facade"
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._next_seq = 1
        self.timeline = []
        self.events = []
        self.poll_events = []
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
        return []


def main():
    assert CodexReplayFacade.is_dangerous("rm -rf /tmp/x")
    assert not CodexReplayFacade.is_dangerous("echo ok")

    identity_session = FakeSession()
    seq, event_id = identity_session.facade.event_identity_locked({"type": "assistant"})
    assert seq == 1
    assert event_id == "facade-000001-assistant"

    session = FakeSession()
    first = session.facade.decorate_for_broadcast({"type": "assistant"})
    assert first["seq"] == 1
    assert first["event_id"] == "facade-000001-assistant"

    second = session.facade.record_timeline_locked({"type": "result"})
    assert second["seq"] == 2
    assert [event["seq"] for event in session.facade.events_after_seq(1)] == [2]
    assert CodexReplayFacade.event_after_seq(second, 1)

    payload = session.facade.replay_payload(after_seq=1)
    assert payload["ok"] is True
    assert [event["seq"] for event in payload["events"]] == [2]
    assert payload["snapshot"]["type"] == "state_snapshot"

    history = [{"type": "user"}, {"type": "assistant"}, {"type": "result"}]
    session.facade.adopt_history_replay(history)
    assert [event["seq"] for event in session.timeline] == [1, 2, 3]
    assert CodexReplayFacade.replay_content_score(session.timeline) == 3
    assert CodexReplayFacade.drop_recover_noise([
        {"type": "result", "error": "Codex app-server exited. restart"},
        {"type": "result", "error": "real failure"},
    ]) == [{"type": "result", "error": "real failure"}]

    print("codex replay facade helper checks passed")


if __name__ == "__main__":
    main()
