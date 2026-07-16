"""Check auth helpers after extracting them from common.py."""
import base64
import json
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_auth  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        auth_file = Path(td, "auth.txt")
        auth_file.write_text("# comment\nalice:secret\nbob:$pbkdf2$bad\n", encoding="utf-8")
        users, legacy = common_auth.load_users(str(auth_file))
        assert users["alice"] == "secret"
        assert legacy == "alice"
        want = "Basic " + base64.b64encode(b"alice:secret").decode()
        assert common_auth.expected_basic_auth(legacy, users) == want

        hashed = common_auth.hash_password("pw", iters=1000)
        assert common_auth.verify_password("pw", hashed)
        assert not common_auth.verify_password("bad", hashed)
        assert common_auth.verify_password("secret", "secret")

        secret = common_auth.load_or_create_session_secret(td)
        assert secret
        assert common_auth.load_or_create_session_secret(td) == secret

        internal = common_auth.internal_auth(secret)
        assert common_auth.verify_internal_auth(internal, internal)
        assert not common_auth.verify_internal_auth("Bearer wrong", internal)

        tok = common_auth.make_session_token("alice", secret, ttl=60)
        assert common_auth.verify_session_token(tok, secret, users) == "alice"
        assert common_auth.verify_session_token(tok, "other", users) is None
        assert common_auth.verify_session_token(tok, secret, {"bob": "pw"}) is None
        expired_body = base64.urlsafe_b64encode(json.dumps({"u": "alice", "exp": 1}).encode()).decode("ascii")
        assert common_auth.verify_session_token(expired_body + ".bad", secret, users) is None

        cookie = common_auth.session_cookie_header("ac_session", "tok", 5, secure=True)
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie
        assert "Secure" in cookie

        assert common_auth.normalize_origin("https://Example.COM:443/path") == "https://example.com"
        assert common_auth.normalize_origin("http://example.com:80/") == "http://example.com"
        assert common_auth.split_allowed_origins("https://a.test, https://b.test;http://c.test") == [
            "https://a.test", "https://b.test", "http://c.test"
        ]
        headers = {"Host": "app.example.test", "Origin": "https://app.example.test"}
        assert common_auth.request_origin_allowed(headers) == (True, "same origin")
        headers = {"Host": "app.example.test", "Referer": "https://app.example.test/x"}
        assert common_auth.request_origin_allowed(headers) == (True, "same origin")
        headers = {"Host": "internal.local", "Origin": "https://public.example.test"}
        assert common_auth.request_origin_allowed(headers, ["https://public.example.test"]) == (True, "same origin")
        headers = {"Host": "app.example.test", "Origin": "https://evil.example.test"}
        assert common_auth.request_origin_allowed(headers)[0] is False
        assert common_auth.request_origin_allowed({"Host": "app.example.test"}, allow_missing=True)[0] is True
        assert common_auth.request_origin_allowed({"Host": "app.example.test"}, allow_missing=False)[0] is False

    old_users = common.USERS
    try:
        common.USERS = {"alice": "secret"}
        tok = common.make_session_token("alice")
        assert common.verify_session_token(tok) == "alice"
        assert common.verify_internal_auth(common.INTERNAL_AUTH)
        assert common.session_cookie_header("x", "y", max_age=1).startswith("x=y;")
        assert common.codex_dynamic_tool_mappings() == {}
        assert common.request_origin_allowed({"Host": "example.test", "Origin": "https://example.test"})[0]
    finally:
        common.USERS = old_users

    print("common auth helper checks passed")


if __name__ == "__main__":
    main()
