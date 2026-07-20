"""Check compact Work View summaries preserve important non-chat feedback."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import work_summary  # noqa: E402


def main():
    notice = work_summary.summarize_events([
        {"type": "codex_notice", "message": "Model set", "method": "slash/model", "seq": 7},
    ], snapshot={"state": "idle"})
    assert notice["last_seq"] == 7
    assert notice["turn_count"] == 0
    assert notice["turns"] == []
    assert len(notice["notices"]) == 1
    assert notice["notices"][0]["type"] == "work_notice"
    assert "Codex: Model set" in notice["notices"][0]["text"]
    assert "slash/model" in notice["notices"][0]["text"]

    running = work_summary.summarize_events([
        {"type": "user", "message": {"role": "user", "content": "make it calm"}, "seq": 1},
        {"type": "codex_notice", "message": "Config warning", "seq": 2},
        {"type": "result", "seq": 3},
    ], snapshot={"state": "idle"})
    assert running["turn_count"] == 1
    assert running["turns"][0]["user_text"] == "make it calm"
    assert "Config warning" in running["turns"][0]["assistant_text"]

    debug = work_summary.summarize_events([
        {"type": "codex_notice", "message": "hidden", "level": "debug", "seq": 1},
        {"type": "codex_notice", "message": "silent", "silent": True, "seq": 2},
    ], snapshot={"state": "idle"})
    assert debug["turns"] == []
    assert debug["notices"] == []
    assert debug["last_seq"] == 2

    orphan = work_summary.summarize_events([
        {"type": "turn_started", "seq": 1},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "orphan"}]}, "seq": 2},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "done"}]}, "seq": 3},
        {"type": "result", "seq": 4},
    ], snapshot={"state": "idle"})
    assert orphan["last_seq"] == 4
    assert orphan["turn_count"] == 0
    assert orphan["turns"] == []

    class Session:
        pass

    calls = {"count": 0}

    def events_fn():
        calls["count"] += 1
        return [
            {"type": "user", "message": {"role": "user", "content": "cache me"}, "seq": 1},
            {"type": "turn_started", "seq": 2},
        ]

    session = Session()
    first = work_summary.replay_payload_cached(
        session, events_fn,
        {"state": "running", "running": True, "last_seq": 2, "turn_elapsed_ms": 1000, "turn_started_at_ms": 10},
        [],
    )
    second = work_summary.replay_payload_cached(
        session, events_fn,
        {"state": "running", "running": True, "last_seq": 2, "turn_elapsed_ms": 5000, "turn_started_at_ms": 10},
        [],
    )
    assert calls["count"] == 1
    assert first["work"]["turns"][-1]["elapsed_ms"] == 1000
    assert second["work"]["turns"][-1]["elapsed_ms"] == 5000
    assert second["snapshot"]["turn_elapsed_ms"] == 5000

    print("work summary helper checks passed")


if __name__ == "__main__":
    main()
