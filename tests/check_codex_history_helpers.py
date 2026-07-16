"""Check extracted Codex thread history helpers."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_history  # noqa: E402
import codex_native  # noqa: E402
import codex_thread_history  # noqa: E402


def main():
    assert codex_history.epoch("1000") == 1000
    assert codex_history.epoch(100000000001) == 100000000.001
    assert codex_history.epoch("bad") == 0

    thread = {
        "id": "thread-1",
        "cwd": "repo",
        "recencyAt": 2000,
        "name": "Named",
        "source": "test",
    }
    item = codex_history.thread_history_item(thread, archived=True)
    assert item["session_id"] == "thread-1"
    assert item["title"] == "Named"
    assert item["archived"] is True
    assert codex_native._thread_id({"sessionId": "sid"}) == "sid"
    assert codex_native._thread_title({}) == "(Untitled)"

    filtered = codex_history.filter_thread_history_items([
        {"thread_id": "a", "title": "old", "ts": 1},
        {"thread_id": "a", "title": "new", "ts": 2},
        {"session_id": "b", "title": "Beta", "cwd": "repo", "ts": 3},
    ], limit=5, search="bet")
    assert filtered == [{"session_id": "b", "title": "Beta", "cwd": "repo", "ts": 3}]

    with tempfile.TemporaryDirectory() as td:
        cwd = os.path.join(td, "repo")
        os.makedirs(cwd, exist_ok=True)
        Path(td, "codex_s1.json").write_text(json.dumps({"thread_id": "local-1", "cwd": cwd}), encoding="utf-8")
        Path(td, "codex_s2.json").write_text(json.dumps({"cwd": cwd}), encoding="utf-8")
        local_items = codex_history.local_thread_history_items(state_dir=td)
        assert len(local_items) == 1
        assert local_items[0]["thread_id"] == "local-1"
        assert local_items[0]["title"] == "repo"

        codex_history.write_thread_history_cache([
            {"thread_id": "cached-1", "session_id": "cached-1", "title": "Cached", "cwd": "x",
             "ts": time.time() + 100}
        ], state_dir=td)
        assert Path(codex_history.history_cache_path(td)).exists()
        merged = codex_history.read_thread_history_cache(limit=10, state_dir=td)
        assert [entry["thread_id"] for entry in merged] == ["cached-1", "local-1"]
        assert codex_history.read_thread_history_cache(archived=True, state_dir=td) == []

        old_state = codex_native.STATE_DIR
        try:
            codex_native.STATE_DIR = td
            wrapped = codex_native._read_thread_history_cache(limit=1)
            assert wrapped[0]["thread_id"] == "cached-1"
        finally:
            codex_native.STATE_DIR = old_state

    class FakeHistoryClient:
        def __init__(self):
            self.calls = []

        def request(self, method, params, timeout=0):
            self.calls.append((method, params, timeout))
            if method == "thread/fork":
                return {"thread": {"id": "fork-thread"}}
            if method == "thread/goal/get":
                return {"goal": {"objective": "Keep parity", "status": "active"}}
            if method == "thread/goal/set":
                return {"goal": {
                    "objective": params.get("objective"),
                    "status": params.get("status"),
                }}
            return {}

    fake = FakeHistoryClient()

    def fake_client(**kwargs):
        assert kwargs == {"user": "alice", "uid": "u1", "state_dir": "state", "codex_home": "home"}
        return fake

    assert codex_thread_history.history_action("", "archive", get_client_fn=fake_client) == {
        "ok": False, "error": "missing thread_id",
    }
    assert codex_thread_history.history_action(
        "thread-1", "fork", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client) == {
            "ok": True, "action": "fork", "thread_id": "fork-thread",
        }
    assert codex_thread_history.history_action(
        "thread-1", "archive", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client) == {
            "ok": True, "action": "archive", "thread_id": "thread-1",
        }
    assert codex_thread_history.history_action(
        "thread-1", "unarchive", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client) == {
            "ok": True, "action": "unarchive", "thread_id": "thread-1",
        }
    assert codex_thread_history.history_action(
        "thread-1", "rename", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client)["ok"] is False
    assert codex_thread_history.history_action(
        "thread-1", "rename", name="Better", user="alice", uid="u1",
        state_dir="state", codex_home="home", get_client_fn=fake_client) == {
            "ok": True, "action": "rename", "thread_id": "thread-1", "name": "Better",
        }
    assert codex_thread_history.history_action(
        "thread-1", "goal_get", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client)["goal"]["objective"] == "Keep parity"
    assert codex_thread_history.history_action(
        "thread-1", "goal_set", objective="Finish", status="paused", user="alice",
        uid="u1", state_dir="state", codex_home="home", get_client_fn=fake_client) == {
            "ok": True,
            "action": "goal_set",
            "thread_id": "thread-1",
            "goal": {"objective": "Finish", "status": "paused"},
        }
    assert codex_thread_history.history_action(
        "thread-1", "goal_set", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client)["ok"] is False
    assert codex_thread_history.history_action(
        "thread-1", "goal_clear", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client) == {
            "ok": True, "action": "goal_clear", "thread_id": "thread-1",
        }
    assert codex_thread_history.history_action(
        "thread-1", "bad", user="alice", uid="u1", state_dir="state",
        codex_home="home", get_client_fn=fake_client)["ok"] is False
    assert ("thread/name/set", {"threadId": "thread-1", "name": "Better"}, 30) in fake.calls
    assert ("thread/goal/clear", {"threadId": "thread-1"}, 30) in fake.calls

    print("codex history helper checks passed")


if __name__ == "__main__":
    main()
