"""Check extracted manager API helper modules."""
import sys
import urllib.parse
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import manager_internal_api  # noqa: E402
import manager_user_api  # noqa: E402


class FakeHandler:
    def __init__(self):
        self.headers = {"Host": "example.test"}
        self.calls = []
        self.status = 200
        self.body = None

    def _ctx(self, required=True):
        self.calls.append(("ctx", required))
        return {"user": "alice"} if required else None

    def _json(self, obj, code=200):
        self.status = code
        self.body = obj


class GateNative:
    def await_permission(self, tool_use_id, tool_name, input_obj):
        assert tool_use_id == "tu1"
        assert tool_name == "Edit"
        assert input_obj == {"x": 1}
        return True, ""

    def await_answer(self, tool_use_id, question, questions):
        assert tool_use_id == "ask1"
        assert question == "Ready?"
        assert questions == ["a"]
        return "yes"


class ReplayNative:
    def replay_payload(self, after_seq=0):
        return {"ok": True, "after_seq": after_seq}


class SendNative:
    def __init__(self):
        self._busy = False
        self._pending = {}
        self.plan_mode = False
        self.task_mode = False
        self.sent = []

    def send(self, prompt):
        self.sent.append(prompt)


def main():
    assert manager_internal_api.INTERNAL_GATE_POSTS == {"/api/_perm_gate", "/api/_ask_gate"}
    assert manager_internal_api.INTERNAL_CONTROL_POSTS == {"/api/_exit", "/api/_soft_exit"}

    h = FakeHandler()
    assert manager_internal_api.post_context(h, "/api/_ask_gate") is None
    assert h.calls[-1] == ("ctx", False)
    assert manager_internal_api.post_context(h, "/api/_exit") is None
    assert h.calls[-1] == ("ctx", False)
    assert manager_internal_api.post_context(h, "/api/launch") == {"user": "alice"}
    assert h.calls[-1] == ("ctx", True)

    sid, session, native = manager_internal_api.native_from_payload(
        {"sid": " s1 "}, {"user": "alice"}, lambda sid, _ctx: {"native": GateNative()} if sid == "s1" else None
    )
    assert sid == "s1"
    assert session and isinstance(native, GateNative)

    h = FakeHandler()
    assert manager_internal_api.handle_gate(
        h,
        "/api/_perm_gate",
        {"sid": "s1", "tool_use_id": "tu1", "tool_name": "Edit", "input": {"x": 1}},
        {"user": "alice"},
        lambda _data, _ctx: ("s1", {}, GateNative()),
    )
    assert h.body == {"behavior": "allow", "updatedInput": {"x": 1}}

    h = FakeHandler()
    assert manager_internal_api.handle_gate(
        h,
        "/api/_ask_gate",
        {"sid": "s1", "tool_use_id": "ask1", "question": "Ready?", "questions": ["a"]},
        {"user": "alice"},
        lambda _data, _ctx: ("s1", {}, GateNative()),
    )
    assert h.body == {"answer": "yes"}

    old_backends = common.BACKENDS
    old_path_allowed = common.path_allowed_for_user
    try:
        common.BACKENDS = {"codex_native": {"label": "Codex"}}
        common.path_allowed_for_user = lambda _user, _path: True

        h = FakeHandler()
        manager_user_api.handle_get(h, "/api/backends", urllib.parse.urlparse("/api/backends"), {"user": "alice"},
                                    lambda _sid, _ctx: None)
        assert h.body == {"backends": ["codex_native"], "labels": {"codex_native": "Codex"}}

        h = FakeHandler()
        manager_user_api.handle_get(
            h,
            "/api/nreplay",
            urllib.parse.urlparse("/api/nreplay?sid=s1&after=4"),
            {"user": "alice"},
            lambda sid, _ctx: {"native": ReplayNative()} if sid == "s1" else None,
        )
        assert h.body == {"ok": True, "after_seq": 4}

        native = SendNative()
        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nsend",
            {"sid": "s1", "prompt": "hello", "plan": True, "task": False},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True}
        assert native.sent == ["hello"]
        assert native.plan_mode is True
        assert native.task_mode is False
    finally:
        common.BACKENDS = old_backends
        common.path_allowed_for_user = old_path_allowed

    print("manager api helper checks passed")


if __name__ == "__main__":
    main()
