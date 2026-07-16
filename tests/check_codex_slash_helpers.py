"""Check Codex slash adapter delegation and state mutation behavior."""
import os
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_slash  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        if method == "thread/goal/get":
            return {"goal": {"objective": "Keep parity smooth", "status": "active"}}
        if method == "mcpServerStatus/list":
            return {"data": [{
                "name": "docs",
                "authStatus": "unsupported",
                "resources": [{"name": "Guide", "uri": "file://guide.md"}],
                "resourceTemplates": [],
                "tools": {"search": {"name": "search", "inputSchema": {}}},
            }]}
        if method == "skills/list":
            return {"data": [{"cwd": os.getcwd(), "skills": [{"name": "openai-docs", "enabled": True}]}]}
        if method == "plugin/installed":
            return {"marketplaces": [{"id": "local", "plugins": [{"id": "browser", "name": "Browser"}]}]}
        if method == "account/read":
            return {"requiresOpenaiAuth": False, "account": {"type": "chatgpt", "email": "u@example.com"}}
        if method == "account/rateLimits/read":
            return {"limit": 10}
        if method == "account/usage/read":
            return {"inputTokens": 1}
        return {}


class FakeSession:
    def __init__(self):
        self.sid = "s-slash"
        self.cwd = os.getcwd()
        self.cfg = {}
        self.model = ""
        self.yolo = False
        self.user = ""
        self.thread_id = "thread-1"
        self.last_turn_id = "turn-1"
        self._busy = False
        self._compact_in_progress = False
        self.current_turn_started_at = None
        self.synced = 0
        self.persisted = 0
        self.notices = []
        self.records = []
        self.client = FakeClient()

    def _client(self):
        return self.client

    def _sync_collaboration_mode(self):
        self.synced += 1

    def _record_and_broadcast(self, obj):
        self.records.append(obj)

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        self.notices.append((message, method, params, silent))

    def _persist(self):
        self.persisted += 1

    def _ensure_thread(self):
        if not self.thread_id:
            self.thread_id = "thread-1"

    def _thread_params(self):
        return {"cwd": self.cwd}

    def _replace_history_from_thread(self, thread):
        self.replaced_thread = thread

    def _user_input_items(self, prompt):
        return [{"type": "text", "text": prompt, "text_elements": []}]


def main():
    session = FakeSession()
    slash = codex_slash.CodexSlashAdapter(session)

    assert slash.handle_slash_command("not slash") == {"ok": False, "error": "not a slash command"}
    assert slash.handle_slash_command("/model gpt-test") == {
        "ok": True,
        "command": "model",
        "model": "gpt-test",
    }
    assert session.model == "gpt-test"
    assert session.cfg["model"] == "gpt-test"
    assert session.synced == 1
    assert session.persisted == 1

    assert slash.handle_slash_command("/compact") == {"ok": True, "command": "compact"}
    assert session._busy is True
    assert session._compact_in_progress is True
    assert session.current_turn_started_at is not None
    assert session.client.calls[-1] == ("thread/compact/start", {"threadId": "thread-1"}, 30)

    goal = slash.handle_slash_command("/goal get")
    assert goal["goal"]["objective"] == "Keep parity smooth"
    assert "Keep parity smooth" in session.notices[-1][0]

    steer = slash.handle_slash_command("/steer adjust course")
    assert steer == {"ok": True, "command": "steer"}
    assert session.client.calls[-1][0] == "turn/steer"
    assert session.client.calls[-1][1]["input"][0]["text"] == "adjust course"

    assert slash.handle_slash_command('/mcp-tool srv tool ["bad"]') == {
        "ok": False,
        "error": "json-args must be an object",
    }
    assert slash.handle_slash_command("/mcp-status tools") == {
        "ok": True,
        "command": "mcp-status",
        "detail": "toolsAndAuthOnly",
        "servers": 1,
        "next_cursor": None,
    }
    assert session.client.calls[-1][0] == "mcpServerStatus/list"
    assert slash.handle_slash_command("/mcp-resources docs") == {
        "ok": True,
        "command": "mcp-resources",
        "server": "docs",
        "resources": 1,
        "resource_templates": 0,
        "tools": 1,
    }
    assert slash.handle_slash_command("/skills") == {
        "ok": True,
        "command": "skills",
        "mode": "all",
        "skills": 1,
    }
    assert session.client.calls[-1][0] == "skills/list"
    assert slash.handle_slash_command("/plugins") == {
        "ok": True,
        "command": "plugins",
        "mode": "installed",
        "plugins": 1,
    }
    assert session.client.calls[-1][0] == "plugin/installed"
    account = slash.handle_slash_command("/account-status basic")
    assert account == {
        "ok": True,
        "command": "account-status",
        "mode": "basic",
        "signed_in": True,
        "errors": 0,
    }
    assert session.client.calls[-1][0] == "account/read"

    print("codex slash helper checks passed")


if __name__ == "__main__":
    main()
