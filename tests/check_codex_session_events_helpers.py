"""Check Codex session event helper behavior."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_session_events  # noqa: E402


class FakeSession:
    def __init__(self):
        self.cwd = r"E:\repo"
        self._plan_output = {}
        self._awaiting_plan_decision = False
        self._compact_in_progress = False
        self._busy = False
        self.current_turn_started_at = None
        self.terminals = {}
        self.pushes = []
        self.records = []
        self.broadcasts = []

    def _push(self, event, title, body, webhook_body=None):
        self.pushes.append((event, title, body, webhook_body))

    def _record_and_broadcast(self, event):
        self.records.append(event)

    def _broadcast(self, event):
        self.broadcasts.append(event)

    def _tool_result_from_item(self, item):
        return None

    def terminal_interaction_event(self, params):
        event = {
            "type": "terminal_interaction",
            "process_id": params.get("processId"),
            "item_id": params.get("itemId"),
            "stdin": params.get("stdin") or "",
        }
        self.terminals[event["process_id"]] = event
        return event


def main():
    session = FakeSession()
    codex_session_events.on_item_completed(session, {"type": "plan", "id": "p1", "text": "do it"})
    assert session._awaiting_plan_decision is True
    assert session.pushes[0][:3] == (
        "plan",
        "计划待审阅 · repo",
        "Codex\n点击打开会话审阅计划\n" + r"E:\repo",
    )
    assert session.records[0]["message"]["content"][0]["text"] == "<proposed_plan>\ndo it\n</proposed_plan>"

    session = FakeSession()
    session._plan_output = {"p2": "continue"}
    codex_session_events.flush_pending_plan_items(session)
    assert session.pushes[0][1] == "计划待审阅 · repo"
    assert "点击打开会话审阅计划" in session.pushes[0][2]

    session = FakeSession()
    session._compact_in_progress = True
    session._busy = True
    session.current_turn_started_at = 123.0
    codex_session_events.handle_notification(session, "thread/compacted", {})
    assert session.records == [{"type": "compacted"}]
    assert session._compact_in_progress is False
    assert session._busy is False
    assert session.current_turn_started_at is None

    session = FakeSession()
    codex_session_events.handle_notification(session, "thread/unarchived", {"threadId": "t1"})
    assert session.broadcasts[0]["message"] == "Thread unarchived in Codex history"
    session = FakeSession()
    codex_session_events.handle_notification(
        session,
        "thread/goal/updated",
        {"threadId": "t1", "goal": {"objective": "Ship", "status": "active", "tokensUsed": 3}},
    )
    assert session.broadcasts[0]["message"].startswith("Goal updated: [active, tokens 3] Ship")
    session = FakeSession()
    codex_session_events.handle_notification(session, "thread/goal/cleared", {"threadId": "t1"})
    assert session.broadcasts[0]["message"] == "Goal cleared"

    session = FakeSession()
    codex_session_events.handle_notification(
        session,
        "item/commandExecution/terminalInteraction",
        {"processId": "p1", "itemId": "i1", "stdin": "Password:"},
    )
    assert session.records == [{
        "type": "terminal_interaction",
        "process_id": "p1",
        "item_id": "i1",
        "stdin": "Password:",
    }]

    print("codex session event helper checks passed")


if __name__ == "__main__":
    main()
