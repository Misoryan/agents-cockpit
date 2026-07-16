"""Check browser-facing Origin/CSRF helper behavior."""
import sys
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
    finally:
        common.CSRF_ORIGIN_CHECK = old_check
        common.CSRF_ALLOW_MISSING_ORIGIN = old_allow_missing
        common.CSRF_ALLOWED_ORIGINS = old_allowed

    print("web security helper checks passed")


if __name__ == "__main__":
    main()
