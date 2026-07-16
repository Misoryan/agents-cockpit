"""Check read-only Codex skills/plugin inventory helpers."""
import os
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_inventory  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []

    def request(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        if method == "skills/list":
            return {
                "data": [{
                    "cwd": os.getcwd(),
                    "skills": [
                        {
                            "name": "openai-docs",
                            "description": "Use docs.",
                            "scope": "system",
                            "enabled": True,
                            "path": r"C:\secret\SKILL.md",
                            "interface": {"displayName": "OpenAI Docs", "shortDescription": "Docs helper"},
                        },
                        {"name": "disabled-skill", "scope": "user", "enabled": False},
                    ],
                }],
            }
        if method == "plugin/installed":
            return {
                "marketplaces": [{
                    "id": "local",
                    "name": "Local",
                    "plugins": [{
                        "id": "browser",
                        "name": "Browser",
                        "description": "Browser plugin",
                        "version": "1.0",
                        "installed": True,
                        "enabled": True,
                        "path": r"C:\secret\plugin",
                    }],
                }],
                "marketplaceLoadErrors": [],
            }
        if method == "plugin/list":
            return {
                "marketplaces": [{"id": "market", "items": [{"id": "new", "title": "New Plugin"}]}],
                "featuredPluginIds": ["new"],
            }
        return {}


class FakeSession:
    def __init__(self):
        self.cwd = os.getcwd()
        self.client = FakeClient()
        self.results = []
        self.notices = []

    def _client(self):
        return self.client

    def _mcp_result_events(self, call_id, name, input_obj, result, method):
        self.results.append((call_id, name, input_obj, result, method))

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        self.notices.append((message, method, params, silent))


def main():
    session = FakeSession()
    skills = codex_inventory.list_skills(session, "")
    assert skills == {"ok": True, "command": "skills", "mode": "all", "skills": 2}
    assert session.client.calls[-1][0] == "skills/list"
    payload = session.results[-1][3]
    assert payload["enabled"] == 1 and payload["disabled"] == 1
    assert payload["roots"][0]["skills"][0]["displayName"] == "OpenAI Docs"
    assert "path" not in payload["roots"][0]["skills"][0]
    assert session.results[-1][1] == "codex.skills"
    assert session.results[-1][4] == "skills/list"

    enabled = codex_inventory.list_skills(session, "enabled")
    assert enabled["skills"] == 1
    assert codex_inventory.list_skills(session, "bad")["ok"] is False

    plugins = codex_inventory.list_plugins(session, "")
    assert plugins == {"ok": True, "command": "plugins", "mode": "installed", "plugins": 1}
    assert session.client.calls[-1][0] == "plugin/installed"
    plugin_payload = session.results[-1][3]
    assert plugin_payload["marketplaces"][0]["plugins"][0]["name"] == "Browser"
    assert "path" not in plugin_payload["marketplaces"][0]["plugins"][0]
    assert session.results[-1][1] == "codex.plugins"

    available = codex_inventory.list_plugins(session, "available")
    assert available["mode"] == "available"
    assert session.client.calls[-1][0] == "plugin/list"
    assert codex_inventory.list_plugins(session, "bad")["ok"] is False

    print("codex inventory helper checks passed")


if __name__ == "__main__":
    main()
