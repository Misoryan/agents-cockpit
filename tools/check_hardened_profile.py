#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate config.ini against the recommended hardened deployment profile."""
import argparse
import configparser
import json
import os
import sys
from pathlib import Path


DEFAULTS = """
[server]
host = 0.0.0.0
use_https = 0
http_port = 0
[approval]
auto_approve = 1
[users]
allow_unconfigured_paths = 1
primary_user_uses_default_homes = 1
[security]
cookie_secure = 0
csrf_origin_check = 1
csrf_allow_missing_origin = 1
allowed_origins =
session_ttl = 86400
"""

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _bool(cfg, section, key):
    try:
        return cfg.getboolean(section, key)
    except (ValueError, configparser.Error):
        return None


def _int(cfg, section, key):
    try:
        return cfg.getint(section, key)
    except (ValueError, configparser.Error):
        return None


def load_config(path):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_string(DEFAULTS)
    if path and Path(path).is_file():
        cfg.read(path, encoding="utf-8")
    return cfg


def evaluate(cfg, behind_https_proxy=False, allow_public_bind=False, max_session_ttl=28800):
    checks = []

    def add(key, ok, message, severity="error", value=None):
        checks.append({
            "key": key,
            "ok": bool(ok),
            "severity": severity,
            "message": message,
            "value": value,
        })

    host = (cfg.get("server", "host", fallback="0.0.0.0") or "").strip().lower()
    add(
        "server.host",
        allow_public_bind or host in LOCAL_HOSTS,
        "Bind to localhost, or pass --allow-public-bind only when protected by firewall/VPN.",
        value=host,
    )

    use_https = _bool(cfg, "server", "use_https")
    add(
        "server.use_https",
        bool(use_https) or bool(behind_https_proxy),
        "Enable built-in HTTPS or pass --behind-https-proxy when TLS terminates before Agents Cockpit.",
        value=use_https,
    )

    http_port = _int(cfg, "server", "http_port")
    add(
        "server.http_port",
        int(http_port or 0) == 0,
        "Disable the extra plain HTTP listener in hardened deployments.",
        value=http_port,
    )

    auto_approve = _bool(cfg, "approval", "auto_approve")
    add(
        "approval.auto_approve",
        auto_approve is False,
        "Use web approval gates instead of auto-approving host actions.",
        value=auto_approve,
    )

    allow_paths = _bool(cfg, "users", "allow_unconfigured_paths")
    add(
        "users.allow_unconfigured_paths",
        allow_paths is False,
        "Restrict browsing/launches to configured workspace roots.",
        value=allow_paths,
    )

    default_homes = _bool(cfg, "users", "primary_user_uses_default_homes")
    add(
        "users.primary_user_uses_default_homes",
        default_homes is False,
        "Use per-user Codex/Claude homes for every login user.",
        value=default_homes,
    )

    cookie_secure = _bool(cfg, "security", "cookie_secure")
    add(
        "security.cookie_secure",
        cookie_secure is True,
        "Mark login cookies Secure when browser traffic uses HTTPS.",
        value=cookie_secure,
    )

    csrf_check = _bool(cfg, "security", "csrf_origin_check")
    add(
        "security.csrf_origin_check",
        csrf_check is True,
        "Keep Origin/Referer checks enabled for browser POST and WebSocket routes.",
        value=csrf_check,
    )

    allow_missing = _bool(cfg, "security", "csrf_allow_missing_origin")
    add(
        "security.csrf_allow_missing_origin",
        allow_missing is False,
        "Reject browser state changes that omit both Origin and Referer.",
        value=allow_missing,
    )

    ttl = _int(cfg, "security", "session_ttl")
    add(
        "security.session_ttl",
        ttl is not None and 0 < ttl <= int(max_session_ttl),
        "Use a bounded login session TTL no longer than %s seconds." % max_session_ttl,
        value=ttl,
    )

    failed = [item for item in checks if item["severity"] == "error" and not item["ok"]]
    return {
        "ok": not failed,
        "checks": checks,
        "failed": failed,
    }


def _print_text(result):
    print("Hardened profile: %s" % ("PASS" if result["ok"] else "FAIL"))
    for item in result["checks"]:
        mark = "OK" if item["ok"] else "FAIL"
        print("[%s] %s = %r - %s" % (mark, item["key"], item.get("value"), item["message"]))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.ini", help="Config file to check.")
    parser.add_argument("--behind-https-proxy", action="store_true",
                        help="Treat TLS termination before Agents Cockpit as satisfying HTTPS.")
    parser.add_argument("--allow-public-bind", action="store_true",
                        help="Do not fail server.host even if it is not localhost.")
    parser.add_argument("--max-session-ttl", type=int, default=28800)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    result = evaluate(
        cfg,
        behind_https_proxy=args.behind_https_proxy,
        allow_public_bind=args.allow_public_bind,
        max_session_ttl=args.max_session_ttl,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_text(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
