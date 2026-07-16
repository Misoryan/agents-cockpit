"""Static helper checks for the live Codex MCP smoke."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import codex_mcp_smoke as smoke  # noqa: E402


def main():
    cfg = smoke.config_toml(Path(r"C:\tmp\mcp_echo_server.py"))
    assert "[mcp_servers.codex_smoke]" in cfg
    assert 'command = "python"' in cfg
    assert "mcp_echo_server.py" in cfg
    assert "tools/call" in smoke.MCP_ECHO_SERVER
    assert "tools/list" in smoke.MCP_ECHO_SERVER

    result = {"content": [{"type": "text", "text": "hello"}, {"type": "image", "data": "x"}]}
    assert smoke.first_text_content(result) == "hello"
    assert smoke.first_text_content({"content": [{"type": "inputText", "text": "hi"}]}) == "hi"
    assert smoke.first_text_content({"content": [{"type": "image"}]}) == ""

    session = smoke.DynamicSmokeSession(client=None, thread_id="thread-1")
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "call-1"}]},
    })
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "echo:{}"}]},
    })
    assert smoke.validate_dynamic_records(session, "call-1")
    assert not smoke.validate_dynamic_records(session, "call-2")
    print("codex mcp smoke helper checks passed")


if __name__ == "__main__":
    main()
