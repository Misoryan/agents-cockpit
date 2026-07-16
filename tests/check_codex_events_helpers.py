"""Check extracted Codex item-to-event conversion helpers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_events  # noqa: E402
import codex_native  # noqa: E402


def main():
    ev = codex_events.tool_event_from_item(
        {"type": "commandExecution", "id": "cmd-1", "command": "echo hi"},
        cwd="repo",
        os_name="posix",
    )
    block = ev["message"]["content"][0]
    assert block["id"] == "cmd-1"
    assert block["name"] == "Bash"
    assert block["input"] == {"command": "echo hi", "cwd": "repo"}

    ev = codex_events.tool_event_from_item(
        {"type": "commandExecution", "command": "dir"},
        cwd="repo",
        os_name="nt",
        now_ms=123,
    )
    block = ev["message"]["content"][0]
    assert block["id"] == "item-123"
    assert block["name"] == "PowerShell"

    ev = codex_events.tool_event_from_item(
        {"type": "fileChange", "id": "f1", "changes": [{"path": "a.py"}]},
        cwd="repo",
    )
    assert ev["message"]["content"][0]["name"] == "Edit"
    assert ev["message"]["content"][0]["input"]["file_path"] == "a.py"

    assert codex_events.tool_event_from_item({"type": "agentMessage"}, cwd="repo") is None
    assert codex_events.tool_event_from_item({"type": "plan", "text": "do it"}, cwd="repo")[
        "message"]["content"][0]["text"] == "<proposed_plan>\ndo it\n</proposed_plan>"
    assert codex_events.tool_event_from_item({"type": "mcpToolCall", "id": "m1", "server": "srv", "tool": "run",
                                             "arguments": {"x": 1}}, cwd="repo")[
        "message"]["content"][0]["name"] == "srv.run"
    assert codex_events.tool_event_from_item({"type": "dynamicToolCall", "id": "d1", "namespace": "ns",
                                             "tool": "go"}, cwd="repo")[
        "message"]["content"][0]["name"] == "ns.go"
    assert codex_events.tool_event_from_item({"type": "webSearch", "id": "w1", "query": "q"}, cwd="repo")[
        "message"]["content"][0]["input"]["query"] == "q"
    assert codex_events.tool_event_from_item({"type": "unknown", "id": "u1", "x": 2}, cwd="repo")[
        "message"]["content"][0]["name"] == "unknown"

    result = codex_events.tool_result_from_item(
        {"type": "commandExecution", "id": "cmd-1", "aggregatedOutput": "out", "exitCode": 2,
         "durationMs": 1234})
    result_block = result["message"]["content"][0]
    assert result_block["content"] == "out\nexit code: 2\nduration ms: 1234"
    assert result_block["exit_code"] == 2
    assert result_block["duration_ms"] == 1234
    assert result_block["aggregated_output"] == "out"
    assert codex_events.tool_result_from_item({"type": "fileChange", "id": "f1",
                                              "changes": [{"kind": "modify", "path": "a.py", "diff": "@@"}],
                                              "status": "done"})[
        "message"]["content"][0]["content"] == "--- modify a.py\n@@\n\nstatus: done"
    assert '"ok": true' in codex_events.tool_result_from_item(
        {"type": "mcpToolCall", "id": "m1", "result": {"ok": True}})["message"]["content"][0]["content"]
    assert '"success": false' in codex_events.tool_result_from_item(
        {"type": "dynamicToolCall", "id": "d1", "success": False})["message"]["content"][0]["content"]
    assert '"type": "webSearch"' in codex_events.tool_result_from_item(
        {"type": "webSearch", "id": "w1"})["message"]["content"][0]["content"]
    assert codex_events.tool_result_from_item({"type": "agentMessage", "id": "a1"}) is None
    assert codex_events.tool_result_from_item({"type": "commandExecution"}) is None

    session = object.__new__(codex_native.CodexSession)
    session.cwd = "repo"
    assert session._tool_event_from_item({"type": "commandExecution", "id": "cmd-2"})[
        "message"]["content"][0]["input"]["cwd"] == "repo"
    assert session._tool_result_from_item({"type": "commandExecution", "id": "cmd-2", "exitCode": 0})[
        "message"]["content"][0]["content"] == "exit code: 0"

    print("codex event helper checks passed")


if __name__ == "__main__":
    main()
