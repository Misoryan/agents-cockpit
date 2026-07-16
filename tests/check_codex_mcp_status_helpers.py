"""Check Codex MCP status helper formatting and slash calls."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_mcp_status  # noqa: E402


SAMPLE_RESPONSE = {
    "data": [
        {
            "name": "docs",
            "authStatus": "unsupported",
            "resources": [
                {"name": "Guide", "uri": "file://guide.md", "mimeType": "text/markdown"},
            ],
            "resourceTemplates": [
                {"name": "Issue", "uriTemplate": "issue://{id}"},
            ],
            "tools": {
                "search": {
                    "name": "search",
                    "description": "Search docs",
                    "inputSchema": {"type": "object"},
                },
            },
            "serverInfo": {"name": "docs", "version": "1.0.0"},
        },
        {
            "name": "private",
            "authStatus": "notLoggedIn",
            "resources": [],
            "resourceTemplates": [],
            "tools": {},
        },
    ],
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, params, timeout=0):
        self.calls.append((method, params, timeout))
        assert method == "mcpServerStatus/list"
        return SAMPLE_RESPONSE


class FakeSession:
    def __init__(self):
        self.thread_id = "thread-1"
        self.client = FakeClient()
        self.notices = []

    def _client(self):
        return self.client

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        self.notices.append((message, method, params, level, silent))


def main():
    assert codex_mcp_status.normalize_detail("") == "full"
    assert codex_mcp_status.normalize_detail("tools") == "toolsAndAuthOnly"
    assert codex_mcp_status.normalize_detail("bad") is None

    summary = codex_mcp_status.server_summary(SAMPLE_RESPONSE["data"][0], include_items=True)
    assert summary["name"] == "docs"
    assert summary["tools"] == 1
    assert summary["resourceList"][0]["uri"] == "file://guide.md"
    assert "private" in codex_mcp_status.status_notice_message(SAMPLE_RESPONSE)
    assert "login required" in codex_mcp_status.status_notice_message(SAMPLE_RESPONSE)

    session = FakeSession()
    assert codex_mcp_status.list_mcp_status(session, "tools") == {
        "ok": True,
        "command": "mcp-status",
        "detail": "toolsAndAuthOnly",
        "servers": 2,
        "next_cursor": None,
    }
    assert session.client.calls[-1][1] == {
        "threadId": "thread-1",
        "limit": 50,
        "detail": "toolsAndAuthOnly",
    }
    assert session.notices[-1][1] == "mcpServerStatus/list"

    assert codex_mcp_status.list_mcp_resources(session, "docs") == {
        "ok": True,
        "command": "mcp-resources",
        "server": "docs",
        "resources": 1,
        "resource_templates": 1,
        "tools": 1,
    }
    assert session.notices[-1][2]["resources"][0]["uri"] == "file://guide.md"
    assert codex_mcp_status.list_mcp_resources(session, "missing")["ok"] is False

    assert codex_mcp_status.startup_status_message(
        {"name": "docs", "status": "failed", "error": "boom"}
    ) == "MCP docs: failed (boom)"
    assert "completed" in codex_mcp_status.oauth_login_message({"name": "docs", "success": True})
    assert "failed" in codex_mcp_status.oauth_login_message({"name": "docs", "success": False})

    print("codex MCP status helper checks passed")


if __name__ == "__main__":
    main()
