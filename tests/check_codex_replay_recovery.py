"""Check Codex replay recovery helpers stay useful without startup app-server I/O."""
import json
import sys
import tempfile
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
    assert CodexSession._drop_recover_noise([
        {"type": "result", "error": "Codex app-server exited. It will be restarted on the next send."},
        {"type": "result", "error": "real turn failure"},
    ]) == [{"type": "result", "error": "real turn failure"}]

    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "codex_s-local.json"
        state.write_text(json.dumps({
            "thread_id": "thread-local",
            "last_turn_id": "turn-local",
            "cwd": ".",
            "yolo": True,
            "events": history_events,
            "timeline": [{"type": "user", "message": {"role": "user", "content": "cached"}, "seq": 7}],
            "next_seq": 8,
        }), encoding="utf-8")

        original_history_snapshot = CodexSession.__dict__["history_snapshot"]

        def fail_history_snapshot(*_args, **_kwargs):
            raise AssertionError("recover must not call thread/read during startup")

        try:
            CodexSession.history_snapshot = classmethod(fail_history_snapshot)
            recovered = CodexSession.recover("s-local", ".", state_dir=td)
        finally:
            CodexSession.history_snapshot = original_history_snapshot

        assert recovered is not None
        assert recovered.thread_id == "thread-local"
        assert recovered.last_turn_id == "turn-local"
        assert recovered.timeline[0]["message"]["content"] == "cached"
        assert recovered._next_seq == 8
    print("ok")


if __name__ == "__main__":
    main()
