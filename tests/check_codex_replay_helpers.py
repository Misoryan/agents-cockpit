"""Check extracted Codex replay/timeline helpers."""
import sys
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_native  # noqa: E402
import codex_replay  # noqa: E402


class FakeSession:
    def __init__(self):
        self.sid = "s1"
        self._next_seq = 1
        self.timeline = []
        self.events = []
        self.poll_events = []
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending = {}
        self._busy = False
        self.plan_mode = False
        self.task_mode = True
        self.current_turn_started_at = None
        self._route_debug = ["a", "b"]

    def state(self):
        return "running" if self._busy else "idle"

    def _state_snapshot(self):
        with self._pending_lock:
            pending = list(self._pending.items())
        return codex_replay.state_snapshot(self, pending, now_fn=lambda: 100.0)

    def _events_after_seq(self, after_seq=0):
        return codex_replay.events_after_seq(self, after_seq)

    def _pending_events_snapshot(self):
        with self._pending_lock:
            pending = list(self._pending.items())
        return codex_replay.pending_events_snapshot(pending)


def _tool_result(tool_id, content):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content}
    ]}}


def main():
    assert codex_replay.is_dangerous("rm -rf /tmp/x")
    assert not codex_replay.is_dangerous("echo ok")
    assert codex_native.CodexSession._is_dangerous("shutdown /s")

    session = FakeSession()
    first = codex_replay.record_timeline(session, {"type": "assistant"}, 10, 100)
    assert first["seq"] == 1
    assert first["event_id"] == "s1-000001-assistant"
    assert session._next_seq == 2

    stream_1 = codex_replay.record_timeline(
        session, {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "hello"}}}, 10, 100)
    stream_2 = codex_replay.record_timeline(
        session, {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": " world"}}}, 10, 100)
    assert stream_2["seq"] == 3
    assert session.timeline[-1] is stream_1
    assert session.timeline[-1]["event"]["delta"]["text"] == "hello world"
    assert session.timeline[-1]["merged_seq"] == 3
    assert session.timeline[-1]["_stream_chunks"] == [
        {"seq": 2, "text": "hello"},
        {"seq": 3, "text": " world"},
    ]
    inc_stream = codex_replay.events_after_seq(session, 2)
    assert len(inc_stream) == 1
    assert inc_stream[0].pop("ts") > 0
    assert inc_stream == [{
        "type": "stream_event",
        "event": {"delta": {"type": "text_delta", "text": " world"}},
        "seq": 3,
        "event_id": "s1-000002-stream_event-after-2",
        "merged_seq": 3,
    }]

    tool_1 = codex_replay.record_timeline(session, _tool_result("tool-1", "old"), 10, 100)
    tool_2 = codex_replay.record_timeline(session, _tool_result("tool-1", "new"), 10, 100)
    assert tool_1["message"]["content"][0]["content"] == "new"
    assert tool_1["merged_seq"] == tool_2["seq"]
    assert codex_replay.tool_result_id(tool_1) == "tool-1"

    assert codex_replay.replay_content_score([{"type": "assistant"}, {"type": "mode_state"}]) == 1
    assert codex_replay.drop_recover_noise([
        {"type": "result", "error": "Codex app-server exited. restart"},
        {"type": "assistant"},
    ]) == [{"type": "assistant"}]

    other = FakeSession()
    other.timeline = [{"type": "mode_state"}]
    codex_replay.adopt_history_replay(other, [{"type": "assistant"}, {"type": "result"}], 1)
    assert len(other.timeline) == 1
    assert other.timeline[0]["type"] == "result"
    assert other.timeline[0]["seq"] == 2
    assert len(other.events) == 2
    assert other.events[0]["seq"] == 1
    assert other._next_seq == 3

    assert codex_replay.event_after_seq({"seq": 2}, 1)
    assert codex_replay.event_after_seq({"seq": 1, "merged_seq": 3}, 2)
    assert not codex_replay.event_after_seq({"seq": 1}, 2)
    assert codex_replay.trim_stream_event_after(
        {"type": "stream_event", "seq": 1, "merged_seq": 3,
         "event": {"delta": {"type": "text_delta", "text": "old new"}}},
        2,
    ) is None
    session.poll_events = [{"seq": 99, "type": "assistant"}]
    assert codex_replay.events_after_seq(session, 10) == [{"seq": 99, "type": "assistant"}]

    session._pending = {
        "approve": {"kind": "approve", "name": "Run", "params": {"cmd": "x"}, "preview": "x", "danger": True},
        "ask": {"kind": "ask", "question": "Pick?", "questions": [], "auto_resolution_ms": 60000},
        "form": {"kind": "form", "message": "Fill", "params": {"mode": "edit", "serverName": "srv"},
                 "fields": [{"id": "x"}], "schema_detail": "{}"},
    }
    pending = codex_replay.pending_events_snapshot(list(session._pending.items()))
    assert [event["type"] for event in pending] == ["pending_approval", "pending_ask", "pending_form"]
    assert pending[0]["danger"] is True
    assert pending[1]["auto_resolution_ms"] == 60000
    assert pending[2]["server_name"] == "srv"

    session._busy = True
    session.current_turn_started_at = 90.0
    state = codex_replay.state_snapshot(session, list(session._pending.items()), now_fn=lambda: 100.0)
    assert state["state"] == "running"
    assert state["task"] is True
    assert state["turn_elapsed_ms"] == 10000
    assert state["last_seq"] == session._next_seq - 1
    assert state["route_debug"] == ["a", "b"]

    payload = codex_replay.replay_payload(session, after_seq=10)
    assert payload["ok"] is True
    assert payload["events"] == [{"seq": 99, "type": "assistant"}]
    assert payload["pending"] == pending
    assert payload["last_seq"] == payload["snapshot"]["last_seq"]

    work_session = FakeSession()
    codex_replay.record_timeline(work_session, {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "fix it"}]},
    }, 20, 100)
    codex_replay.record_timeline(work_session, {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "cmd-1", "name": "PowerShell",
                                  "input": {"command": "echo ok", "cwd": "E:/repo"}}]},
    }, 20, 100)
    codex_replay.record_timeline(work_session, _tool_result("cmd-1", "ok\nexit code: 0\nduration ms: 10"), 20, 100)
    codex_replay.record_timeline(work_session, {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "done"}]},
    }, 20, 100)
    codex_replay.record_timeline(work_session, {"type": "result", "duration_ms": 10}, 20, 100)
    work_payload = codex_replay.replay_payload(work_session, view="work")
    assert work_payload["events"] == []
    assert work_payload["work"]["turn_count"] == 1
    assert work_payload["work"]["turns"][0]["user_text"] == "fix it"
    assert work_payload["work"]["tool_total"] == 1
    assert work_payload["work"]["turns"][0]["tool_total"] == 1
    assert work_payload["work"]["turns"][0]["tool_summary"] == [{"name": "PowerShell", "count": 1}]
    assert work_payload["work"]["turns"][0]["tools"] == []
    assert work_payload["work"]["turns"][0]["latest_tool"] is None
    assert work_payload["work"]["turns"][0]["assistant_text"] == "done"
    assert work_payload["work"]["turns"][0]["assistant_text_hidden"] is True
    assert work_payload["work"]["turns"][0]["assistant_text_chars"] == 4
    turn_payload = codex_replay.replay_payload(work_session, view="turn", turn="turn-1")
    assert turn_payload["ok"] is True
    assert [event["type"] for event in turn_payload["events"]] == ["user", "assistant", "user", "assistant", "result"]
    assert codex_replay.replay_payload(work_session, view="turn", turn="missing")["ok"] is False

    diff_session = FakeSession()
    codex_replay.record_timeline(diff_session, {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "patch file"}]},
    }, 20, 100)
    codex_replay.record_timeline(diff_session, {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "cmd-diff", "name": "PowerShell",
                                  "input": {"command": "git diff", "cwd": "E:/repo"}}]},
    }, 20, 100)
    codex_replay.record_timeline(diff_session, _tool_result("cmd-diff",
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-old\n+new\n+again\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@\n-gone\n+back"), 20, 100)
    codex_replay.record_timeline(diff_session, {"type": "result", "duration_ms": 5}, 20, 100)
    diff_turn = codex_replay.replay_payload(diff_session, view="work")["work"]["turns"][0]
    assert diff_turn["diff_added"] == 3
    assert diff_turn["diff_deleted"] == 2
    assert diff_turn["diff_total"] == 5
    assert diff_turn["changed_files"] == [
        {"path": "a.py", "added": 2, "deleted": 1, "total": 3},
        {"path": "b.py", "added": 1, "deleted": 1, "total": 2},
    ]

    running_session = FakeSession()
    codex_replay.record_timeline(running_session, {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "run tests"}]},
    }, 20, 100)
    codex_replay.record_timeline(running_session, {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "cmd-2", "name": "PowerShell",
                                  "input": {"command": "pytest tests", "cwd": "E:/repo"}}]},
    }, 20, 100)
    codex_replay.record_timeline(running_session, _tool_result("cmd-2", "ok\nexit code: 0\nduration ms: 15"), 20, 100)
    running_session._busy = True
    running_session.current_turn_started_at = 95.0
    running_payload = codex_replay.replay_payload(running_session, view="work")
    running_turn = running_payload["work"]["turns"][0]
    assert running_turn["status"] == "running"
    assert running_turn["elapsed_ms"] == 5000
    assert running_turn["tool_total"] == 1
    assert running_turn["latest_tool"]["name"] == "PowerShell"
    assert running_turn["latest_tool"]["label"] == "pytest tests"
    assert running_turn["latest_tool"]["input"] == {"command": "pytest tests", "cwd": "E:/repo"}
    assert running_turn["latest_tool"]["result"] == "ok\nexit code: 0\nduration ms: 15"
    assert running_turn["latest_tool"]["preview"] == "ok\nexit code: 0\nduration ms: 15"
    assert running_turn["tools"] == [running_turn["latest_tool"]]

    stream_work = FakeSession()
    codex_replay.record_timeline(stream_work, {
        "type": "user",
        "message": {"content": [{"type": "text", "text": "summarize"}]},
    }, 20, 100)
    codex_replay.record_timeline(stream_work, {
        "type": "stream_event",
        "event": {"delta": {"type": "text_delta", "text": "streamed "}},
    }, 20, 100)
    codex_replay.record_timeline(stream_work, {
        "type": "stream_event",
        "event": {"delta": {"type": "text_delta", "text": "summary"}},
    }, 20, 100)
    codex_replay.record_timeline(stream_work, {"type": "result", "duration_ms": 5}, 20, 100)
    stream_turn = codex_replay.replay_payload(stream_work, view="work")["work"]["turns"][0]
    assert stream_turn["assistant_text"] == "streamed summary"
    assert stream_turn["assistant_text_hidden"] is True

    print("codex replay helper checks passed")


if __name__ == "__main__":
    main()
