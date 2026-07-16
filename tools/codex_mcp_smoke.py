# -*- coding: utf-8 -*-
"""Live smoke for Codex app-server MCP tool calls and dynamic passthrough."""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codex_client import CodexAppServerClient  # noqa: E402
import codex_requests  # noqa: E402


SERVER_NAME = "codex_smoke"
TOOL_NAME = "echo"

MCP_ECHO_SERVER = r'''
import json
import sys


def send(obj):
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codex-smoke", "version": "1.0.0"},
            },
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo JSON arguments as text.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "additionalProperties": True,
                    },
                }]
            },
        })
    elif method == "tools/call":
        params = msg.get("params") or {}
        args = params.get("arguments") or {}
        send({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "content": [{"type": "text", "text": "echo:" + json.dumps(args, sort_keys=True)}],
                "isError": False,
            },
        })
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif mid is not None:
        send({
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": -32601, "message": "unknown method " + str(method)},
        })
'''


def config_toml(server_path):
    path = str(server_path).replace("\\", "\\\\")
    return '[mcp_servers.%s]\ncommand = "python"\nargs = ["%s"]\n' % (SERVER_NAME, path)


def first_text_content(result):
    for item in (result or {}).get("content") or []:
        if isinstance(item, dict) and item.get("type") in ("text", "inputText"):
            return str(item.get("text") or "")
    return ""


def server_status_summary(response, server_name):
    for server in (response or {}).get("data") or []:
        if not isinstance(server, dict) or server.get("name") != server_name:
            continue
        tools = server.get("tools") or {}
        resources = server.get("resources") or []
        templates = server.get("resourceTemplates") or []
        return {
            "name": server.get("name") or "",
            "authStatus": server.get("authStatus") or "",
            "tools": sorted(tools.keys()) if isinstance(tools, dict) else [],
            "resource_count": len(resources) if isinstance(resources, list) else 0,
            "resource_template_count": len(templates) if isinstance(templates, list) else 0,
        }
    return {}


class DynamicSmokeSession:
    def __init__(self, client, thread_id, timeout=30):
        self.client = client
        self.thread_id = thread_id
        self.timeout = timeout
        self.records = []
        self.notices = []
        self.mcp_calls = []

    def _record_and_broadcast(self, obj):
        self.records.append(obj)

    def _call_mcp_tool_for_dynamic(self, params):
        self.mcp_calls.append(dict(params))
        return self.client.request("mcpServer/tool/call", params, timeout=self.timeout) or {}

    def _codex_notice(self, message, method, detail=None, silent=False):
        self.notices.append({
            "message": message,
            "method": method,
            "detail": detail,
            "silent": bool(silent),
        })


def validate_dynamic_records(session, call_id):
    seen_use = False
    seen_result = False
    for record in session.records:
        blocks = ((record.get("message") or {}).get("content") or [])
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("id") == call_id:
                seen_use = True
            if block.get("type") == "tool_result" and block.get("tool_use_id") == call_id:
                seen_result = "echo:" in str(block.get("content") or "")
    return seen_use and seen_result


def run_smoke(cwd, timeout=30, keep_temp=False):
    temp_dir = Path(tempfile.mkdtemp(prefix="codex-mcp-smoke-"))
    try:
        server_path = temp_dir / "mcp_echo_server.py"
        server_path.write_text(MCP_ECHO_SERVER.lstrip(), encoding="utf-8")
        (temp_dir / "config.toml").write_text(config_toml(server_path), encoding="utf-8")

        client = CodexAppServerClient(codex_home=str(temp_dir))
        try:
            client.ensure()
            thread_res = client.request("thread/start", {"cwd": os.path.abspath(cwd)}, timeout=timeout) or {}
            thread_id = ((thread_res.get("thread") or {}).get("id") or "").strip()
            if not thread_id:
                raise RuntimeError("thread/start did not return a thread id")

            direct_args = {"text": "direct smoke", "number": 7}
            direct = client.request(
                "mcpServer/tool/call",
                {"server": SERVER_NAME, "tool": TOOL_NAME, "threadId": thread_id, "arguments": direct_args},
                timeout=timeout,
            ) or {}
            direct_text = first_text_content(direct)
            if "direct smoke" not in direct_text or direct.get("isError"):
                raise RuntimeError("direct MCP call returned unexpected result: %s" % json.dumps(direct))

            status_res = client.request(
                "mcpServerStatus/list",
                {"threadId": thread_id, "detail": "full", "limit": 10},
                timeout=timeout,
            ) or {}
            status_summary = server_status_summary(status_res, SERVER_NAME)
            if TOOL_NAME not in (status_summary.get("tools") or []):
                raise RuntimeError("MCP status list did not include smoke tool: %s" % json.dumps(status_res))

            call_id = "dynamic-smoke-call"
            dyn_session = DynamicSmokeSession(client, thread_id, timeout=timeout)
            dynamic = codex_requests.handle_dynamic_tool_call(
                dyn_session,
                "dynamic-smoke-request",
                "item/tool/call",
                {
                    "namespace": "smoke",
                    "tool": "echo",
                    "callId": call_id,
                    "threadId": thread_id,
                    "arguments": {"text": "dynamic smoke", "ok": True},
                },
                {"smoke.echo": "mcp:%s/%s" % (SERVER_NAME, TOOL_NAME)},
            )
            dynamic_text = first_text_content({"content": dynamic.get("contentItems") or []})
            if not dynamic.get("success") or "dynamic smoke" not in dynamic_text:
                raise RuntimeError("dynamic MCP passthrough returned unexpected result: %s" % json.dumps(dynamic))
            if not validate_dynamic_records(dyn_session, call_id):
                raise RuntimeError("dynamic passthrough did not record matching tool_use/tool_result events")

            return {
                "ok": True,
                "thread_id": thread_id,
                "server": SERVER_NAME,
                "tool": TOOL_NAME,
                "direct_text": direct_text,
                "dynamic_text": dynamic_text,
                "status": status_summary,
                "dynamic_records": len(dyn_session.records),
                "mcp_calls": dyn_session.mcp_calls,
            }
        finally:
            client.shutdown()
    finally:
        if not keep_temp:
            for _attempt in range(30):
                try:
                    shutil.rmtree(temp_dir)
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                shutil.rmtree(temp_dir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=str(ROOT), help="Workspace cwd for the temporary Codex thread.")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary CODEX_HOME for debugging.")
    args = parser.parse_args(argv)
    print(json.dumps(run_smoke(args.cwd, timeout=args.timeout, keep_temp=args.keep_temp), indent=2))


if __name__ == "__main__":
    main()
