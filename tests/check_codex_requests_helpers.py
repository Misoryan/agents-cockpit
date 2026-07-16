"""Check extracted Codex app-server request helpers."""
import sys
import threading
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_requests  # noqa: E402


class AppError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class FakeSession:
    def __init__(self):
        self.cwd = str(Path.cwd())
        self._pending = {}
        self._pending_lock = threading.Lock()
        self.broadcasts = []
        self.pushes = []
        self.records = []
        self.notices = []
        self.approval_calls = []
        self.ask_calls = []
        self.form_calls = []
        self._item_output = {}
        self.dynamic_mappings = {}
        self.mcp_calls = []
        self.mcp_result = {"content": [{"type": "text", "text": "mcp ok"}], "isError": False}

    def _is_dangerous(self, text):
        return "rm -rf" in str(text)

    def _broadcast(self, event):
        self.broadcasts.append(event)
        req_id = event.get("tool_use_id")
        entry = self._pending.get(req_id)
        if not entry:
            return
        if entry["kind"] == "approve":
            entry["allow"] = True
            entry["always"] = True
        elif entry["kind"] == "ask":
            entry["answer"] = {"q1": ["A"]}
        elif entry["kind"] == "form":
            entry["answer"] = {"action": "accept", "content": {"field": "value"}}
        entry["event"].set()

    def _push(self, event, title, body, webhook_body=None):
        self.pushes.append((event, title, body, webhook_body))

    def _record_and_broadcast(self, event):
        self.records.append(event)
        self._broadcast(event)

    def _codex_notice(self, message, method=None, params=None, silent=False):
        self.notices.append((message, method, params, silent))

    def _await_approval(self, req_id, method, params, name, preview):
        self.approval_calls.append((req_id, method, params, name, preview))
        return {"approved": name}

    def _await_user_input(self, req_id, method, params):
        self.ask_calls.append((req_id, method, params))
        return {"asked": method}

    def _await_form_input(self, req_id, method, params):
        self.form_calls.append((req_id, method, params))
        return {"formed": method}

    def _reject_dynamic_tool_call(self, req_id, method, params):
        return codex_requests.reject_dynamic_tool_call(self, req_id, method, params)

    def _handle_dynamic_tool_call(self, req_id, method, params):
        return codex_requests.handle_dynamic_tool_call(
            self, req_id, method, params, self.dynamic_mappings)

    def _call_mcp_tool_for_dynamic(self, params):
        self.mcp_calls.append(params)
        return self.mcp_result


def main():
    assert codex_requests.approval_response("item/commandExecution/requestApproval", True, True, {}) == {
        "decision": "acceptForSession"
    }
    assert codex_requests.approval_response("item/fileChange/requestApproval", False, False, {}) == {
        "decision": "decline"
    }
    assert codex_requests.approval_response("item/permissions/requestApproval", True, True, {"permissions": {"x": 1}}) == {
        "permissions": {"x": 1}, "scope": "session"
    }

    session = FakeSession()
    result = codex_requests.await_approval(
        session, "approve-1", "item/commandExecution/requestApproval",
        {"command": "rm -rf x"}, "Command", "rm -rf x", timeout=1)
    assert result == {"decision": "acceptForSession"}
    assert session.broadcasts[0]["type"] == "pending_approval"
    assert session.broadcasts[0]["danger"] is True
    assert session.pushes[0][0] == "confirm"
    assert "approve-1" not in session._pending

    questions = [{"id": "q1", "question": "Pick?"}]
    assert codex_requests.user_input_response("item/tool/requestUserInput", questions, {"q1": ["A"]}) == {
        "answers": {"q1": {"answers": ["A"]}}
    }
    assert codex_requests.user_input_response("mcpServer/elicitation/request", questions, {"field": ["x", "y"]}) == {
        "action": "accept", "content": {"field": ["x", "y"]}
    }
    assert codex_requests.user_input_response("mcpServer/elicitation/request", questions, "") == {
        "action": "decline", "content": None
    }

    session = FakeSession()
    result = codex_requests.await_user_input(
        session, "ask-1", "item/tool/requestUserInput",
        {"questions": [{"id": "q1", "question": "Pick?", "options": ["A"]}], "autoResolutionMs": 1000},
        timeout=2)
    assert result == {"answers": {"q1": {"answers": ["A"]}}}
    assert session.broadcasts[0]["type"] == "pending_ask"
    assert session.broadcasts[0]["auto_resolution_ms"] == 1000

    assert codex_requests.form_response({"action": "accept", "content": {"x": 1}}) == {
        "action": "accept", "content": {"x": 1}
    }
    assert codex_requests.form_response({"action": "weird", "content": {"x": 1}}) == {
        "action": "accept", "content": {"x": 1}
    }
    assert codex_requests.form_response(None) == {"action": "decline", "content": None}

    session = FakeSession()
    result = codex_requests.await_form_input(
        session, "form-1", "mcpServer/elicitation/request",
        {"mode": "form", "serverName": "srv", "message": "Fill", "requestedSchema": {
            "properties": {"field": {"type": "string"}}
        }},
        timeout=1)
    assert result == {"action": "accept", "content": {"field": "value"}}
    assert session.broadcasts[0]["type"] == "pending_form"
    assert session.broadcasts[0]["fields"][0]["id"] == "field"

    session = FakeSession()
    result = codex_requests.reject_dynamic_tool_call(
        session, "req-1", "item/tool/call",
        {"namespace": "ns", "tool": "do", "callId": "call-1", "arguments": {"a": 1}})
    assert result["success"] is False
    assert session.records[0]["message"]["content"][0]["name"] == "ns.do"
    assert session.records[1]["message"]["content"][0]["tool_use_id"] == "call-1"
    assert session.notices[0][0] == "Dynamic tool call was rejected by the Web adapter"

    session = FakeSession()
    session.dynamic_mappings = {"ns.do": "mcp:docs/search"}
    result = codex_requests.handle_dynamic_tool_call(
        session, "req-1", "item/tool/call",
        {"namespace": "ns", "tool": "do", "callId": "call-1", "threadId": "thread-1",
         "arguments": {"q": "codex"}},
        session.dynamic_mappings)
    assert result == {"success": True, "contentItems": [{"type": "inputText", "text": "mcp ok"}]}
    assert session.mcp_calls == [{
        "server": "docs",
        "tool": "search",
        "threadId": "thread-1",
        "arguments": {"q": "codex"},
    }]
    assert session.records[0]["message"]["content"][0]["name"] == "ns.do"
    assert session.records[1]["message"]["content"][0]["content"] == "mcp ok"

    assert codex_requests.dynamic_tool_target(
        {"namespace": "ns", "tool": "read"}, {"ns.*": "mcp:docs/{tool}"}) == ("docs", "read")
    recovery = codex_requests.recoverable_unsupported_request("account/chatgptAuthTokens/refresh")
    assert "codex login" in recovery["message"]
    assert recovery["detail"]["adapter_status"].startswith("visible unsupported")

    session = FakeSession()
    assert codex_requests.handle_server_request(
        session, "req-2", "item/fileChange/requestApproval", {"reason": "why"}, AppError
    ) == {"approved": "FileChange"}
    assert session.approval_calls[0][-1] == "why"
    assert codex_requests.handle_server_request(
        session, "req-3", "mcpServer/elicitation/request", {"mode": "form"}, AppError
    ) == {"formed": "mcpServer/elicitation/request"}
    assert codex_requests.handle_server_request(
        session, "req-4", "currentTime/read", {}, AppError
    )["utcTimestampMs"] > 0
    session.dynamic_mappings = {"ns.do": "mcp:docs/search"}
    result = codex_requests.handle_server_request(
        session, "req-4b", "item/tool/call",
        {"namespace": "ns", "tool": "do", "callId": "call-4b", "threadId": "thread-4",
         "arguments": {"q": "via handler"}},
        AppError,
    )
    assert result["success"] is True
    assert session.mcp_calls[-1]["server"] == "docs"
    try:
        codex_requests.handle_server_request(
            session, "req-4c", "account/chatgptAuthTokens/refresh",
            {"accessToken": "secret-token"}, AppError)
        raise AssertionError("expected AppError")
    except AppError as exc:
        assert exc.code == -32601
        assert "token refresh" in exc.message
    assert session.notices[-1][1] == "account/chatgptAuthTokens/refresh"
    assert "secret-token" not in str(session.notices[-1])
    assert "Run `codex login`" in session.notices[-1][2]["recovery"][0]
    try:
        codex_requests.handle_server_request(session, "req-4d", "attestation/generate", {"nonce": "abc"}, AppError)
        raise AssertionError("expected AppError")
    except AppError as exc:
        assert exc.code == -32601
        assert "attestation" in exc.message
    assert session.notices[-1][1] == "attestation/generate"
    assert "device/security attestation" in session.notices[-1][2]["recovery"][1]
    try:
        codex_requests.handle_server_request(session, "req-5", "unknown/method", {}, AppError)
        raise AssertionError("expected AppError")
    except AppError as exc:
        assert exc.code == -32601
        assert "unsupported app-server request" in exc.message

    adapter = codex_requests.CodexRequestAdapter(session, AppError, lambda: {"ns.do": "mcp:docs/search"})
    event = adapter.tool_event_from_item({"id": "item-1", "type": "commandExecution", "command": "echo hi"})
    assert event["message"]["content"][0]["input"]["cwd"] == session.cwd
    adapter.append_tool_output("item-1", "hello")
    adapter.append_tool_output("item-1", " world")
    assert session._item_output["item-1"] == "hello world"
    assert session.broadcasts[-1]["message"]["content"][0]["content"] == "hello world"
    assert adapter.handle_server_request("req-6", "currentTime/read", {})["utcTimestampMs"] > 0
    assert adapter.handle_dynamic_tool_call(
        "req-7", "item/tool/call",
        {"namespace": "ns", "tool": "do", "callId": "call-7", "threadId": "thread-7",
         "arguments": {"q": "adapter"}},
    )["success"] is True
    assert session.mcp_calls[-1]["threadId"] == "thread-7"

    print("codex request helper checks passed")


if __name__ == "__main__":
    main()
