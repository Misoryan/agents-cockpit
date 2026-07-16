# -*- coding: utf-8 -*-
"""Manager process for web-rendered agent sessions.

The manager owns in-memory NativeSession objects and exposes the HTTP/WebSocket
API consumed by the browser. Every launch/resume opens the structured web UI.
"""
import os
import sys
import json
import atexit
import threading
import urllib.parse
import hmac

import common
import manager_internal_api
import manager_sessions
import manager_user_api
from common import BaseHandler, ThreadingServer

# Session state and lifecycle live in manager_sessions; these aliases preserve
# the public names used by tests and older helper code.
sessions = manager_sessions.sessions
_lock = manager_sessions.lock
_sid = manager_sessions.sid_counter
_server = [None]

_INTERNAL_GATE_POSTS = manager_internal_api.INTERNAL_GATE_POSTS
_INTERNAL_CONTROL_POSTS = manager_internal_api.INTERNAL_CONTROL_POSTS


def _sid_num(sid):
    return manager_sessions.sid_num(sid)


def _state_sid_taken(sid, state_dir):
    return manager_sessions.state_sid_taken(sid, state_dir)


def _seed_sid_from_state_dir(state_dir):
    return manager_sessions.seed_sid_from_state_dir(state_dir)


def prune_dead():
    return manager_sessions.prune_dead()


def kill_session(sid):
    return manager_sessions.kill_session(sid)


def kill_all():
    return manager_sessions.kill_all()


def persist_sessions():
    return manager_sessions.persist_sessions()


def idle_sweaper(interval=60, ttl=1800):
    return manager_sessions.idle_sweaper(interval=interval, ttl=ttl)


def _session_title(cwd, title):
    return manager_sessions.session_title(cwd, title)


def _backend_available(backend):
    return manager_sessions.backend_available(backend)


def launch_native(cwd, title="", auto_approve=None, mode="new", session_id=None,
                  events=None, backend=None, ctx=None, codex_config=None):
    return manager_sessions.launch_native(cwd, title=title, auto_approve=auto_approve, mode=mode,
                                          session_id=session_id, events=events, backend=backend, ctx=ctx,
                                          codex_config=codex_config)


def reattach_sessions():
    return manager_sessions.reattach_sessions()


def _reattach_one(ctx, sid, e):
    return manager_sessions.reattach_one(ctx, sid, e)


# ---------- HTTP handler ----------
class ManagerHandler(BaseHandler):
    def _auth(self):
        auth = self.headers.get("Authorization", "")
        if common.verify_internal_auth(auth):
            return True
        if hmac.compare_digest(auth, common.EXPECTED_AUTH):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="agent-cockpit"')
        self.send_header("Content-Length", "12")
        self.end_headers()
        self.wfile.write(b"auth required")
        return False

    def _ctx(self, required=True):
        user = common.request_user(self)
        ctx = common.user_context(user) if user else None
        if required and not ctx:
            self._json({"error": "missing user context"}, 401)
        return ctx

    def _owned_session(self, sid, ctx):
        return manager_sessions.owned_session(sid, ctx)

    def _post_context(self, path):
        return manager_internal_api.post_context(self, path)

    def _native_from_payload(self, data, ctx):
        return manager_internal_api.native_from_payload(data, ctx, self._owned_session)

    def _handle_internal_gate(self, path, data, ctx):
        return manager_internal_api.handle_gate(self, path, data, ctx, self._native_from_payload)

    def _handle_internal_control(self, path):
        return manager_internal_api.handle_control(self, path, kill_all, persist_sessions)

    def _serve_session(self, sid, rest):
        ctx = self._ctx(required=True)
        if not ctx:
            return
        s = self._owned_session(sid, ctx)
        if not s:
            body = ("<h3>Session not found or already stopped.</h3><p>Return to <a href='/'>console</a>.</p>").encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        ns = s.get("native")
        if rest == "ws":
            self._native_ws_handshake(ns)
        else:
            self._serve_native_page(sid, s)

    def _native_ws_handshake(self, ns):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_response(400)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not ns:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.close_connection = True
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", common.ws_accept_key(key))
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:
            pass
        try:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            after_seq = int(q.get("after", ["0"])[0] or 0)
        except Exception:
            after_seq = 0
        try:
            ns.add_client(self.connection, after_seq=after_seq)
        except TypeError:
            ns.add_client(self.connection)

    def _serve_native_page(self, sid, s):
        body = ("<h3>Agent session: %s</h3><p>Open it from the <a href='/'>console</a>.</p>"
                % s.get("title", sid)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_user_get(self, path, pr, ctx):
        return manager_user_api.handle_get(self, path, pr, ctx, self._owned_session)

    def do_GET(self):
        if not self._auth():
            return
        pr = urllib.parse.urlparse(self.path)
        path = pr.path
        if path.startswith("/t/"):
            parts = path.split("/")
            if len(parts) >= 3 and parts[1] == "t":
                return self._serve_session(parts[2], "/".join(parts[3:]))
            self._json({"error": "bad session path"}, 404)
            return
        if path in ("/", "/index.html"):
            self._serve_index()
            return
        if path.startswith(self.static_url_prefix):
            self._serve_static(path)
            return
        ctx = self._ctx(required=True)
        if not ctx:
            return
        self._handle_user_get(path, pr, ctx)

    def _resume_native(self, data, ctx):
        return manager_user_api.resume_native(self, data, ctx, launch_native)

    def _handle_user_post(self, path, data, ctx):
        return manager_user_api.handle_post(
            self, path, data, ctx, self._native_from_payload, self._owned_session,
            launch_native, kill_session)

    def do_POST(self):
        if not self._auth():
            return
        pr = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            data = {}
        ctx = self._post_context(pr.path)
        if pr.path not in _INTERNAL_CONTROL_POSTS and pr.path not in _INTERNAL_GATE_POSTS and not ctx:
            return
        if self._handle_internal_control(pr.path):
            return
        if self._handle_internal_gate(pr.path, data, ctx):
            return
        self._handle_user_post(pr.path, data, ctx)

def _sigterm_die(*_a):
    try:
        kill_all()
    except Exception:
        pass
    os._exit(0)


def run():
    print("Agents Cockpit manager: http://%s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT))
    reattach_sessions()
    threading.Thread(target=idle_sweaper, daemon=True).start()
    atexit.register(persist_sessions)
    if os.name == "posix":
        import signal as _sig
        _sig.signal(_sig.SIGTERM, _sigterm_die)
    try:
        try:
            _server[0] = ThreadingServer((common.MANAGER_HOST, common.MANAGER_PORT), ManagerHandler)
        except OSError as e:
            print("ERROR: manager port %d is already in use: %s" % (common.MANAGER_PORT, e))
            sys.exit(1)
        _server[0].serve_forever()
    except KeyboardInterrupt:
        kill_all()
        print("manager bye")
