"""Check extracted native replay helper functions."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_replay  # noqa: E402


class FakeSession:
    def __init__(self):
        self.sid = "s1"
        self.events = []
        self._next_seq = 1
        self._busy = False
        self.plan_mode = False
        self.task_mode = True


def main():
    session = FakeSession()
    assert native_replay.seq_value({"seq": "3"}) == 3
    assert native_replay.seq_value({"seq": "bad"}) == 0

    first = native_replay.record_event(session, {"type": "user"})
    assert first["seq"] == 1
    assert first["event_id"] == "s1:1"
    explicit = native_replay.record_event(session, {"type": "assistant", "seq": 5, "event_id": "custom"})
    assert explicit["seq"] == 5
    assert explicit["event_id"] == "custom"
    assert session._next_seq == 6
    assert native_replay.last_seq(session) == 5
    assert [event["seq"] for event in native_replay.events_after_seq(session, 1)] == [5]

    native_replay.load_events(session, [{"type": "old", "seq": 9}, {"type": "new"}], next_seq=20)
    assert [event["seq"] for event in session.events] == [9, 10]
    assert session._next_seq == 20

    pending = native_replay.pending_events_snapshot([
        ("approve-1", {"kind": "approve", "tool": "Edit", "input": {"file_path": "a.py"},
                       "preview": "a.py", "danger": True}),
        ("ask-1", {"kind": "ask", "question": "Pick?", "questions": [{"id": "q1"}]}),
    ])
    assert pending[0]["type"] == "pending_approval"
    assert pending[0]["danger"] is True
    assert pending[1]["type"] == "pending_ask"

    payload = native_replay.replay_payload(session, session.events, pending, model="sonnet",
                                           after_seq=0, state_fn=lambda: "confirm")
    assert payload["ok"] is True
    assert payload["snapshot"]["state"] == "confirm"
    assert payload["snapshot"]["task"] is True
    assert payload["pending"][0] == {"type": "system", "model": "sonnet"}
    assert payload["last_seq"] == 19

    print("native replay helper checks passed")


if __name__ == "__main__":
    main()
