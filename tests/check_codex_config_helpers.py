"""Check Codex launch config normalization and app-server params."""
import base64
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_config  # noqa: E402
from codex_native import CodexSession  # noqa: E402


def main():
    cfg = codex_config.normalize_launch_config({
        "model": " gpt-5-codex ",
        "approvalPolicy": "on-request",
        "sandbox": "workspace-write",
        "webSearch": "live",
        "reasoningEffort": "medium",
        "reasoningSummary": "concise",
        "serviceTier": "auto",
        "writableRoots": ["extras", "extras"],
        "ignored": "x",
    }, cwd="C:/repo")
    assert cfg == {
        "model": "gpt-5-codex",
        "approval_policy": "on-request",
        "sandbox": "workspace-write",
        "web_search": "live",
        "reasoning_effort": "medium",
        "reasoning_summary": "concise",
        "service_tier": "auto",
        "writable_roots": [os.path.abspath("C:/repo/extras")],
    }
    assert codex_config.normalize_launch_config({"approvalPolicy": "bad", "sandbox": "bad"}) == {}
    assert codex_config.normalize_launch_config({"search": True})["web_search"] == "live"
    assert codex_config.normalize_launch_config({"search": False})["web_search"] == "disabled"
    assert codex_config.thread_config(cfg) == {
        "web_search": "live",
        "model_reasoning_effort": "medium",
        "model_reasoning_summary": "concise",
        "service_tier": "auto",
        "sandbox_workspace_write": {"writable_roots": [os.path.abspath("C:/repo/extras")]},
    }
    assert codex_config.sandbox_policy("danger-full-access") == {"type": "dangerFullAccess"}
    assert codex_config.sandbox_policy("read-only") == {"type": "readOnly"}
    assert codex_config.sandbox_policy("workspace-write", "C:/repo", ["C:/repo/extras"]) == {
        "type": "workspaceWrite",
        "writableRoots": [os.path.abspath("C:/repo"), os.path.abspath("C:/repo/extras")],
    }
    assert codex_config.account_status({
        "requiresOpenaiAuth": False,
        "account": {"type": "chatgpt", "email": "user@example.com", "planType": "plus"},
    }) == {
        "signed_in": True,
        "requires_openai_auth": False,
        "type": "chatgpt",
        "email": "user@example.com",
        "plan_type": "plus",
        "credential_source": "",
    }

    class LaunchOptionsClient:
        def __init__(self):
            self.calls = []

        def request(self, method, params, timeout=0):
            self.calls.append((method, params, timeout))
            if method == "model/list":
                return {"data": [{"id": "gpt-5-codex"}]}
            if method == "permissionProfile/list":
                return {"data": [{"id": "workspace-write"}]}
            if method == "config/read":
                return {"config": {"model": "gpt-5-codex", "approval_policy": "on-request"}}
            if method == "account/read":
                return {"requiresOpenaiAuth": False, "account": {
                    "type": "chatgpt",
                    "email": "user@example.com",
                    "planType": "pro",
                }}
            return {}

    launch_client = LaunchOptionsClient()
    launch_options = codex_config.load_launch_options(launch_client, cwd="C:/repo")
    assert launch_options["models"] == [{"id": "gpt-5-codex"}]
    assert launch_options["permission_profiles"] == [{"id": "workspace-write"}]
    assert launch_options["config"]["approval_policy"] == "on-request"
    assert launch_options["account"]["type"] == "chatgpt"
    assert launch_options["account"]["plan_type"] == "pro"
    assert ("account/read", {"refreshToken": False}, 8) in launch_client.calls

    with tempfile.TemporaryDirectory() as td:
        Path(td, "README.md").write_text("hello", encoding="utf-8")
        session = CodexSession("s1", td, yolo=False, cfg=cfg, state_dir=td)
        thread = session._thread_params()
        assert thread["cwd"] == os.path.abspath(td)
        assert thread["model"] == "gpt-5-codex"
        assert thread["approvalPolicy"] == "on-request"
        assert thread["sandbox"] == "workspace-write"
        assert thread["serviceTier"] == "auto"
        assert thread["config"]["web_search"] == "live"
        assert thread["config"]["model_reasoning_effort"] == "medium"
        assert thread["config"]["model_reasoning_summary"] == "concise"
        session.thread_id = "thread-1"
        turn = session._turn_params("hello")
        assert turn["model"] == "gpt-5-codex"
        assert turn["approvalPolicy"] == "on-request"
        assert turn["serviceTier"] == "auto"
        assert turn["effort"] == "medium"
        assert turn["summary"] == "concise"
        assert turn["sandboxPolicy"]["type"] == "workspaceWrite"
        assert turn["sandboxPolicy"]["writableRoots"] == [os.path.abspath(td), os.path.abspath("C:/repo/extras")]
        assert turn["collaborationMode"]["settings"]["model"] == "gpt-5-codex"
        assert turn["collaborationMode"]["settings"]["reasoning_effort"] == "medium"
        mention_turn = session._turn_params("read @README.md")
        mention_items = [item for item in mention_turn["input"] if item.get("type") == "mention"]
        assert mention_items and mention_items[0]["path"] == os.path.abspath(Path(td, "README.md"))
        session._persist()
        assert '"cfg"' in Path(td, "codex_s1.json").read_text(encoding="utf-8")
        assert session.handle_slash_command("/model o4-mini") == {
            "ok": True,
            "command": "model",
            "model": "o4-mini",
        }
        assert session.cfg["model"] == "o4-mini"
        assert session.model == "o4-mini"
        assert session.handle_slash_command("/approval never") == {
            "ok": True,
            "command": "approval",
            "approval_policy": "never",
        }
        assert session.cfg["approval_policy"] == "never"
        assert session.handle_slash_command("/sandbox read-only") == {
            "ok": True,
            "command": "sandbox",
            "sandbox": "read-only",
        }
        assert session.cfg["sandbox"] == "read-only"
        assert session.handle_slash_command("/search on")["error"].startswith("web search")

        fresh = CodexSession("s0", td, yolo=False, state_dir=td)
        assert fresh.handle_slash_command("/search on") == {
            "ok": True,
            "command": "search",
            "web_search": "live",
        }
        assert fresh.cfg["web_search"] == "live"
        assert session.handle_slash_command("/reasoning high") == {
            "ok": True,
            "command": "reasoning",
            "reasoning_effort": "high",
        }
        assert session.cfg["reasoning_effort"] == "high"
        assert session.handle_slash_command("/summary detailed") == {
            "ok": True,
            "command": "summary",
            "reasoning_summary": "detailed",
        }
        assert session.cfg["reasoning_summary"] == "detailed"
        assert session.handle_slash_command("/service-tier flex") == {
            "ok": True,
            "command": "service-tier",
            "service_tier": "flex",
        }
        assert session.cfg["service_tier"] == "flex"
        assert session.handle_slash_command("/add-dir subdir") == {
            "ok": True,
            "command": "writable-roots",
            "writable_roots": [os.path.abspath(Path(td, "subdir"))],
        }

        yolo = CodexSession("s2", td, yolo=True, cfg=cfg, state_dir=td)
        assert yolo._thread_params()["approvalPolicy"] == "never"
        assert yolo._thread_params()["sandbox"] == "danger-full-access"
        yolo.thread_id = "thread-2"
        assert yolo._turn_params("hello")["sandboxPolicy"] == {"type": "dangerFullAccess"}
        assert yolo.handle_slash_command("/approval on-request")["ok"] is False
        assert yolo.handle_slash_command("/sandbox workspace-write")["ok"] is False

        class FakeClient:
            def __init__(self):
                self.calls = []

            def ensure(self):
                self.calls.append(("ensure", None))

            def register(self, thread_id, session_obj):
                self.calls.append(("register", thread_id, session_obj.sid))

            def request(self, method, params, timeout=0):
                self.calls.append((method, params, timeout))
                if method == "thread/fork":
                    return {"thread": {"id": "fork-thread"}}
                if method == "thread/goal/get":
                    return {"goal": {"objective": "Keep parity smooth", "status": "active", "tokensUsed": 12}}
                if method == "thread/goal/set":
                    return {"goal": {
                        "objective": params.get("objective") or "Keep parity smooth",
                        "status": params.get("status") or "active",
                        "tokensUsed": 12,
                        "tokenBudget": params.get("tokenBudget"),
                    }}
                if method == "fuzzyFileSearch":
                    return {"files": [
                        {"file_name": "README.md", "match_type": "file", "path": "README.md", "root": td, "score": 99},
                        {"file_name": "outside.txt", "match_type": "file", "path": "C:/outside.txt", "root": "C:/", "score": 1},
                    ]}
                if method == "mcpServer/resource/read":
                    return {"contents": [{"uri": params.get("uri"), "text": "resource text"}]}
                if method == "mcpServer/tool/call":
                    return {"content": [{"type": "text", "text": "tool result"}], "isError": False}
                if method == "thread/rollback":
                    return {"thread": {
                        "id": "thread-4",
                        "turns": [
                            {"items": [
                                {"type": "userMessage", "content": [{"type": "text", "text": "kept"}]},
                                {"type": "agentMessage", "text": "still here"},
                            ]}
                        ],
                    }}
                return {}

        compact = CodexSession("s3", td, state_dir=td)
        compact.thread_id = "thread-3"
        compact._thread_ready = True
        fake = FakeClient()
        compact._client = lambda: fake
        assert compact.handle_slash_command("/compact") == {"ok": True, "command": "compact"}
        assert compact._busy is True
        assert compact._compact_in_progress is True
        assert ("thread/compact/start", {"threadId": "thread-3"}, 30) in fake.calls
        assert compact.handle_slash_command("/unknown")["ok"] is False

        lifecycle = CodexSession("s4", td, state_dir=td)
        lifecycle.thread_id = "thread-4"
        lifecycle._thread_ready = True
        fake2 = FakeClient()
        lifecycle._client = lambda: fake2
        assert lifecycle.handle_slash_command("/rename Better name") == {
            "ok": True,
            "command": "rename",
            "name": "Better name",
        }
        assert ("thread/name/set", {"threadId": "thread-4", "name": "Better name"}, 30) in fake2.calls
        assert lifecycle.handle_slash_command("/archive") == {
            "ok": True,
            "command": "archive",
            "thread_id": "thread-4",
        }
        assert ("thread/archive", {"threadId": "thread-4"}, 30) in fake2.calls
        assert lifecycle.handle_slash_command("/unarchive") == {
            "ok": True,
            "command": "unarchive",
            "thread_id": "thread-4",
        }
        assert ("thread/unarchive", {"threadId": "thread-4"}, 30) in fake2.calls
        assert lifecycle.handle_slash_command("/fork") == {
            "ok": True,
            "command": "fork",
            "thread_id": "fork-thread",
        }
        assert lifecycle.timeline[-1]["type"] == "thread_forked"
        assert lifecycle.timeline[-1]["thread_id"] == "fork-thread"
        fork_calls = [call for call in fake2.calls if call[0] == "thread/fork"]
        assert fork_calls and fork_calls[0][1]["threadId"] == "thread-4"
        assert lifecycle.handle_slash_command("/rollback 1") == {
            "ok": True,
            "command": "rollback",
            "num_turns": 1,
        }
        rollback_calls = [call for call in fake2.calls if call[0] == "thread/rollback"]
        assert rollback_calls and rollback_calls[0][1] == {"threadId": "thread-4", "numTurns": 1}
        assert lifecycle.events[0]["type"] == "user"
        assert lifecycle.events[1]["type"] == "assistant"
        assert lifecycle.handle_slash_command("/goal get")["goal"]["objective"] == "Keep parity smooth"
        assert lifecycle.handle_slash_command("/goal set Finish CLI parity")["goal"]["objective"] == "Finish CLI parity"
        assert ("thread/goal/set", {"threadId": "thread-4", "objective": "Finish CLI parity", "status": "active"}, 30) in fake2.calls
        assert lifecycle.handle_slash_command("/goal status paused")["status"] == "paused"
        assert ("thread/goal/set", {"threadId": "thread-4", "status": "paused"}, 30) in fake2.calls
        assert lifecycle.handle_slash_command("/goal clear") == {"ok": True, "command": "goal", "action": "clear"}
        assert ("thread/goal/clear", {"threadId": "thread-4"}, 30) in fake2.calls
        found_files = lifecycle.search_files("readme", limit=5)["files"]
        assert found_files == [{
            "path": os.path.abspath(Path(td, "README.md")),
            "insert": "README.md",
            "name": "README.md",
            "match_type": "file",
            "score": 99,
        }]
        assert [call for call in fake2.calls if call[0] == "fuzzyFileSearch"][0][1] == {
            "query": "readme",
            "roots": [os.path.abspath(td)],
        }
        images = lifecycle.prepare_image_inputs([{
            "name": "screen.png",
            "type": "image/png",
            "data_url": "data:image/png;base64,%s" % base64.b64encode(b"png").decode("ascii"),
        }])
        assert len(images) == 1
        assert images[0]["type"] == "localImage"
        assert images[0]["name"] == "screen.png"
        assert os.path.isfile(images[0]["path"])
        image_items = lifecycle._user_input_items("look", image_inputs=images)
        assert image_items[0]["type"] == "text"
        assert image_items[-1] == {"type": "localImage", "path": images[0]["path"], "detail": "auto"}
        assert lifecycle.image_file(images[0]["image_id"]) == images[0]["path"]
        term_event = lifecycle.terminal_interaction_event(
            {"processId": "proc-1", "itemId": "item-1", "stdin": "input:"})
        assert term_event["type"] == "terminal_interaction"
        assert lifecycle._pending_events_snapshot()[-1]["process_id"] == "proc-1"
        assert lifecycle.terminal_write("proc-1", "hello\n") == {
            "ok": True,
            "process_id": "proc-1",
            "closed": False,
        }
        write_calls = [call for call in fake2.calls if call[0] == "command/exec/write"]
        assert write_calls[-1][1]["deltaBase64"] == base64.b64encode(b"hello\n").decode("ascii")
        assert lifecycle.terminal_resize("proc-1", 100, 30) == {
            "ok": True,
            "process_id": "proc-1",
            "cols": 100,
            "rows": 30,
        }
        resize_calls = [call for call in fake2.calls if call[0] == "command/exec/resize"]
        assert resize_calls[-1][1] == {"processId": "proc-1", "size": {"cols": 100, "rows": 30}}
        assert lifecycle.terminal_terminate("proc-1") == {
            "ok": True,
            "process_id": "proc-1",
            "terminated": True,
        }
        assert [call for call in fake2.calls if call[0] == "command/exec/terminate"][-1][1] == {"processId": "proc-1"}
        assert lifecycle.terminal_write("proc-1", "x")["ok"] is False
        assert lifecycle.handle_slash_command('/mcp-resource docs "file://guide.md"') == {
            "ok": True,
            "command": "mcp-resource",
            "server": "docs",
            "uri": "file://guide.md",
        }
        resource_calls = [call for call in fake2.calls if call[0] == "mcpServer/resource/read"]
        assert resource_calls[-1][1] == {"server": "docs", "uri": "file://guide.md", "threadId": "thread-4"}
        assert lifecycle.events[-2]["message"]["content"][0]["name"] == "mcpServer.resource/read"
        assert lifecycle.handle_slash_command('/mcp-tool docs search {"q":"codex"}') == {
            "ok": True,
            "command": "mcp-tool",
            "server": "docs",
            "tool": "search",
        }
        tool_calls = [call for call in fake2.calls if call[0] == "mcpServer/tool/call"]
        assert tool_calls[-1][1] == {
            "server": "docs",
            "tool": "search",
            "threadId": "thread-4",
            "arguments": {"q": "codex"},
        }
        assert lifecycle.handle_slash_command("/mcp-tool docs search []")["ok"] is False

        steer = CodexSession("s5", td, state_dir=td)
        steer.thread_id = "thread-5"
        steer.last_turn_id = "turn-5"
        steer._busy = True
        fake3 = FakeClient()
        steer._client = lambda: fake3
        assert steer.handle_slash_command("/steer focus on tests") == {"ok": True, "command": "steer"}
        steer_calls = [call for call in fake3.calls if call[0] == "turn/steer"]
        assert steer_calls and steer_calls[0][1]["expectedTurnId"] == "turn-5"
        assert steer_calls[0][1]["input"][0]["text"] == "focus on tests"

    print("codex config helper checks passed")


if __name__ == "__main__":
    main()
