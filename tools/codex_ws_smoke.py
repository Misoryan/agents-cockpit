#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-destructive Codex WebSocket reconnect smoke test.

The probe connects directly to the local manager with internal auth, reads a
session replay, reconnects with `after=<lastSeq>`, and verifies that reconnect
does not replay already rendered events. It is intended for local validation
after replay/socket changes.
"""
import argparse
import base64
import http.client
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common  # noqa: E402


def _user_from_config(explicit=""):
    if explicit:
        return explicit
    return getattr(common, "_legacy_user", "") or next(iter(getattr(common, "USERS", {}) or {}), "")


def _headers(user):
    headers = {"Authorization": common.EXPECTED_AUTH}
    if user:
        headers["X-Agent-Cockpit-User"] = user
    return headers


def _api_json(path, user):
    conn = http.client.HTTPConnection(common.MANAGER_HOST, common.MANAGER_PORT, timeout=8)
    try:
        conn.request("GET", path, headers=_headers(user))
        res = conn.getresponse()
        data = res.read()
    finally:
        conn.close()
    if res.status >= 400:
        raise RuntimeError("GET %s -> %s %s" % (path, res.status, data[:400].decode("utf-8", "replace")))
    return json.loads(data.decode("utf-8", "replace"))


def _choose_session(sid, user):
    if sid:
        return sid
    data = _api_json("/api/sessions", user)
    for item in data.get("sessions") or []:
        if item.get("backend") == "codex_native" and item.get("sid"):
            return item["sid"]
    raise RuntimeError("no running codex_native session found; pass --sid or open/resume one first")


def _ws_connect(sid, user, after=0):
    sock = socket.create_connection((common.MANAGER_HOST, common.MANAGER_PORT), 8)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    path = "/t/%s/ws%s" % (sid, ("?after=%d" % int(after)) if after else "")
    req = [
        "GET %s HTTP/1.1" % path,
        "Host: %s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT),
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: %s" % key,
        "Sec-WebSocket-Version: 13",
        "Authorization: %s" % common.EXPECTED_AUTH,
    ]
    if user:
        req.append("X-Agent-Cockpit-User: %s" % user)
    req.extend(["", ""])
    sock.sendall("\r\n".join(req).encode("utf-8"))
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            break
        resp += chunk
    first = resp.split(b"\r\n", 1)[0].decode("latin1", "replace")
    if " 101 " not in first:
        sock.close()
        raise RuntimeError("websocket handshake failed: %s" % first)
    return sock


def _read_events(sock, seconds, max_events=40):
    out = []
    sock.settimeout(0.4)
    deadline = time.time() + float(seconds)
    while time.time() < deadline and len(out) < max_events:
        try:
            opcode, payload = common.ws_recv(sock)
        except socket.timeout:
            continue
        if opcode is None:
            break
        if opcode in (0x9, 0xA):
            continue
        try:
            out.append(json.loads(payload.decode("utf-8", "replace")))
        except Exception as exc:
            out.append({"type": "_bad_json", "error": str(exc)})
    return out


def _max_seq(events):
    max_seq = 0
    for event in events:
        for obj in [event] + list(event.get("events") or []):
            for key in ("seq", "last_seq", "merged_seq"):
                try:
                    max_seq = max(max_seq, int(obj.get(key) or 0))
                except Exception:
                    pass
    return max_seq


def _replay_event_count(events):
    return sum(len(event.get("events") or []) for event in events if event.get("type") == "replay_batch")


def probe(sid="", user="", seconds=2.5):
    user = _user_from_config(user)
    sid = _choose_session(sid, user)
    first = _ws_connect(sid, user, after=0)
    try:
        first_events = _read_events(first, seconds)
    finally:
        first.close()
    last_seq = _max_seq(first_events)
    second = _ws_connect(sid, user, after=last_seq)
    try:
        after_events = _read_events(second, seconds)
    finally:
        second.close()
    after_replay = _replay_event_count(after_events)
    return {
        "ok": after_replay == 0,
        "sid": sid,
        "user": user,
        "last_seq": last_seq,
        "first_types": [event.get("type") for event in first_events],
        "after_types": [event.get("type") for event in after_events],
        "first_replay_events": _replay_event_count(first_events),
        "after_replay_events": after_replay,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sid", default="", help="Running manager session id, e.g. s29. Defaults to first Codex session.")
    parser.add_argument("--user", default="", help="Auth user context. Defaults to first auth.txt user.")
    parser.add_argument("--seconds", type=float, default=2.5, help="Read window per websocket connection.")
    args = parser.parse_args(argv)
    result = probe(sid=args.sid, user=args.user, seconds=args.seconds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
