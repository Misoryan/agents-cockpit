"""Check extracted Codex app-server routing helpers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_native  # noqa: E402
import codex_routing  # noqa: E402


class FakeSession:
    def __init__(self, thread_id="", busy=False, closed=False):
        self.thread_id = thread_id
        self._busy = busy
        self._closed = closed
        self.notifications = []
        self.debug = []

    def _remember_route_debug(self, message, method=None, params=None):
        self.debug.append((message, method, params))

    def handle_notification(self, method, params):
        self.notifications.append((method, params))


def main():
    nested = {"item": {"id": "item-1", "turnId": "turn-1", "turn": {"threadId": "thread-from-turn"}}}
    assert codex_routing.thread_id_from_params({"threadId": "thread-1"}) == "thread-1"
    assert codex_routing.thread_id_from_params({"thread": {"sessionId": "thread-2"}}) == "thread-2"
    assert codex_routing.thread_id_from_params({"turn": {"thread": {"id": "thread-3"}}}) == "thread-3"
    assert codex_routing.thread_id_from_params(nested) == "thread-from-turn"
    assert codex_routing.turn_id_from_params(nested) == "turn-1"
    assert codex_routing.item_id_from_params(nested) == "item-1"
    assert codex_native.CodexAppServerClient._item_id_from_params(nested) == "item-1"

    session = FakeSession()
    sessions = {}
    turn_sessions = {}
    item_sessions = {}
    route = codex_routing.remember_item_route(
        {"threadId": "t", "turnId": "u", "itemId": "i"}, session, sessions, turn_sessions, item_sessions)
    assert route == ("t", "u", "i")
    assert codex_routing.session_from_params({"threadId": "t"}, sessions, turn_sessions, item_sessions) is session
    assert codex_routing.session_from_params({"turnId": "u"}, {}, turn_sessions, item_sessions) is session
    assert codex_routing.session_from_params({"itemId": "i"}, {}, {}, item_sessions) is session
    assert codex_routing.has_route_hint({"turnId": "u"})
    assert not codex_routing.has_route_hint({})

    assert codex_routing.single_busy_session({"a": FakeSession(busy=True)}) is not None
    assert codex_routing.single_busy_session({"a": FakeSession(busy=True), "b": FakeSession(busy=True)}) is None
    assert codex_routing.single_busy_session({"a": FakeSession(busy=True, closed=True)}) is None

    original_params = {"threadId": "t", "payload": {"x": 1}}
    entry = codex_routing.unrouted_entry("item/updated", original_params, now=100.0)
    original_params["payload"]["x"] = 2
    assert entry["params"]["payload"]["x"] == 1
    assert entry["thread_id"] == "t"
    buffered = codex_routing.buffered_unrouted([
        {"ts": 80.0, "method": "old"},
        {"ts": 99.0, "method": "fresh"},
    ], entry, now=100.0, ttl=10.0, max_events=2)
    assert [item["method"] for item in buffered] == ["fresh", "item/updated"]

    by_thread = FakeSession(thread_id="t")
    keep, replay = codex_routing.split_unrouted_for_session(
        [
            {"thread_id": "t", "ts": 100.0, "method": "thread"},
            {"turn_id": "u", "ts": 100.0, "method": "turn"},
            {"item_id": "i", "ts": 100.0, "method": "item"},
            {"thread_id": "other", "ts": 80.0, "method": "expired"},
        ],
        by_thread,
        turn_id="u",
        now=101.0,
        ttl=10.0,
        max_events=10,
    )
    assert [item["method"] for item in replay] == ["thread", "turn"]
    assert [item["method"] for item in keep] == ["item"]

    print("codex routing helper checks passed")


if __name__ == "__main__":
    main()
