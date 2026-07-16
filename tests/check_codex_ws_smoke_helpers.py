"""Check helper logic for the Codex WebSocket smoke probe."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import codex_ws_smoke  # noqa: E402


def main():
    events = [
        {"type": "replay_batch", "events": [
            {"type": "assistant", "seq": 2},
            {"type": "assistant", "merged_seq": 3},
        ]},
        {"type": "state_snapshot", "last_seq": 5},
        {"type": "mode_state", "seq": 6},
        {"type": "assistant", "seq": 4},
    ]
    assert codex_ws_smoke._max_seq(events) == 6
    assert codex_ws_smoke._replay_event_count(events) == 2
    assert codex_ws_smoke._state_snapshot_count(events) == 1
    assert codex_ws_smoke._type_count(events, "mode_state") == 1
    assert codex_ws_smoke._client_summary(events) == {
        "types": ["replay_batch", "state_snapshot", "mode_state", "assistant"],
        "last_seq": 6,
        "replay_events": 2,
        "state_snapshots": 1,
        "mode_state_events": 1,
    }
    print("codex websocket smoke helper checks passed")


if __name__ == "__main__":
    main()
