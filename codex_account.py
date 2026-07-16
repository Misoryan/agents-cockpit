# -*- coding: utf-8 -*-
"""Read-only Codex account, rate-limit, and usage helpers."""
import json
import time

import codex_config
import codex_text


ACCOUNT_MODES = {"": "full", "full": "full", "basic": "basic", "account": "basic"}
SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "credential",
    "cookie",
    "authorization",
    "authheader",
)


def _words(arg):
    return str(arg or "").strip().split()


def _text(value, limit=360):
    value = str(value or "").strip()
    if limit and len(value) > limit:
        return value[:limit - 1].rstrip() + "..."
    return value


def mask_email(email):
    email = _text(email, 180)
    at = email.find("@")
    if at <= 1:
        return email
    return email[:1] + "***" + email[max(1, at - 1):]


def _safe_error(exc):
    text = str(exc or "").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            text = obj.get("message") or obj.get("error") or text
    except Exception:
        pass
    return _text(text.replace("\r", " ").replace("\n", " "), 500)


def _safe_value(value, depth=0):
    if depth > 5:
        return _text(value, 200)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = _text(key, 120)
            lower = key_text.lower().replace("_", "").replace("-", "")
            if any(part in lower for part in SENSITIVE_KEY_PARTS):
                continue
            if lower == "email":
                out[key_text] = mask_email(item)
            else:
                out[key_text] = _safe_value(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in list(value)[:80]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _text(value, 500)


def _safe_request(session, method, params=None, timeout=20):
    try:
        return {"ok": True, "data": session._client().request(method, params or {}, timeout=timeout) or {}}
    except Exception as exc:
        return {"ok": False, "error": _safe_error(exc)}


def account_summary(response):
    summary = codex_config.account_status(response if isinstance(response, dict) else {})
    if summary.get("email"):
        summary["email"] = mask_email(summary.get("email"))
    return summary


def account_payload(account_response, rate_response=None, usage_response=None):
    payload = {
        "account": account_summary(account_response),
        "rateLimits": {},
        "usage": {},
        "errors": [],
    }
    for label, response in (("rateLimits", rate_response), ("usage", usage_response)):
        if not response:
            continue
        if response.get("ok"):
            payload[label] = _safe_value(response.get("data") or {})
        else:
            payload["errors"].append({"method": label, "error": response.get("error") or "request failed"})
    return payload


def _emit_result(session, call_id, name, input_obj, result, method):
    if hasattr(session, "_mcp_result_events"):
        session._mcp_result_events(call_id, name, input_obj, result, method)
        return True
    if not hasattr(session, "_record_and_broadcast"):
        return False
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": input_obj or {}}]},
    })
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": call_id,
            "content": codex_text.compact_json(result or {}, 5000),
        }]},
    })
    return True


def account_notice(payload):
    account = payload.get("account") or {}
    if account.get("signed_in"):
        who = account.get("email") or account.get("type") or "signed in"
    elif account.get("requires_openai_auth"):
        who = "login required"
    else:
        who = "not signed in"
    errors = len(payload.get("errors") or [])
    suffix = ", %d read errors" % errors if errors else ""
    return "Codex account: %s%s" % (who, suffix)


def account_status(session, arg):
    words = _words(arg)
    if len(words) > 1:
        return {"ok": False, "error": "usage: /account-status [basic|full]"}
    mode = ACCOUNT_MODES.get(words[0].lower() if words else "")
    if not mode:
        return {"ok": False, "error": "usage: /account-status [basic|full]"}
    account = _safe_request(session, "account/read", {"refreshToken": False}, timeout=10)
    account_data = account.get("data") if account.get("ok") else {}
    payload = account_payload(account_data)
    if not account.get("ok"):
        payload["errors"].append({"method": "account/read", "error": account.get("error")})
    if mode == "full":
        rate = _safe_request(session, "account/rateLimits/read", {}, timeout=20)
        usage = _safe_request(session, "account/usage/read", {}, timeout=20)
        payload = account_payload(account_data, rate_response=rate, usage_response=usage)
        if not account.get("ok"):
            payload["errors"].insert(0, {"method": "account/read", "error": account.get("error")})
    payload["mode"] = mode
    _emit_result(
        session,
        "codex-account-%d" % int(time.time() * 1000),
        "codex.accountStatus",
        {"mode": mode},
        payload,
        "account/status",
    )
    session._codex_notice(account_notice(payload), "account/status", payload)
    return {
        "ok": True,
        "command": "account-status",
        "mode": mode,
        "signed_in": bool((payload.get("account") or {}).get("signed_in")),
        "errors": len(payload.get("errors") or []),
    }
