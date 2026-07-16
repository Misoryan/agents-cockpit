"""Check read-only Codex account status helpers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_account  # noqa: E402


class FakeClient:
    def __init__(self, fail_usage=False):
        self.fail_usage = fail_usage
        self.calls = []

    def request(self, method, params, timeout=None):
        self.calls.append((method, params, timeout))
        if method == "account/read":
            return {
                "requiresOpenaiAuth": False,
                "account": {
                    "type": "chatgpt",
                    "email": "person@example.com",
                    "planType": "pro",
                    "credentialSource": "codex-cli",
                    "accessToken": "secret",
                },
            }
        if method == "account/rateLimits/read":
            if self.fail_usage:
                raise RuntimeError('{"code":-32600,"message":"auth required"}')
            return {"primary": {"used": 1, "limit": 10, "token": "redacted"}}
        if method == "account/usage/read":
            if self.fail_usage:
                raise RuntimeError("codex account authentication required to read token usage")
            return {"window": "month", "inputTokens": 100, "secret": "hidden"}
        return {}


class FakeSession:
    def __init__(self, fail_usage=False):
        self.client = FakeClient(fail_usage=fail_usage)
        self.results = []
        self.notices = []

    def _client(self):
        return self.client

    def _mcp_result_events(self, call_id, name, input_obj, result, method):
        self.results.append((call_id, name, input_obj, result, method))

    def _codex_notice(self, message, method=None, params=None, level=None, silent=False):
        self.notices.append((message, method, params, silent))


def main():
    assert codex_account.mask_email("person@example.com") == "p***n@example.com"
    summary = codex_account.account_summary({
        "requiresOpenaiAuth": False,
        "account": {"type": "chatgpt", "email": "person@example.com", "planType": "pro"},
    })
    assert summary["email"] == "p***n@example.com"
    assert summary["signed_in"] is True

    session = FakeSession()
    result = codex_account.account_status(session, "")
    assert result == {"ok": True, "command": "account-status", "mode": "full", "signed_in": True, "errors": 0}
    assert [call[0] for call in session.client.calls] == [
        "account/read",
        "account/rateLimits/read",
        "account/usage/read",
    ]
    payload = session.results[-1][3]
    assert payload["account"]["email"] == "p***n@example.com"
    assert "accessToken" not in payload["account"]
    assert "token" not in payload["rateLimits"]["primary"]
    assert "secret" not in payload["usage"]
    assert session.results[-1][1] == "codex.accountStatus"

    basic = FakeSession()
    basic_result = codex_account.account_status(basic, "basic")
    assert basic_result["mode"] == "basic"
    assert [call[0] for call in basic.client.calls] == ["account/read"]

    failing = FakeSession(fail_usage=True)
    fail_result = codex_account.account_status(failing, "full")
    assert fail_result["errors"] == 2
    assert "auth required" in failing.results[-1][3]["errors"][0]["error"]
    assert codex_account.account_status(failing, "bad")["ok"] is False

    print("codex account helper checks passed")


if __name__ == "__main__":
    main()
