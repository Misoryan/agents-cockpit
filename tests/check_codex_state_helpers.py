"""Check Codex session state persistence helpers."""
import json
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_state  # noqa: E402
from codex_native import CodexSession  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        session = CodexSession("s-state", td, yolo=True, cfg={"model": "gpt-test"}, state_dir=td)
        session.thread_id = "thread-1"
        session.last_turn_id = "turn-1"
        session.model = "gpt-test"
        session.model_provider = "openai"
        session.service_tier = "auto"
        session._busy = True
        session.current_turn_started_at = 123.5
        session._awaiting_plan_decision = True
        session.events = [{"type": "assistant", "seq": 1}]
        session.timeline = [{"type": "assistant", "seq": 1}, {"type": "result", "seq": 2}]
        session._next_seq = 3

        assert session._state_path() == os.path.join(td, "codex_s-state.json")
        assert session._persist() is True
        data = json.loads(Path(session._state_path()).read_text(encoding="utf-8"))
        assert data["thread_id"] == "thread-1"
        assert data["last_turn_id"] == "turn-1"
        assert data["model_provider"] == "openai"
        assert data["busy"] is True
        assert data["current_turn_started_at"] == 123.5
        assert data["awaiting_plan_decision"] is True
        assert [event["seq"] for event in data["timeline"]] == [1, 2]

        loaded = codex_state.load_state_data(td, "s-state")
        recovered = CodexSession("s-recovered", td, state_dir=td)
        codex_state.CodexSessionState(recovered, 400).apply_recovered(
            loaded,
            expected_thread_id="thread-override",
            drop_noise_fn=lambda events: [
                event for event in events
                if "Codex app-server exited" not in str(event.get("error") or "")
            ],
        )
        assert recovered.thread_id == "thread-override"
        assert recovered.last_turn_id == "turn-1"
        assert recovered.model == "gpt-test"
        assert recovered._busy is True
        assert recovered.current_turn_started_at == 123.5
        assert recovered._awaiting_plan_decision is True
        assert recovered._next_seq == 3

        Path(td, "codex_s-local.json").write_text(json.dumps({
            "thread_id": "thread-local",
            "cwd": td,
            "events": [{"type": "result", "error": "Codex app-server exited. restart"}],
            "timeline": [{"type": "assistant", "seq": 7}],
            "next_seq": 8,
        }), encoding="utf-8")

        class Recoverable(CodexSession):
            registered = []

            def _client(self):
                class Client:
                    def register(_self, thread_id, session_obj):
                        Recoverable.registered.append((thread_id, session_obj.sid))
                return Client()

        restored = codex_state.recover_session(
            Recoverable, "s-local", td, default_state_dir=td, replay_max_events=400,
            drop_noise_fn=CodexSession._drop_recover_noise)
        assert restored is not None
        assert restored.thread_id == "thread-local"
        assert restored._next_seq == 8
        assert Recoverable.registered == [("thread-local", "s-local")]

    print("codex state helper checks passed")


if __name__ == "__main__":
    main()
