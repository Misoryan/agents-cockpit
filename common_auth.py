# -*- coding: utf-8 -*-
"""Authentication primitives shared by the web and manager processes."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

_INTERNAL_AUTH_CONTEXT = b"agent-cockpit-manager-internal-v1"


def load_users(auth_file):
    """Load auth.txt as {user: credential}, returning (users, first_user)."""
    users = {}
    legacy_user = None
    try:
        with open(auth_file, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                user, password = line.split(":", 1)
                user = user.strip()
                users[user] = password
                if legacy_user is None:
                    legacy_user = user
    except OSError:
        pass
    return users, legacy_user


def expected_basic_auth(legacy_user, users):
    cred = ("%s:%s" % (legacy_user, users.get(legacy_user, ""))) if legacy_user else ":"
    return "Basic " + base64.b64encode(cred.encode()).decode()


def hash_password(password, iters=120000):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return "$pbkdf2$%d$%s$%s" % (iters, base64.b64encode(salt).decode(),
                                 base64.b64encode(dk).decode())


def verify_password(password, stored):
    if not stored or not password:
        return False
    if stored.startswith("$pbkdf2$"):
        parts = stored.split("$")
        if len(parts) != 5:
            return False
        try:
            iters = int(parts[2])
            salt = base64.b64decode(parts[3])
            want = base64.b64decode(parts[4])
        except Exception:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, want)
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))


def load_or_create_session_secret(state_dir):
    path = os.path.join(state_dir, "session_secret")
    try:
        with open(path, "r", encoding="utf-8") as f:
            secret = f.read().strip()
        if secret:
            return secret
    except OSError:
        pass
    try:
        os.makedirs(state_dir, exist_ok=True)
        secret = secrets.token_hex(32)
        with open(path, "w", encoding="utf-8") as f:
            f.write(secret)
        return secret
    except OSError:
        return ""


def _secret_bytes(session_secret):
    if isinstance(session_secret, bytes):
        return session_secret
    return str(session_secret or "").encode("utf-8")


def internal_auth(session_secret):
    return "Bearer " + hmac.new(_secret_bytes(session_secret), _INTERNAL_AUTH_CONTEXT, hashlib.sha256).hexdigest()


def verify_internal_auth(header, expected_auth):
    return bool(header) and hmac.compare_digest(str(header), expected_auth)


def make_session_token(user, session_secret, ttl):
    payload = {"u": user, "exp": int(time.time()) + int(ttl)}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(body).decode("ascii")
    sig = hmac.new(_secret_bytes(session_secret), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return payload_b64 + "." + sig


def verify_session_token(token, session_secret, users, now=None):
    if not token or "." not in token:
        return None
    payload_b64, _, sig = token.partition(".")
    expect = hmac.new(_secret_bytes(session_secret), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
        exp = int(payload.get("exp", 0))
    except Exception:
        return None
    if exp < (time.time() if now is None else now):
        return None
    user = payload.get("u")
    return user if (isinstance(user, str) and user in users) else None


def session_cookie_header(name, value, max_age, secure=False):
    parts = ["%s=%s" % (name, value), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % int(max_age)]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
