"""Check Codex pending request helper behavior."""
import sys
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_pending  # noqa: E402


class DummySession:
    def __init__(self):
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._terminal_processes = {}
        self.broadcasts = []
        self._busy = False
        self.current_turn_started_at = None
        self.plan_mode = False
        self.task_mode = False
        self._next_seq = 7
        self._route_debug = []

    def _broadcast(self, obj):
        self.broadcasts.append(dict(obj))

    def state(self):
        return "confirm" if codex_pending.has_pending(self) else "idle"


def main():
    s = DummySession()
    approve_event = threading.Event()
    ask_event = threading.Event()
    form_event = threading.Event()
    s._pending = {
        "approve-1": {
            "kind": "approve",
            "event": approve_event,
            "method": "Bash",
            "name": "Bash",
            "params": {"cmd": "echo ok"},
            "preview": "echo ok",
        },
        "ask-1": {"kind": "ask", "event": ask_event, "question": "Pick one?"},
        "form-1": {"kind": "form", "event": form_event, "message": "Fill form", "fields": []},
    }
    s._terminal_processes = {"proc-1": {"type": "terminal_interaction", "process_id": "proc-1"}}

    assert codex_pending.has_pending(s)
    assert codex_pending.pending_events_snapshot(s)[0]["type"] == "pending_approval"
    assert codex_pending.pending_events_snapshot(s)[-1]["process_id"] == "proc-1"
    snapshot = codex_pending.state_snapshot(s)
    assert snapshot["state"] == "confirm"
    assert snapshot["last_seq"] == 6

    assert codex_pending.approve(s, "approve-1", True, always=True) is True
    assert approve_event.is_set()
    assert s._pending["approve-1"]["allow"] is True
    assert s.broadcasts[-2]["type"] == "approval_decision"
    assert s.broadcasts[-1]["type"] == "auto_allow_added"
    assert codex_pending.approve(s, "missing", True) is False

    assert codex_pending.answer(s, "ask-1", "A") is True
    assert ask_event.is_set()
    assert s.broadcasts[-1] == {"type": "ask_answered", "tool_use_id": "ask-1"}
    assert codex_pending.answer(s, "form-1", {"value": 1}) is True
    assert form_event.is_set()
    assert s.broadcasts[-1] == {"type": "form_answered", "tool_use_id": "form-1"}
    assert codex_pending.answer(s, "approve-1", "no") is False

    assert codex_pending.clear_pending(s) is True
    assert s._pending == {}
    assert codex_pending.clear_pending(s) is False
    assert not codex_pending.has_pending(s)
    print("codex pending helper checks passed")


if __name__ == "__main__":
    main()
