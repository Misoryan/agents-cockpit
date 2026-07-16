"""Check browser-facing Codex command/exec helper behavior."""
import os
import sys
import threading
import time
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_command_exec  # noqa: E402


class FakeClient:
    def __init__(self, session):
        self.session = session
        self.calls = []

    def request(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        assert method == "command/exec"
        assert self.session._busy is True
        assert params["cwd"] == os.path.abspath(self.session.cwd)
        return {"exitCode": 0, "stdout": "hello\n", "stderr": "warn\n"}


class FakeStreamClient:
    def __init__(self):
        self.handlers = {}
        self.calls = []

    def ensure(self):
        self.calls.append(("ensure", {}, None))

    def add_command_exec_output_handler(self, process_id, handler):
        self.handlers[process_id] = handler
        return True

    def remove_command_exec_output_handler(self, process_id, handler=None):
        if handler is None or self.handlers.get(process_id) is handler:
            self.handlers.pop(process_id, None)

    def request(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        if method == "command/exec":
            handler = self.handlers[params["processId"]]
            handler({"processId": params["processId"], "stream": "stdout", "deltaBase64": "cmVhZHkK"})
            handler({"processId": params["processId"], "stream": "stderr", "deltaBase64": "d2Fybg=="})
            return {"exitCode": 0, "stdout": "", "stderr": ""}
        return {}


class FakeSession:
    def __init__(self):
        self.sid = "cmd-exec-session"
        self.cwd = os.getcwd()
        self.cfg = {"sandbox": "read-only", "approval_policy": "on-request"}
        self.yolo = False
        self._busy = False
        self.current_turn_started_at = None
        self.records = []
        self.broadcasts = []
        self.notices = []
        self.persisted = 0
        self._pending_lock = threading.Lock()
        self._terminal_processes = {}
        self.client = FakeClient(self)

    def _client(self):
        return self.client

    def _record_and_broadcast(self, obj):
        self.records.append(obj)

    def _broadcast(self, obj):
        self.broadcasts.append(obj)

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        self.notices.append((message, method, params, level, silent))

    def _persist(self):
        self.persisted += 1


def main():
    tool_name, argv = codex_command_exec.shell_command_argv("echo hello")
    assert tool_name in ("powershell", "bash")
    assert "echo hello" in argv[-1]
    assert "truncated" in codex_command_exec._clip_text("x" * (codex_command_exec.MAX_CAPTURE_CHARS + 20))

    session = FakeSession()
    result = codex_command_exec.run_command_exec(session, "echo hello")
    assert result["ok"] is True
    assert result["command"] == "exec"
    assert result["exit_code"] == 0
    assert session._busy is False
    assert session.current_turn_started_at is None
    assert session.persisted == 1
    assert session.client.calls[0][0] == "command/exec"
    params = session.client.calls[0][1]
    assert params["sandboxPolicy"] == {"type": "readOnly"}
    assert params["approvalPolicy"] == "on-request"
    assert session.records[0]["message"]["content"][0]["type"] == "tool_use"
    assert session.records[0]["message"]["content"][0]["name"] == tool_name
    block = session.records[1]["message"]["content"][0]
    assert block["type"] == "tool_result"
    assert block["stdout"] == "hello\n"
    assert block["stderr"] == "warn\n"
    assert session.records[2]["type"] == "result"
    assert session.notices[-1][1] == "command/exec"
    assert session.notices[-1][4] is True

    stream = FakeSession()
    stream.client = FakeStreamClient()
    streamed = codex_command_exec.run_stream_command_exec(stream, "echo ready")
    assert streamed["ok"] is True
    assert streamed["command"] == "exec-stream"
    deadline = time.time() + 3
    while time.time() < deadline and not stream.notices:
        time.sleep(0.05)
    assert stream.notices, "stream worker did not finish"
    assert stream.client.calls[0][0] == "ensure"
    exec_call = [call for call in stream.client.calls if call[0] == "command/exec"][0]
    assert exec_call[1]["streamStdoutStderr"] is True
    assert exec_call[1]["streamStdin"] is True
    assert not stream.client.handlers
    assert any(obj.get("type") == "terminal_interaction" for obj in stream.broadcasts)
    assert any(obj.get("type") == "terminal_closed" for obj in stream.broadcasts)
    assert any(
        (((obj.get("message") or {}).get("content") or [{}])[0].get("stdout") or "").startswith("ready")
        for obj in stream.broadcasts + stream.records
        if obj.get("type") == "user"
    )
    assert stream.records[-1]["type"] == "result"

    yolo = FakeSession()
    yolo.yolo = True
    _, yolo_params = codex_command_exec.build_exec_params(yolo, "echo yolo")
    assert yolo_params["sandboxPolicy"] == {"type": "dangerFullAccess"}
    assert yolo_params["approvalPolicy"] == "never"

    print("codex command exec helper checks passed")


if __name__ == "__main__":
    main()
