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
        self.prepared_images = []
        self.slash = []

    def send(self, prompt, image_inputs=None):
        self.sent.append((prompt, image_inputs or []))

    def prepare_image_inputs(self, images):
        self.prepared_images.append(images)
        return [{"type": "localImage", "path": "image.png", "name": "image.png"}] if images else []

    def handle_slash_command(self, command):
        self.slash.append(command)
        if command.startswith("/steer"):
            return {"ok": True, "command": "steer"}
        return {"ok": True, "command": "model", "model": "gpt-5-codex"}

    def search_files(self, query, limit=20):
        return {"ok": True, "files": [{"insert": query + ".py", "name": query + ".py", "limit": limit}]}

    def terminal_write(self, process_id, text="", close_stdin=False):
        return {"ok": True, "process_id": process_id, "input": text, "closed": bool(close_stdin)}

    def terminal_terminate(self, process_id):
        return {"ok": True, "process_id": process_id, "terminated": True}

    def terminal_resize(self, process_id, cols, rows):
        return {"ok": True, "process_id": process_id, "cols": int(cols), "rows": int(rows)}


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
    old_load_history = common.load_history
    old_codex_session = manager_user_api.CodexSession
    try:
        common.BACKENDS = {"codex_native": {"label": "Codex"}}
        common.path_allowed_for_user = lambda _user, _path: True

        class FakeCodexSession:
            @staticmethod
            def launch_options(cwd="", user="", uid="", state_dir=None, codex_home=None):
                assert cwd == "C:/repo"
                assert user == "alice"
                assert uid == "u1"
                assert state_dir == "state"
                assert codex_home == "home"
                return {"models": [{"id": "gpt-5-codex"}], "error": ""}

            @staticmethod
            def history_action(thread_id, action, name="", objective="", status="",
                               user="", uid="", state_dir=None, codex_home=None):
                assert thread_id == "thread-1"
                assert user == "alice"
                assert uid == "u1"
                assert state_dir == "state"
                assert codex_home == "home"
                if action == "rename":
                    assert name == "Better"
                    return {"ok": True, "action": "rename", "thread_id": thread_id, "name": name}
                if action == "goal_set":
                    assert objective == "Finish parity"
                    return {"ok": True, "action": "goal_set", "thread_id": thread_id,
                            "goal": {"objective": objective, "status": status or "active"}}
                if action == "unarchive":
                    return {"ok": True, "action": "unarchive", "thread_id": thread_id}
                assert action == "fork"
                return {"ok": True, "action": "fork", "thread_id": "thread-fork"}

        manager_user_api.CodexSession = FakeCodexSession

        h = FakeHandler()
        manager_user_api.handle_get(h, "/api/backends", urllib.parse.urlparse("/api/backends"), {"user": "alice"},
                                    lambda _sid, _ctx: None)
        assert h.body == {"backends": ["codex_native"], "labels": {"codex_native": "Codex"}}

        h = FakeHandler()
        manager_user_api.handle_get(
            h,
            "/api/codex_options",
            urllib.parse.urlparse("/api/codex_options?dir=C%3A%2Frepo"),
            {"user": "alice", "uid": "u1", "state_dir": "state", "codex_home": "home"},
            lambda _sid, _ctx: None,
        )
        assert h.body["models"][0]["id"] == "gpt-5-codex"

        hist_kwargs = {}
        common.load_history = lambda limit, ctx=None, live_codex=False, archived=False: (
            hist_kwargs.update({"limit": limit, "ctx": ctx, "live_codex": live_codex,
                                "archived": archived}) or [
                {"session_id": "archived-thread", "cwd": "C:/repo", "title": "Archived",
                 "backend": "codex_native", "archived": True}
            ]
        )
        h = FakeHandler()
        manager_user_api.handle_get(
            h,
            "/api/history",
            urllib.parse.urlparse("/api/history?limit=7&live_codex=1&archived=1"),
            {"user": "alice"},
            lambda _sid, _ctx: None,
        )
        assert h.body["history"][0]["session_id"] == "archived-thread"
        assert hist_kwargs["limit"] == 21
        assert hist_kwargs["live_codex"] is True
        assert hist_kwargs["archived"] is True

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
        manager_user_api.handle_get(
            h,
            "/api/nfiles",
            urllib.parse.urlparse("/api/nfiles?sid=s1&q=codex&limit=7"),
            {"user": "alice"},
            lambda sid, _ctx: {"native": native} if sid == "s1" else None,
        )
        assert h.body == {"ok": True, "files": [{"insert": "codex.py", "name": "codex.py", "limit": 7}]}

        native = SendNative()
        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nterminal",
            {"sid": "s1", "process_id": "p1", "action": "write", "input": "hello", "close": True},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "process_id": "p1", "input": "hello", "closed": True}

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nterminal",
            {"sid": "s1", "process_id": "p1", "action": "resize", "cols": 90, "rows": 20},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "process_id": "p1", "cols": 90, "rows": 20}

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
        assert native.sent == [("hello", [])]
        assert native.plan_mode is True
        assert native.task_mode is False

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nsend",
            {"sid": "s1", "prompt": "", "images": [{"name": "shot.png", "data_url": "data:image/png;base64,aGVsbG8="}]},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True}
        assert native.sent[-1][0] == ""
        assert native.sent[-1][1][0]["path"] == "image.png"

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nslash",
            {"sid": "s1", "command": "/model gpt-5-codex"},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "command": "model", "model": "gpt-5-codex"}
        assert native.slash == ["/model gpt-5-codex"]

        native._busy = True
        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nslash",
            {"sid": "s1", "command": "/model other"},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.status == 409
        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/nslash",
            {"sid": "s1", "command": "/steer keep going"},
            {"user": "alice"},
            lambda _data, _ctx: ("s1", {"native": native}, native),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "command": "steer"}
        native._busy = False

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/codex_history_action",
            {"thread_id": "thread-1", "backend": "codex_native", "action": "fork"},
            {"user": "alice", "uid": "u1", "state_dir": "state", "codex_home": "home"},
            lambda _data, _ctx: ("", None, None),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "action": "fork", "thread_id": "thread-fork"}

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/codex_history_action",
            {"thread_id": "thread-1", "backend": "codex_native", "action": "rename", "name": "Better"},
            {"user": "alice", "uid": "u1", "state_dir": "state", "codex_home": "home"},
            lambda _data, _ctx: ("", None, None),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "action": "rename", "thread_id": "thread-1", "name": "Better"}

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/codex_history_action",
            {"thread_id": "thread-1", "backend": "codex_native", "action": "goal_set", "objective": "Finish parity"},
            {"user": "alice", "uid": "u1", "state_dir": "state", "codex_home": "home"},
            lambda _data, _ctx: ("", None, None),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body["goal"]["objective"] == "Finish parity"

        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/codex_history_action",
            {"thread_id": "thread-1", "backend": "codex_native", "action": "unarchive"},
            {"user": "alice", "uid": "u1", "state_dir": "state", "codex_home": "home"},
            lambda _data, _ctx: ("", None, None),
            lambda _sid, _ctx: None,
            lambda *_args, **_kwargs: "unused",
            lambda _sid: True,
        )
        assert h.body == {"ok": True, "action": "unarchive", "thread_id": "thread-1"}

        captured = {}
        launch_dir = str(Path(__file__).resolve().parents[1])
        h = FakeHandler()
        manager_user_api.handle_post(
            h,
            "/api/launch",
            {"dir": launch_dir, "backend": "codex_native", "codex": {
                "model": "gpt-5-codex",
                "approvalPolicy": "on-request",
                "sandbox": "workspace-write",
                "webSearch": "live",
            }},
            {"user": "alice"},
            lambda _data, _ctx: ("", None, None),
            lambda _sid, _ctx: None,
            lambda *args, **kwargs: captured.update(kwargs) or "s42",
            lambda _sid: True,
        )
        assert h.body["sid"] == "s42"
        assert captured["codex_config"] == {
            "model": "gpt-5-codex",
            "approval_policy": "on-request",
            "sandbox": "workspace-write",
            "web_search": "live",
        }
    finally:
        common.BACKENDS = old_backends
        common.path_allowed_for_user = old_path_allowed
        common.load_history = old_load_history
        manager_user_api.CodexSession = old_codex_session

    print("manager api helper checks passed")


if __name__ == "__main__":
    main()
