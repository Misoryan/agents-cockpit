"""Check Codex app-server protocol matrix helper."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import app_server_protocol_matrix as matrix  # noqa: E402


def _schema(*methods):
    return {
        "oneOf": [
            {
                "properties": {
                    "method": {
                        "title": "%sMethod" % method.title().replace("/", ""),
                        "enum": [method],
                    }
                }
            }
            for method in methods
        ]
    }


def main():
    schema = _schema("thread/started", "item/tool/call", "model/list")
    assert matrix.collect_methods(schema) == ["item/tool/call", "model/list", "thread/started"]
    assert matrix.classify("server_notifications", "thread/started") == "supported"
    assert matrix.classify("server_requests", "item/tool/call") == "degraded"
    assert matrix.classify("client_requests", "model/list") == "supported"
    assert matrix.classify("client_requests", "thread/compact/start") == "supported"
    assert matrix.classify("client_requests", "thread/fork") == "supported"
    assert matrix.classify("client_requests", "thread/rollback") == "supported"
    assert matrix.classify("client_requests", "thread/unarchive") == "supported"
    assert matrix.classify("client_requests", "thread/goal/set") == "supported"
    assert matrix.classify("client_requests", "fuzzyFileSearch") == "supported"
    assert matrix.classify("client_requests", "mcpServer/resource/read") == "supported"
    assert matrix.classify("client_requests", "mcpServer/tool/call") == "supported"
    assert matrix.classify("client_requests", "turn/steer") == "supported"
    assert matrix.classify("client_requests", "plugin/list") == "not_integrated"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ServerNotification.json").write_text(
            json.dumps(_schema("thread/started", "app/list/updated")), encoding="utf-8")
        (root / "ServerRequest.json").write_text(
            json.dumps(_schema("item/tool/call")), encoding="utf-8")
        (root / "ClientRequest.json").write_text(
            json.dumps(_schema("thread/start", "thread/fork")), encoding="utf-8")
        methods = matrix.load_methods(root)
        doc = matrix.render_markdown(methods, "codex-cli test")
        assert "Codex CLI: `codex-cli test`" in doc
        assert "| `thread/started` | `supported` |" in doc
        assert "| `app/list/updated` | `degraded` |" in doc
        assert "| `item/tool/call` | `degraded` |" in doc
        assert "Allowlisted MCP passthrough is implemented" in doc
        assert "| `thread/fork` | `supported` |" in doc

    print("app-server protocol matrix checks passed")


if __name__ == "__main__":
    main()
