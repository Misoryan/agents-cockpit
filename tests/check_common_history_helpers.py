"""Check history helpers after extracting them from common.py."""
import json
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_history  # noqa: E402


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as td:
        claude_home = Path(td, "claude")
        project = claude_home / "projects" / "proj-a"
        session_path = project / "abc.jsonl"
        _write_jsonl(session_path, [
            {"type": "user", "cwd": str(Path(td, "repo")), "timestamp": "2026-01-02T03:04:05Z",
             "message": {"content": [{"type": "text", "text": "first prompt"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "skip"}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "second prompt"}]}},
            {"type": "summary", "summary": "Short title"},
        ])
        _write_jsonl(claude_home / "projects" / "subagents" / "ignored.jsonl", [
            {"type": "user", "cwd": "bad", "message": {"content": "bad"}},
        ])

        settings = common_history.HistorySettings(
            claude_home=str(claude_home),
            claude_scan_cap=100,
            codex_enabled=False,
        )
        assert common_history.iso_to_epoch("bad") == 0
        assert common_history.claude_user_text({"message": {"content": "hello"}}) == "hello"
        assert common_history.transcript_is_human_turn({"message": {"content": "hello"}})
        assert not common_history.transcript_is_human_turn(
            {"message": {"content": [{"type": "tool_result", "content": "x"}]}}
        )

        history = common_history.load_claude_history(settings)
        assert len(history) == 1
        assert history[0]["session_id"] == "abc"
        assert history[0]["title"] == "Short title"
        assert history[0]["backend"] == "claude_native"

        events = common_history.load_claude_transcript_events("abc", settings)
        assert [ev["type"] for ev in events] == ["user", "assistant", "user", "result", "user", "result"]
        assert common_history.load_history(settings)[0]["session_id"] == "abc"

        codex_settings = common_history.HistorySettings(
            claude_home=str(claude_home),
            claude_scan_cap=100,
            codex_enabled=True,
        )
        mixed = common_history.load_history(
            codex_settings, limit=5,
            list_thread_history_fn=lambda **_kw: [
                {"session_id": "thread", "cwd": "codex", "ts": 9999999999, "title": "Codex", "backend": "codex_native"}
            ],
        )
        assert mixed[0]["session_id"] == "thread"

        recent = common_history.recent_dirs(
            settings, limit=2,
            load_history_fn=lambda _settings, _limit, ctx=None: [
                {"cwd": "a", "ts": 1}, {"cwd": "a", "ts": 3}, {"cwd": "b", "ts": 2}
            ],
        )
        assert recent[0] == {"cwd": "a", "count": 2, "last_ts": 3}

        deleted = common_history.delete_history("abc", settings)
        assert deleted["deleted"] is True
        assert not session_path.exists()
        codex_deleted = common_history.delete_history(
            "thread", codex_settings, backend="codex_native",
            is_codex_backend_fn=lambda backend: backend == "codex_native",
            delete_thread_fn=lambda thread_id, **_kw: thread_id == "thread",
        )
        assert codex_deleted == {"deleted": True, "session_file": "thread"}

        old_home = common.CLAUDE_HOME
        old_bin = common.CODEX_BIN
        try:
            common.CLAUDE_HOME = str(claude_home)
            common.CODEX_BIN = None
            _write_jsonl(session_path, [
                {"type": "user", "cwd": str(Path(td, "repo")), "timestamp": "2026-01-02T03:04:05Z",
                 "message": {"content": "wrapper prompt"}},
            ])
            assert common.load_history(10)[0]["session_id"] == "abc"
            assert common.load_claude_transcript_events("abc")[-1]["type"] == "result"
        finally:
            common.CLAUDE_HOME = old_home
            common.CODEX_BIN = old_bin

    print("common history helper checks passed")


if __name__ == "__main__":
    main()
