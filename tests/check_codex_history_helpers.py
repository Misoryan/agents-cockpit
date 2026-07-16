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

    print("codex history helper checks passed")


if __name__ == "__main__":
    main()
