"""Check browser-facing Origin/CSRF helper behavior."""
import sys
from io import BytesIO
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import web  # noqa: E402


def _handler(headers=None, client=("203.0.113.10", 12345)):
    h = object.__new__(web.WebHandler)
    h.headers = headers or {}
    h.client_address = client
    return h


def _post_handler(path, headers=None):
    h = _handler(headers=headers)
    h.path = path
    h.rfile = BytesIO(b"{}")
    h.status = None
    h.body = None
    h.auth_called = 0
    h._json = lambda obj, code=200: (
        setattr(h, "status", code),
        setattr(h, "body", obj),
    )
    h._auth = lambda: (
        setattr(h, "auth_called", h.auth_called + 1) or True
    )
    return h


def main():
    old_check = common.CSRF_ORIGIN_CHECK
    old_allow_missing = common.CSRF_ALLOW_MISSING_ORIGIN
    old_allowed = list(common.CSRF_ALLOWED_ORIGINS)
    try:
        common.CSRF_ORIGIN_CHECK = True
        common.CSRF_ALLOW_MISSING_ORIGIN = False
        common.CSRF_ALLOWED_ORIGINS = []

        assert _handler({"Host": "app.test", "Origin": "https://app.test"})._origin_allowed()[0]
        assert not _handler({"Host": "app.test", "Origin": "https://evil.test"})._origin_allowed()[0]
        assert not _handler({"Host": "app.test"})._origin_allowed()[0]

        common.CSRF_ALLOW_MISSING_ORIGIN = True
        assert _handler({"Host": "app.test"})._origin_allowed()[0]

        common.CSRF_ALLOW_MISSING_ORIGIN = False
        common.CSRF_ALLOWED_ORIGINS = ["https://public.test"]
        assert _handler({"Host": "127.0.0.1:7891", "Origin": "https://public.test"})._origin_allowed()[0]

        assert _handler(
            {"Authorization": common.EXPECTED_AUTH, "Origin": "https://evil.test"},
            client=("127.0.0.1", 12345),
        )._origin_allowed() == (True, "internal auth")

        common.CSRF_ORIGIN_CHECK = False
        assert _handler({"Host": "app.test", "Origin": "https://evil.test"})._origin_allowed() == (True, "disabled")

        common.CSRF_ORIGIN_CHECK = True
        common.CSRF_ALLOW_MISSING_ORIGIN = False
        common.CSRF_ALLOWED_ORIGINS = []
        calls = []
        old_restart_web = web.restart_web_soon
        old_restart_manager = web.restart_manager_soon
        old_restart_server = web.restart_server_soon
        old_stop = web.stop_soon
        old_stopping = common.STOPPING
        try:
            web.restart_web_soon = lambda: calls.append("restart_web")
            web.restart_manager_soon = lambda: calls.append("restart_manager")
            web.restart_server_soon = lambda: calls.append("restart")
            web.stop_soon = lambda: calls.append("stop")
            for route in ("/api/restart_web", "/api/restart_manager", "/api/restart", "/api/_stop"):
                h = _post_handler(route, {"Host": "app.test", "Origin": "https://evil.test", "Content-Length": "2"})
                web.WebHandler.do_POST(h)
                assert h.status == 403
                assert h.body["error"] == "origin rejected"
                assert h.auth_called == 0
            assert calls == []
            assert common.STOPPING is old_stopping

            h = _post_handler(
                "/api/restart_manager",
                {"Host": "app.test", "Origin": "https://app.test", "Content-Length": "2"},
            )
            web.WebHandler.do_POST(h)
            assert h.status == 200
            assert h.body == {"ok": True, "restarting": True, "soft": True}
            assert h.auth_called == 1
            assert calls == ["restart_manager"]
        finally:
            web.restart_web_soon = old_restart_web
            web.restart_manager_soon = old_restart_manager
            web.restart_server_soon = old_restart_server
            web.stop_soon = old_stop
            common.STOPPING = old_stopping
    finally:
        common.CSRF_ORIGIN_CHECK = old_check
        common.CSRF_ALLOW_MISSING_ORIGIN = old_allow_missing
        common.CSRF_ALLOWED_ORIGINS = old_allowed

    print("web security helper checks passed")


if __name__ == "__main__":
    main()
