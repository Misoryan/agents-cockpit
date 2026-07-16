"""Check Codex notification adapter wrappers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_notifications import CodexNotificationAdapter  # noqa: E402


class FakeSession:
    def __init__(self):
        self.cwd = r"E:\repo"
        self._codex_debug_notices = []
        self._route_debug = []
        self._compact_in_progress = False
        self._busy = False
        self.current_turn_started_at = None
        self.broadcasts = []
        self.records = []

    def _broadcast(self, event):
        self.broadcasts.append(event)

    def _record_and_broadcast(self, event):
        self.records.append(event)


def main():
    session = FakeSession()
    adapter = CodexNotificationAdapter(session)

    adapter.codex_notice("hello", "test/method", {"x": 1})
    assert session.broadcasts[-1]["message"] == "hello"
    assert session.broadcasts[-1]["method"] == "test/method"

    adapter.codex_notice("silent", "test/silent", silent=True)
    assert session._codex_debug_notices[-1]["message"] == "silent"

    assert CodexNotificationAdapter.updated_event_notice_message({"message": "changed"}) == "changed"

    session._compact_in_progress = True
    session._busy = True
    session.current_turn_started_at = 1.0
    adapter.handle_notification("thread/compacted", {})
    assert session.records[-1] == {"type": "compacted"}
    assert session._compact_in_progress is False
    assert session._busy is False
    assert session.current_turn_started_at is None

    usage = CodexNotificationAdapter.usage_for_meta({"last": {"inputTokens": 1, "outputTokens": 2}})
    assert usage["input_tokens"] == 1
    assert usage["output_tokens"] == 2

    print("codex notification adapter checks passed")


if __name__ == "__main__":
    main()
