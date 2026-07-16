"""Check Codex recovery replay prefers real thread history over notice-only timelines."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_native import CodexSession  # noqa: E402


def main():
    ns = CodexSession("s-test", ".")
    ns.timeline = [
        {"type": "codex_notice", "message": "settings failed", "seq": 1},
        {"type": "mode_state", "plan": False, "seq": 2},
    ]
    history_events = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "world"}]}},
        {"type": "result", "duration_ms": 1},
    ]

    ns._adopt_history_replay(history_events)

    assert ns.events == history_events
    assert ns.timeline == history_events
    assert CodexSession._replay_content_score(ns.timeline) == 3
    print("ok")


if __name__ == "__main__":
    main()
