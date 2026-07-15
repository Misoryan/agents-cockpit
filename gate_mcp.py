# -*- coding: utf-8 -*-
"""
Agents Cockpit — 权限/提问 网关 MCP 服务器 (gate_mcp.py)

claude(每个 native 会话每轮一次性进程)按 --mcp-config 把本脚本当 stdio MCP
服务器拉起。我们暴露两个工具:

  mcp__cockpit__approve   —— 由 --permission-prompt-tool 指定。claude 想调
      ask 清单里的工具(Bash/PowerShell/Edit/Write/NotebookEdit)时,会暂停并
      调本工具,参数 = {tool_name, input, tool_use_id}。我们向 manager 发一个
      阻塞 HTTP 请求(/api/_perm_gate),manager 广播 pending_approval 给网页、
      阻塞等用户在网页点「允许/拒绝」(/api/napprove)→ 解阻塞回裁决 JSON:
        允许 → {"behavior":"allow","updatedInput":{...}}
        拒绝 → {"behavior":"deny","message":"..."}
      claude 拿到后执行/拒绝。期间 claude 整进程阻塞 = 真·打断。

  mcp__cockpit__ask_user  —— 普通工具。模型需要用户澄清/确认意图时调用,参数
      = {question}。我们阻塞问网页(/api/_ask_gate ↔ /api/nanswer),把用户回答
      作为 tool 结果返回。

传输:换行分隔的 JSON-RPC(stdio)。argv = [sid, manager_port]。
只依赖 stdlib(与 common.py 零依赖风格一致)。
"""
import sys
import os
import json
import http.client

# ---- argv: sid, manager_port ----
SID = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    MANAGER_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
except ValueError:
    MANAGER_PORT = 0

HTTP_TIMEOUT = 660  # 略大于 manager 侧 600s 门控超时,让 manager 先裁决

# ask_user 的 tool_use_id 由我们生成(claude 不给普通工具传 tool_use_id)
import threading
_ask_counter = [0]
_ask_lock = threading.Lock()


def _log(msg):
    sys.stderr.write("[gate] " + str(msg) + "\n")
    sys.stderr.flush()


def _send(obj):
    """写一行 JSON-RPC(换行分隔)。stdout 只走协议帧。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _post(path, payload):
    """阻塞 POST 到 manager,返回解析后的 dict。失败抛 OSError。"""
    conn = http.client.HTTPConnection("127.0.0.1", MANAGER_PORT, timeout=HTTP_TIMEOUT)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _result_text(mid, text):
    """成功的 tools/call 结果:content[0].text = text。"""
    _send({"jsonrpc": "2.0", "id": mid, "result": {
        "content": [{"type": "text", "text": text}], "isError": False}})


def _error_text(mid, text):
    """tools/call 返回错误(让 claude 把它当 tool 错误看到,不至于挂死)。"""
    _send({"jsonrpc": "2.0", "id": mid, "result": {
        "content": [{"type": "text", "text": text}], "isError": True}})


def handle_tools_call(mid, params):
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    if name == "approve":
        tool_name = args.get("tool_name", "")
        inp = args.get("input", {}) or {}
        tuid = args.get("tool_use_id", "")
        try:
            verdict = _post("/api/_perm_gate", {
                "sid": SID, "tool_use_id": tuid, "tool_name": tool_name, "input": inp})
        except OSError as e:
            _log("approve gate unreachable: %r" % e)
            verdict = {"behavior": "deny", "message": "审批网关不可达"}
        # manager 回的就是 {behavior, updatedInput|message};原样回给 claude
        _result_text(mid, json.dumps(verdict, ensure_ascii=False))
        return
    if name == "ask_user":
        question = args.get("question", "")
        questions = args.get("questions")
        tuid = args.get("tool_use_id")
        if not tuid:
            with _ask_lock:
                _ask_counter[0] += 1
                tuid = "ask_%d_%d" % (_ask_counter[0], id(question) & 0xffff)
        try:
            resp = _post("/api/_ask_gate", {
                "sid": SID, "tool_use_id": tuid,
                "question": question, "questions": questions})
            ans = resp.get("answer", "")
        except OSError as e:
            _log("ask gate unreachable: %r" % e)
            ans = "(提问网关不可达)"
        _result_text(mid, ans if isinstance(ans, str) else json.dumps(ans, ensure_ascii=False))
        return
    # 未知工具
    _error_text(mid, "unknown tool: %s" % name)


def main():
    _log("gate up sid=%s port=%s" % (SID, MANAGER_PORT))
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cockpit-gate", "version": "1.0"}}})
        elif method == "notifications/initialized":
            pass  # 通知,不回
        elif method == "tools/list":
            tools = [
                {"name": "approve",
                 "description": "Permission gate. Called automatically before running tools that need approval. Do not call directly.",
                 "inputSchema": {"type": "object",
                                 "properties": {"tool_name": {"type": "string"},
                                                "input": {"type": "object"},
                                                "tool_use_id": {"type": "string"}},
                                 "required": ["tool_name", "input", "tool_use_id"]}},
                {"name": "ask_user",
                 "description": "向用户提问以获取澄清、确认或输入,会阻塞等待用户回答。当信息不足、需要用户决策或确认意图时调用,不要瞎猜。可只传 question(简单文本),或传 questions 做结构化提问(AskUserQuestion 风格)。questions 是数组,每项含:question(必填,问题文本)、header(短标签)、options(数组,每项含 label 与 description)、multiSelect(布尔,是否多选)。用户在网页点选后把回答返回给你。",
                 "inputSchema": {"type": "object",
                                 "properties": {"question": {"type": "string", "description": "简单提问文本(与 questions 二选一)"},
                                                "questions": {"type": "array", "description": "结构化提问数组(AskUserQuestion 风格),每项含 question/header/options[{label,description}]/multiSelect"}},
                                 "required": []}},
            ]
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
        elif method == "tools/call":
            handle_tools_call(mid, msg.get("params", {}) or {})
        else:
            if mid is not None:
                _send({"jsonrpc": "2.0", "id": mid, "result": {}})
    _log("gate stdin EOF, exit")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log("gate fatal: %r" % e)
    sys.stdout.flush()
