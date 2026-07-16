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
import threading
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


def _api_post_json(path, user, payload):
    body = json.dumps(payload or {}).encode("utf-8")
    headers = _headers(user)
    headers["Content-Type"] = "application/json"
    headers["Content-Length"] = str(len(body))
    conn = http.client.HTTPConnection(common.MANAGER_HOST, common.MANAGER_PORT, timeout=12)
    try:
        conn.request("POST", path, body=body, headers=headers)
        res = conn.getresponse()
        data = res.read()
    finally:
        conn.close()
    text = data.decode("utf-8", "replace")
    if res.status >= 400:
        raise RuntimeError("POST %s -> %s %s" % (path, res.status, text[:400]))
    return json.loads(text or "{}")


def _launch_temp_session(user, cwd):
    result = _api_post_json("/api/launch", user, {
        "dir": os.path.abspath(cwd or os.getcwd()),
        "title": "Codex WS smoke",
        "backend": "codex_native",
        "yolo": False,
    })
    if not result.get("sid"):
        raise RuntimeError("temporary Codex launch did not return sid: %s" % result)
    return result["sid"]


def _stop_session(user, sid):
    if not sid:
        return
    try:
        _api_post_json("/api/stop", user, {"sid": sid})
    except Exception as exc:
        print("WARN: failed to stop temporary session %s: %s" % (sid, exc), file=sys.stderr)


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


def _state_snapshot_count(events):
    return sum(1 for event in events if event.get("type") == "state_snapshot")


def _type_count(events, event_type):
    return sum(1 for event in events if event.get("type") == event_type)


def _read_client(label, sock, seconds, out):
    try:
        out[label] = _read_events(sock, seconds)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _read_many(sockets, seconds):
    out = {}
    threads = []
    for label, sock in sockets.items():
        t = threading.Thread(target=_read_client, args=(label, sock, seconds, out), daemon=True)
        t.start()
        threads.append(t)
    for thread in threads:
        thread.join(timeout=max(1.0, float(seconds) + 1.0))
    return out


def _read_many_with_action(sockets, seconds, action=None, action_delay=0.25):
    out = {}
    threads = []
    for label, sock in sockets.items():
        t = threading.Thread(target=_read_client, args=(label, sock, seconds, out), daemon=True)
        t.start()
        threads.append(t)
    if action is not None:
        time.sleep(max(0.0, float(action_delay)))
        action()
    for thread in threads:
        thread.join(timeout=max(1.0, float(seconds) + 1.0))
    return out


def _client_summary(events):
    return {
        "types": [event.get("type") for event in events],
        "last_seq": _max_seq(events),
        "replay_events": _replay_event_count(events),
        "state_snapshots": _state_snapshot_count(events),
        "mode_state_events": _type_count(events, "mode_state"),
    }


def _probe_single(sid, user, seconds):
    user = _user_from_config(user)
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


def _probe_two_clients(sid, user, seconds, exercise_live=False):
    first_sockets = {
        "primary": _ws_connect(sid, user, after=0),
        "mirror": _ws_connect(sid, user, after=0),
    }
    def live_action():
        _api_post_json("/api/nmode", user, {"sid": sid, "plan": True, "task": False})
    first = _read_many_with_action(
        first_sockets,
        seconds,
        action=live_action if exercise_live else None,
    )
    summaries = {label: _client_summary(events) for label, events in first.items()}
    seqs = {label: summary["last_seq"] for label, summary in summaries.items()}
    after_sockets = {
        label: _ws_connect(sid, user, after=seq)
        for label, seq in seqs.items()
    }
    after = _read_many(after_sockets, seconds)
    after_summaries = {label: _client_summary(events) for label, events in after.items()}
    after_replays = {label: summary["replay_events"] for label, summary in after_summaries.items()}
    seqs_match = len(set(seqs.values())) <= 1
    no_after_replay = all(count == 0 for count in after_replays.values())
    snapshots_seen = all(summary["state_snapshots"] >= 1 for summary in summaries.values())
    live_seen = all(summary["mode_state_events"] >= 1 for summary in summaries.values()) if exercise_live else True
    return {
        "ok": bool(seqs_match and no_after_replay and snapshots_seen and live_seen),
        "sid": sid,
        "user": user,
        "clients": 2,
        "live_broadcast_exercised": bool(exercise_live),
        "first": summaries,
        "after": after_summaries,
        "seqs_match": seqs_match,
        "after_replay_events": after_replays,
        "state_snapshots_seen": snapshots_seen,
        "live_broadcast_seen": live_seen,
    }


def probe(sid="", user="", seconds=2.5, clients=1, exercise_live=False):
    user = _user_from_config(user)
    sid = _choose_session(sid, user)
    if int(clients or 1) >= 2:
        return _probe_two_clients(sid, user, seconds, exercise_live=exercise_live)
    return _probe_single(sid, user, seconds)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sid", default="", help="Running manager session id, e.g. s29. Defaults to first Codex session.")
    parser.add_argument("--user", default="", help="Auth user context. Defaults to first auth.txt user.")
    parser.add_argument("--seconds", type=float, default=2.5, help="Read window per websocket connection.")
    parser.add_argument("--clients", type=int, choices=(1, 2), default=1,
                        help="Use 2 to verify two simultaneous clients get matching replay state.")
    parser.add_argument("--launch-temp", action="store_true",
                        help="Launch and stop a temporary idle Codex session when --sid is omitted.")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for --launch-temp.")
    parser.add_argument("--exercise-live", action="store_true",
                        help="During a two-client probe, broadcast a safe /api/nmode update and require both clients to see it.")
    args = parser.parse_args(argv)
    temp_sid = ""
    user = _user_from_config(args.user)
    try:
        if args.launch_temp and not args.sid:
            temp_sid = _launch_temp_session(user, args.cwd)
            args.sid = temp_sid
        exercise_live = bool(args.exercise_live or (args.launch_temp and args.clients >= 2))
        result = probe(sid=args.sid, user=user, seconds=args.seconds,
                       clients=args.clients, exercise_live=exercise_live)
        if temp_sid:
            result["temporary_session"] = temp_sid
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
    finally:
        if temp_sid:
            _stop_session(user, temp_sid)


if __name__ == "__main__":
    main()
