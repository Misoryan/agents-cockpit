"""Check internal manager/gate auth stays separate from browser cookies."""
import json
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import manager  # noqa: E402
from native import NativeSession  # noqa: E402


class _Sink:
    def write(self, _data):
        return None


class _FakeHandler:
    def __init__(self, auth):
        self.headers = {"Authorization": auth} if auth else {}
        self.client_address = ("127.0.0.1", 12345)
        self.wfile = _Sink()
        self.status = None

    def send_response(self, code):
        self.status = code

    def send_header(self, *_args):
        return None

    def end_headers(self):
        return None


def _auth_ok(header):
    h = _FakeHandler(header)
    return manager.ManagerHandler._auth(h), h.status


def main():
    assert common.verify_internal_auth(common.INTERNAL_AUTH)
    assert not common.verify_internal_auth("")
    assert not common.verify_internal_auth("Bearer wrong")

    ok, status = _auth_ok("")
    assert not ok and status == 401
    ok, status = _auth_ok(common.EXPECTED_AUTH)
    assert ok and status is None
    ok, status = _auth_ok(common.INTERNAL_AUTH)
    assert ok and status is None

    with tempfile.TemporaryDirectory() as td:
        ns = NativeSession("s-gate", ".", user="alice", state_dir=td)
        ns._write_mcp_config()
        data = json.loads(Path(ns._mcp_config_path()).read_text(encoding="utf-8"))
        cfg = data["mcpServers"]["cockpit"]
        assert cfg["args"][1] == "s-gate"
        assert cfg["args"][3] == "alice"
        assert cfg["args"][4] == common.INTERNAL_AUTH
        assert cfg["env"]["AGENT_COCKPIT_USER"] == "alice"
        assert cfg["env"]["AGENT_COCKPIT_INTERNAL_AUTH"] == common.INTERNAL_AUTH

    print("internal gate auth checks passed")


if __name__ == "__main__":
    main()
