# -*- coding: utf-8 -*-
"""Read-only CC Switch provider, usage, and balance helpers."""
import http.client
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True)
class CCSwitchSettings:
    db: str
    usage_ttl: float = 15.0
    balance_ttl: float = 300.0


def toml_first(text, key):
    match = re.search(r'(?m)^[ \t]*%s[ \t]*=[ \t]*"([^"]+)"' % re.escape(key), text or "")
    return match.group(1) if match else None


def provider_meta(settings_config_json, app_type):
    """Parse one provider's settings_config into model/base_url/host/api_key."""
    try:
        settings_config = json.loads(settings_config_json) if settings_config_json else {}
    except ValueError:
        settings_config = {}
    if not isinstance(settings_config, dict):
        settings_config = {}
    env = settings_config.get("env") if isinstance(settings_config.get("env"), dict) else {}
    api_key = ""
    if app_type == "claude":
        model = env.get("ANTHROPIC_MODEL") or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL_NAME") or ""
        base_url = env.get("ANTHROPIC_BASE_URL") or ""
        api_key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY") or ""
    else:
        config_text = settings_config.get("config") or ""
        model = toml_first(config_text, "model") or ""
        base_url = toml_first(config_text, "base_url") or ""
        auth = settings_config.get("auth") if isinstance(settings_config.get("auth"), dict) else {}
        api_key = auth.get("OPENAI_API_KEY") or ""
    host = urllib.parse.urlparse(base_url).hostname if base_url else ""
    return {"model": model, "base_url": base_url, "host": host or "", "api_key": api_key}


def open_db(settings):
    uri = "file:%s?mode=ro" % settings.db.replace("\\", "/").replace("?", "")
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def day_start_epoch(now):
    local_time = time.localtime(now)
    return time.mktime(time.struct_time((local_time.tm_year, local_time.tm_mon, local_time.tm_mday,
                                         0, 0, 0, 0, 0, -1)))


def month_start_epoch(now):
    local_time = time.localtime(now)
    return time.mktime(time.struct_time((local_time.tm_year, local_time.tm_mon, 1,
                                         0, 0, 0, 0, 0, -1)))


def usage_window(cursor, since):
    row = cursor.execute(
        "SELECT COUNT(*) n, TOTAL(CAST(total_cost_usd AS REAL)) cost, "
        "TOTAL(input_tokens) it, TOTAL(output_tokens) ot, "
        "TOTAL(COALESCE(cache_read_tokens,0)+COALESCE(cache_creation_tokens,0)) ct "
        "FROM proxy_request_logs WHERE created_at>=? AND status_code<500", (since,)).fetchone()
    return {"requests": int(row["n"] or 0), "cost": round(float(row["cost"] or 0.0), 4),
            "input_tokens": int(row["it"] or 0), "output_tokens": int(row["ot"] or 0),
            "cache_tokens": int(row["ct"] or 0)}


def usage_by_model(cursor, since, limit=8):
    rows = cursor.execute(
        "SELECT model, COUNT(*) n, TOTAL(CAST(total_cost_usd AS REAL)) cost, "
        "TOTAL(input_tokens+output_tokens+COALESCE(cache_read_tokens,0)+COALESCE(cache_creation_tokens,0)) tok "
        "FROM proxy_request_logs WHERE created_at>=? AND status_code<500 "
        "GROUP BY model ORDER BY tok DESC LIMIT ?", (since, limit)).fetchall()
    return [{"model": row["model"] or "(unknown)", "requests": int(row["n"] or 0),
             "cost": round(float(row["cost"] or 0.0), 4), "tokens": int(row["tok"] or 0)} for row in rows]


_usage_cache = {"db": None, "ts": 0.0, "data": None}


def overview(settings):
    if not os.path.isfile(settings.db):
        return {"enabled": False}
    now = time.time()
    cached = _usage_cache["data"]
    if cached and _usage_cache["db"] == settings.db and now - _usage_cache["ts"] < settings.usage_ttl:
        out = dict(cached)
        out["cached"] = True
        return out
    try:
        conn = open_db(settings)
    except Exception as exc:
        return {"enabled": True, "error": "open db: %s" % exc, "providers": [], "usage": {}}
    try:
        cursor = conn.cursor()
        providers = []
        for row in cursor.execute("SELECT app_type,name,is_current,settings_config FROM providers "
                                  "ORDER BY is_current DESC, app_type"):
            meta = provider_meta(row["settings_config"], row["app_type"])
            providers.append({"app_type": row["app_type"], "name": row["name"],
                              "is_current": bool(row["is_current"]),
                              "model": meta["model"], "host": meta["host"]})
        day_start = day_start_epoch(now)
        usage = {"today": usage_window(cursor, day_start),
                 "month": usage_window(cursor, month_start_epoch(now)),
                 "by_model": usage_by_model(cursor, day_start),
                 "last_ts": int(cursor.execute("SELECT MAX(created_at) m FROM proxy_request_logs").fetchone()["m"] or 0)}
        out = {"enabled": True, "providers": providers, "usage": usage, "cached": False}
        _usage_cache.update(db=settings.db, data=out, ts=now)
        return dict(out)
    except Exception as exc:
        return {"enabled": True, "error": str(exc), "providers": [], "usage": {}}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def zhipu_api_base(host):
    host = (host or "").lower()
    if "bigmodel.cn" in host:
        return "https://open.bigmodel.cn"
    if "z.ai" in host:
        return "https://api.z.ai"
    return None


def current_zhipu(settings):
    """Return (api_key, host) for the current claude provider if Zhipu/Z.ai, else None."""
    try:
        conn = open_db(settings)
    except Exception:
        return None
    try:
        row = conn.execute(
            "SELECT settings_config FROM providers WHERE app_type='claude' AND is_current=1 LIMIT 1"
        ).fetchone()
        if not row:
            return None
        meta = provider_meta(row["settings_config"], "claude")
        if not meta["api_key"] or not meta["host"]:
            return None
        return (meta["api_key"], meta["host"])
    finally:
        try:
            conn.close()
        except Exception:
            pass


_balance_cache = {"db": None, "key": None, "host": None, "ts": 0.0, "data": None}
_balance_lock = threading.Lock()
_balance_refreshing = [False]


def balance_refresh(target_key, target_host, settings):
    out = None
    try:
        api_base = zhipu_api_base(target_host)
        if not api_base or not target_key:
            out = {"supported": False}
        else:
            host = api_base.split("://", 1)[1]
            conn = http.client.HTTPSConnection(host, timeout=6.0)
            conn.request("GET", "/api/monitor/usage/quota/limit", headers={
                "Authorization": target_key, "Accept-Language": "en-US,en",
                "Content-Type": "application/json"})
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            if resp.status != 200:
                raise RuntimeError("HTTP %d" % resp.status)
            obj = json.loads(body.decode("utf-8", "replace"))
            data = obj.get("data") or {}
            limits = data.get("limits") or []
            tok = next((item for item in limits if item.get("type") == "TOKENS_LIMIT"), None)
            if tok is None:
                raise RuntimeError("TOKENS_LIMIT not found in response")
            pct = float(tok.get("percentage") or 0)
            out = {"supported": True, "plan": str(data.get("level") or "ZHIPU").upper(),
                   "used_pct": round(pct, 1), "remaining_pct": round(max(0.0, 100.0 - pct), 1),
                   "reset_ms": tok.get("nextResetTime"), "fetched_at": time.time()}
    except Exception as exc:
        out = {"supported": True, "error": str(exc), "fetched_at": time.time()}
    with _balance_lock:
        _balance_cache.update(db=settings.db, key=target_key, host=target_host, data=out, ts=time.time())
        _balance_refreshing[0] = False


def balance(settings):
    """Non-blocking: returns cached quota or starts a background refresh when stale."""
    if not os.path.isfile(settings.db):
        return {"supported": False}
    info = current_zhipu(settings)
    if not info:
        return {"supported": False}
    key, host = info
    if not zhipu_api_base(host) or not key:
        return {"supported": False}
    now = time.time()
    with _balance_lock:
        cached = _balance_cache
        same = cached["db"] == settings.db and cached["key"] == key and cached["host"] == host
        if cached["data"] is not None and same and now - cached["ts"] < settings.balance_ttl:
            return dict(cached["data"])
        served = dict(cached["data"]) if cached["data"] is not None and same else None
        if not _balance_refreshing[0]:
            _balance_refreshing[0] = True
            threading.Thread(target=balance_refresh, args=(key, host, settings), daemon=True).start()
        return served if served is not None else {"supported": True, "pending": True}


def reset_caches():
    _usage_cache.update(db=None, ts=0.0, data=None)
    with _balance_lock:
        _balance_cache.update(db=None, key=None, host=None, ts=0.0, data=None)
        _balance_refreshing[0] = False
