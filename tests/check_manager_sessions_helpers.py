"""Check manager session lifecycle helpers after extraction."""
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import manager  # noqa: E402
import manager_sessions  # noqa: E402


class FakeNative:
    def __init__(self, alive=True, thread_id="thread-1", claude_sid=None):
        self.alive = alive
        self.thread_id = thread_id
        self.claude_sid = claude_sid
        self.convo_title = "Native title"
        self.yolo = True
        self.last_activity = 123
        self._busy = self.alive
        self.current_turn_started_at = 99.0
        self._awaiting_plan_decision = False
        self.closed = False

    def state(self):
        return "running" if self.alive else "closed"

    def close(self):
        self.closed = True
        self.alive = False


def _session(user, state_dir, native=None, started=1):
    return {
        "dir": state_dir,
        "backend": "codex_native",
        "provider": "codex",
        "title": "Stored title",
        "started": started,
        "mode": "new",
        "session_id": "stored",
        "thread_id": getattr(native, "thread_id", None) if native else None,
        "user": user,
        "state_dir": state_dir,
        "native": native,
    }


def main():
    old_sessions = dict(manager_sessions.sessions)
    old_sid = manager_sessions.sid_counter[0]
    old_backends = common.BACKENDS
    old_codex_session = manager_sessions.CodexSession
    try:
        with tempfile.TemporaryDirectory() as td:
            manager_sessions.sessions.clear()
            manager_sessions.sid_counter[0] = 0

            Path(td, "codex_s7.json").write_text("{}", encoding="utf-8")
            Path(td, "native_s3.json").write_text("{}", encoding="utf-8")
            assert manager_sessions.sid_num("s12") == 12
            assert manager_sessions.sid_num("bad") == 0
            assert manager_sessions.state_sid_taken("s7", td)
            manager_sessions.seed_sid_from_state_dir(td)
            assert manager_sessions.sid_counter[0] == 7

            assert manager_sessions.session_title(td, "") == os.path.basename(td)
            common.BACKENDS = {"codex_native": {"label": "Codex"}}
            assert manager_sessions.backend_available("codex")
            assert not manager_sessions.backend_available("claude")

            alice_native = FakeNative(thread_id="thread-alice")
            bob_native = FakeNative(thread_id="thread-bob")
            manager_sessions.sessions["s1"] = _session("alice", td, alice_native, started=2)
            manager_sessions.sessions["s2"] = _session("bob", td, bob_native, started=1)

            assert manager.sessions is manager_sessions.sessions
            assert manager._sid_num("s7") == 7
            assert manager._state_sid_taken("s7", td)

            ctx = {"user": "alice"}
            assert manager_sessions.owned_session("s1", ctx)["user"] == "alice"
            assert manager_sessions.owned_session("s2", ctx) is None
            items = manager_sessions.session_items_for_user("alice")
            assert len(items) == 1
            assert items[0]["sid"] == "s1"
            assert items[0]["title"] == "Native title"
            assert manager_sessions.owned_sids("alice") == ["s1"]
            assert manager_sessions.history_belongs_to_other_user("thread-bob", "alice")
            assert not manager_sessions.history_belongs_to_other_user("thread-alice", "alice")

            manager_sessions.persist_sessions()
            registry = common.registry_load(state_dir=td)
            assert set(registry["sessions"]) == {"s1", "s2"}
            assert registry["sessions"]["s1"]["state"] == "running"
            assert registry["sessions"]["s1"]["busy"] is True
            assert registry["sessions"]["s1"]["current_turn_started_at"] == 99.0

            recovered_native = FakeNative(thread_id="thread-recovered")
            recovered_native._busy = False
            recovered_native.current_turn_started_at = None
            recovered_native._awaiting_plan_decision = False

            class RecoverableCodex:
                @classmethod
                def recover(cls, *_args, **_kwargs):
                    return recovered_native

            manager_sessions.CodexSession = RecoverableCodex
            manager_sessions.reattach_one(
                {"user": "alice", "uid": "u1", "state_dir": td},
                "s9",
                {"dir": td, "backend": "codex_native", "provider": "codex",
                 "title": "Recovered", "state": "running", "busy": True,
                 "current_turn_started_at": 88.5,
                 "awaiting_plan_decision": True, "thread_id": "thread-recovered",
                 "state_dir": td},
            )
            assert recovered_native._busy is True
            assert recovered_native.current_turn_started_at == 88.5
            assert recovered_native._awaiting_plan_decision is True
            assert manager_sessions.sessions["s9"]["native"] is recovered_native

            manager_sessions.sessions["dead"] = _session("alice", td, FakeNative(alive=False), started=3)
            manager_sessions.prune_dead()
            assert "dead" not in manager_sessions.sessions

            assert manager_sessions.kill_session("s1") is True
            assert alice_native.closed is True
            assert "s1" not in manager_sessions.sessions
            assert manager_sessions.kill_session("missing") is False
    finally:
        manager_sessions.sessions.clear()
        manager_sessions.sessions.update(old_sessions)
        manager_sessions.sid_counter[0] = old_sid
        common.BACKENDS = old_backends
        manager_sessions.CodexSession = old_codex_session

    print("manager session helper checks passed")


if __name__ == "__main__":
    main()
