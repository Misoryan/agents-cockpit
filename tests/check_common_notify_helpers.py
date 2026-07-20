"""Check notification helpers after extracting them from common.py."""
import json
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_notify  # noqa: E402


class FakeResponse:
    status = 200

    def __init__(self, body=b"{}"):
        self.body = body

    def read(self):
        return self.body


class FakeConnection:
    last = None

    def __init__(self, host, timeout=None):
        self.host = host
        self.timeout = timeout
        self.requests = []
        FakeConnection.last = self

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers or {}))

    def getresponse(self):
        return FakeResponse(b'{"code":0}')

    def close(self):
        pass


def main():
    settings = common_notify.NotifySettings(enabled=True, events={"done"}, timeout=1)
    assert common_notify.notify_enabled_for("done", settings)
    assert not common_notify.notify_enabled_for("confirm", settings)
    assert not common_notify.push_notify("title", "body", "confirm", settings)
    assert not common_notify.desktop_notify("title", "body", settings=settings)

    events = [
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "skip"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello world"}]}},
    ]
    assert common_notify.notify_result_text(events) == "hello world"
    assert common_notify.notify_result_text(events, limit=8).endswith("truncated)")
    title, body = common_notify.notify_copy("confirm", r"E:\repo", "Codex", "rm -rf x", danger=True)
    assert title == "高危操作待确认 · repo"
    assert body.splitlines()[:3] == ["Codex", "rm -rf x", "点击打开会话处理确认"]
    title, body = common_notify.notify_copy("done", r"E:\repo", "Claude")
    assert title == "任务完成 · repo"
    assert "等待下一条指令" in body
    assert common_notify.ps_quote("a'b\nc") == "a''b c"
    assert common_notify.webhook_is_feishu("https://open.feishu.cn/open-apis/bot/v2/hook/x")
    assert not common_notify.webhook_is_feishu("https://example.com/hook")

    old_http = common_notify.http.client.HTTPConnection
    old_https = common_notify.http.client.HTTPSConnection
    try:
        common_notify.http.client.HTTPConnection = FakeConnection
        common_notify.http.client.HTTPSConnection = FakeConnection

        assert common_notify.webhook_send("http://example.test/hook?x=1", "", "T", "B", "done")
        method, path, body, headers = FakeConnection.last.requests[0]
        assert method == "POST"
        assert path == "/hook?x=1"
        assert headers["Content-Type"] == "application/json"
        assert json.loads(body.decode()) == {"title": "T", "body": "B", "event": "done"}

        assert common_notify.webhook_send(
            "https://open.feishu.cn/open-apis/bot/v2/hook/x", "secret", "T", "B", "done"
        )
        payload = json.loads(FakeConnection.last.requests[0][2].decode())
        assert payload["msg_type"] == "text"
        assert payload["content"]["text"] == "T\nB"
        assert payload["sign"]
    finally:
        common_notify.http.client.HTTPConnection = old_http
        common_notify.http.client.HTTPSConnection = old_https

    old_enabled = common.NOTIFY_ENABLED
    old_events = common.NOTIFY_EVENTS
    old_webhook = common.NOTIFY_WEBHOOK_URL
    old_desktop = common.NOTIFY_DESKTOP_TOAST
    try:
        common.NOTIFY_ENABLED = True
        common.NOTIFY_EVENTS = {"done"}
        common.NOTIFY_WEBHOOK_URL = ""
        common.NOTIFY_DESKTOP_TOAST = False
        assert common._notify_enabled_for("done")
        assert not common._notify_enabled_for("confirm")
        assert common.notify_result_text(events) == "hello world"
        assert common.notify_copy("plan", r"E:\repo", "Codex")[0] == "计划待审阅 · repo"
        assert not common.push_notify("title", "body", "confirm")
    finally:
        common.NOTIFY_ENABLED = old_enabled
        common.NOTIFY_EVENTS = old_events
        common.NOTIFY_WEBHOOK_URL = old_webhook
        common.NOTIFY_DESKTOP_TOAST = old_desktop

    print("common notify helper checks passed")


if __name__ == "__main__":
    main()
