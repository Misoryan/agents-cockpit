"""Check /api/nsend refuses overlapping turns on the same session."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import manager  # noqa: E402


class FakeNative:
    def __init__(self, busy=False, pending=False):
        self._busy = busy
        self._pending = {"gate": object()} if pending else {}
        self.plan_mode = False
        self.task_mode = False
        self.sent = []

    def send(self, prompt):
        self.sent.append(prompt)


class FakeHandler:
    _auth = manager.ManagerHandler._auth
    _ctx = manager.ManagerHandler._ctx
    _owned_session = manager.ManagerHandler._owned_session
    _post_context = manager.ManagerHandler._post_context
    _native_from_payload = manager.ManagerHandler._native_from_payload
    _handle_internal_gate = manager.ManagerHandler._handle_internal_gate
    _handle_internal_control = manager.ManagerHandler._handle_internal_control
    _handle_user_post = manager.ManagerHandler._handle_user_post
    _json = common.BaseHandler._json

    def __init__(self, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.path = "/api/nsend"
        self.headers = {
            "Authorization": common.EXPECTED_AUTH,
            "X-Agent-Cockpit-User": "alice",
            "Content-Length": str(len(raw)),
        }
        self.client_address = ("127.0.0.1", 12345)
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.status = None
        self.out_headers = []

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.out_headers.append((key, value))

    def end_headers(self):
        return None

    def json_body(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def _call_send(ns):
    manager.sessions["s1"] = {"user": "alice", "native": ns}
    h = FakeHandler({"sid": "s1", "prompt": "hello", "plan": True, "task": False})
    manager.ManagerHandler.do_POST(h)
    return h


def main():
    old_users = common.USERS
    old_user_data_dir = common.USER_DATA_DIR
    old_default_root = common.DEFAULT_WORKSPACE_ROOT
    old_sessions = dict(manager.sessions)
    try:
        with tempfile.TemporaryDirectory() as td:
            common.USERS = {"alice": "pw"}
            common.USER_DATA_DIR = os.path.join(td, "users")
            common.DEFAULT_WORKSPACE_ROOT = os.path.join(td, "users", "{uid}", "workspace")
            manager.sessions.clear()

            busy = FakeNative(busy=True)
            h = _call_send(busy)
            assert h.status == 409
            assert h.json_body()["error"] == "session is busy"
            assert busy.sent == []

            pending = FakeNative(pending=True)
            h = _call_send(pending)
            assert h.status == 409
            assert h.json_body()["error"] == "session is busy"
            assert pending.sent == []

            idle = FakeNative()
            h = _call_send(idle)
            assert h.status == 200
            assert h.json_body()["ok"] is True
            assert idle.sent == ["hello"]
            assert idle.plan_mode is True
            assert idle.task_mode is False
    finally:
        common.USERS = old_users
        common.USER_DATA_DIR = old_user_data_dir
        common.DEFAULT_WORKSPACE_ROOT = old_default_root
        manager.sessions.clear()
        manager.sessions.update(old_sessions)

    print("busy guard checks passed")


if __name__ == "__main__":
    main()
