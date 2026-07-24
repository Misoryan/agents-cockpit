"""Check extracted Codex turn/thread lifecycle helpers."""
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_turn  # noqa: E402
from codex_native import CodexSession  # noqa: E402


class FakeClient:
    def __init__(self, fail_turn=False):
        self.fail_turn = fail_turn
        self.calls = []

    def ensure(self):
        self.calls.append(("ensure",))

    def register(self, thread_id, session):
        self.calls.append(("register", thread_id, session.sid))

    def register_turn(self, turn_id, session):
        self.calls.append(("register_turn", turn_id, session.sid))

    def request(self, method, params, timeout=0):
        self.calls.append((method, params, timeout))
        if method == "thread/resume":
            return {
                "thread": {"id": params.get("threadId"), "cliVersion": "0.test"},
                "model": "gpt-test",
                "modelProvider": "openai",
                "serviceTier": "auto",
            }
        if method == "thread/settings/update":
            return {}
        if method == "turn/start":
            if self.fail_turn:
                raise RuntimeError("boom")
            return {"turn": {"id": "turn-1"}}
        return {}


def main():
    with tempfile.TemporaryDirectory() as td:
        session = CodexSession("s-turn", td, cfg={
            "model": "gpt-5-codex",
            "approval_policy": "on-request",
            "sandbox": "workspace-write",
            "reasoning_effort": "medium",
            "reasoning_summary": "concise",
        }, state_dir=td)
        fake = FakeClient()
        session._client = lambda: fake
        session.thread_id = "thread-1"
        session.task_mode = True

        thread_params = session._thread_params()
        assert thread_params["model"] == "gpt-5-codex"
        assert thread_params["approvalPolicy"] == "on-request"
        assert thread_params["sandbox"] == "workspace-write"

        turn_params = session._turn_params("hello")
        assert turn_params["input"][0]["text"].startswith(codex_turn.TASK_SYSTEM)
        assert turn_params["collaborationMode"]["settings"]["reasoning_effort"] == "medium"
        assert "request_user_input" in turn_params["collaborationMode"]["settings"]["developer_instructions"]
        assert turn_params["effort"] == "medium"
        assert turn_params["summary"] == "concise"

        session._ensure_thread()
        assert session._thread_ready is True
        assert session.model == "gpt-test"
        assert ("register", "thread-1", "s-turn") in fake.calls
        assert any(call[0] == "thread/resume" for call in fake.calls)

        session._run_turn("hello")
        assert session._busy is True
        assert session.last_turn_id == "turn-1"
        assert ("register_turn", "turn-1", "s-turn") in fake.calls

        failing = CodexSession("s-fail", td, state_dir=td)
        failing.thread_id = "thread-fail"
        failing._thread_ready = True
        failing._client = lambda: FakeClient(fail_turn=True)
        failing._run_turn("hello")
        assert failing._busy is False
        assert failing.current_turn_started_at is None
        assert failing.timeline[-1]["type"] == "result"
        assert "Codex turn failed: boom" in failing.timeline[-1]["error"]

    print("codex turn helper checks passed")


if __name__ == "__main__":
    main()
