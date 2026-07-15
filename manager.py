# -*- coding: utf-8 -*-
"""Manager process for web-rendered agent sessions.

The manager owns in-memory NativeSession objects and exposes the HTTP/WebSocket
API consumed by the browser. Every launch/resume opens the structured web UI.
"""
import os
import sys
import json
import time
import atexit
import threading
import urllib.parse

import common
from common import BaseHandler, ThreadingServer
from native import NativeSession
from codex_native import CodexSession, get_app_client, shutdown_app_server

# sid -> {dir, title, started, mode, session_id, backend, provider, native}
sessions = {}
_lock = threading.Lock()
_sid = [0]
_server = [None]
_reattached = False


def _sid_num(sid):
    try:
        return int(sid[1:]) if sid.startswith("s") and sid[1:].isdigit() else 0
    except Exception:
        return 0


# ---------- session lifecycle ----------
def prune_dead():
    dead = []
    with _lock:
        for sid, s in sessions.items():
            ns = s.get("native")
            if not ns or not ns.alive:
                dead.append(sid)
        for sid in dead:
            sessions.pop(sid, None)
    for sid in dead:
        common.registry_drop(sid)


def kill_session(sid):
    with _lock:
        s = sessions.pop(sid, None)
    if not s:
        return False
    ns = s.get("native")
    if ns:
        try:
            ns.close()
        except Exception:
            pass
    common.registry_drop(sid)
    return True


def kill_all():
    with _lock:
        sids = list(sessions.keys())
    for sid in sids:
        kill_session(sid)
    try:
        shutdown_app_server()
    except Exception:
        pass


def idle_sweaper(interval=60, ttl=1800):
    """后台回收:清理 claude 路线中无人查看、未在生成、未在等审批、且超过 ttl 秒未活动的 NativeSession。
    只释放内存与 registry,历史文件保留(可恢复)。codex 常驻 app-client 架构排除。"""
    while True:
        try:
            time.sleep(interval)
            now = time.time()
            to_kill = []
            with _lock:
                for sid, s in list(sessions.items()):
                    if common.is_codex_backend(s.get("backend", "")):
                        continue
                    ns = s.get("native")
                    if not ns or getattr(ns, "_closed", False) or not getattr(ns, "alive", False):
                        continue
                    if getattr(ns, "clients", None):
                        continue
                    proc = getattr(ns, "_proc", None)
                    if proc is not None and proc.poll() is None:
                        continue
                    if getattr(ns, "_pending", None):
                        continue
                    if now - float(getattr(ns, "last_activity", 0) or 0) > ttl:
                        to_kill.append(sid)
            for sid in to_kill:
                try:
                    kill_session(sid)
                except Exception:
                    pass
        except Exception:
            pass

def _session_title(cwd, title):
    return title or os.path.basename(cwd.rstrip(os.sep)) or cwd


def _backend_available(backend):
    backend = common.normalize_backend(backend)
    return backend in common.BACKENDS


def launch_native(cwd, title="", auto_approve=None, mode="new", session_id=None,
                  events=None, backend=None):
    """Create one web-rendered agent session."""
    backend = common.normalize_backend(backend)
    if backend == "claude_native":
        if not common.CLAUDE_BIN or not os.path.isfile(common.CLAUDE_BIN):
            raise RuntimeError("Claude CLI was not found. Install claude or set [binaries] claude in config.ini.")
        provider = "claude"
        cls = NativeSession
    elif backend == "codex_native":
        if not common.CODEX_BIN or not os.path.isfile(common.CODEX_BIN):
            raise RuntimeError("Codex CLI was not found. Install codex or set [binaries] codex in config.ini.")
        provider = "codex"
        cls = CodexSession
    else:
        raise RuntimeError("unsupported backend: %s" % backend)
    prune_dead()
    if auto_approve is None:
        auto_approve = common.AUTO_APPROVE
    with _lock:
        _sid[0] += 1
        sid = "s%d" % _sid[0]
        ns = cls(sid, cwd, yolo=bool(auto_approve))
        if provider == "claude" and session_id:
            ns.claude_sid = session_id
        elif provider == "codex" and session_id:
            ns.thread_id = session_id
        if events:
            ns.events = list(events)
        if provider == "codex" and not session_id:
            ns.start()
        elif provider == "codex" and getattr(ns, "thread_id", None):
            get_app_client().register(ns.thread_id, ns)
        sessions[sid] = {
            "dir": cwd,
            "backend": backend,
            "provider": provider,
            "title": _session_title(cwd, title),
            "started": time.time(),
            "mode": mode,
            "session_id": session_id,
            "thread_id": getattr(ns, "thread_id", None),
            "native": ns,
        }
        snap = dict(sessions[sid])
    common.registry_upsert(sid, common._registry_safe_entry(sid, snap))
    return sid


# ---------- re-attach on startup ----------
def reattach_sessions():
    """Recover persisted native sessions after a manager restart.

    Older registry entries without recoverable structured session state are
    dropped instead of reattached.
    """
    global _reattached
    if _reattached:
        return
    _reattached = True
    try:
        os.makedirs(common.STATE_DIR, exist_ok=True)
    except OSError:
        pass
    reg = common.registry_load()
    sess = reg.get("sessions") if isinstance(reg, dict) else None
    if not isinstance(sess, dict) or not sess:
        return
    for sid, e in list(sess.items()):
        if not isinstance(e, dict):
            common.registry_drop(sid)
            continue
        backend = common.normalize_backend(e.get("backend") or ("codex_native" if e.get("provider") == "codex" else "claude_native"))
        provider = "codex" if common.is_codex_backend(backend) else "claude"
        if provider == "codex":
            ns = CodexSession.recover(sid, e.get("dir", ""), e.get("thread_id") or e.get("session_id"))
        else:
            ns = NativeSession.recover(sid, e.get("dir", ""))
        if not ns:
            common.registry_drop(sid)
            continue
        if "yolo" in e:
            try:
                ns.yolo = bool(e.get("yolo"))
            except Exception:
                pass
        with _lock:
            sessions[sid] = {
                "dir": e.get("dir", getattr(ns, "cwd", "")),
                "backend": backend,
                "provider": provider,
                "title": e.get("title", ""),
                "started": e.get("started", time.time()),
                "mode": e.get("mode", "new"),
                "session_id": e.get("session_id") or getattr(ns, "claude_sid", None) or getattr(ns, "thread_id", None),
                "thread_id": e.get("thread_id") or getattr(ns, "thread_id", None),
                "native": ns,
            }
            _sid[0] = max(_sid[0], _sid_num(sid))


# ---------- HTTP handler ----------
class ManagerHandler(BaseHandler):
    def _auth(self):
        if common._is_local_client(self.client_address):
            return True
        if self.headers.get("Authorization", "") == common.EXPECTED_AUTH:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="agent-cockpit"')
        self.send_header("Content-Length", "12")
        self.end_headers()
        self.wfile.write(b"auth required")
        return False

    def _serve_session(self, sid, rest):
        with _lock:
            s = sessions.get(sid)
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
        ns.add_client(self.connection)

    def _serve_native_page(self, sid, s):
        body = ("<h3>Agent session: %s</h3><p>Open it from the <a href='/'>console</a>.</p>"
                % s.get("title", sid)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        if path == "/api/browse":
            q = urllib.parse.parse_qs(pr.query)
            self._json(common.browse(q.get("path", [""])[0]))
        elif path == "/api/sessions":
            prune_dead()
            with _lock:
                items = [common.session_obj(sid, s, self.headers.get("Host", "")) for sid, s in sessions.items()]
            items.sort(key=lambda x: x["started"], reverse=True)
            self._json({"sessions": items})
        elif path == "/api/history":
            q = urllib.parse.parse_qs(pr.query)
            self._json({"history": common.load_history(int(q.get("limit", ["60"])[0] or 60))})
        elif path == "/api/recent_dirs":
            q = urllib.parse.parse_qs(pr.query)
            self._json({"dirs": common.recent_dirs(int(q.get("limit", ["30"])[0] or 30))})
        elif path == "/api/backends":
            self._json({"backends": list(common.BACKENDS.keys()),
                        "labels": {k: v.get("label", k) for k, v in common.BACKENDS.items()}})
        elif path == "/api/cc_usage":
            out = common.ccswitch_overview()
            if out.get("enabled"):
                out["balance"] = common.ccswitch_balance()
            self._json(out)
        else:
            self._json({"error": "not found"}, 404)

    def _resume_native(self, data):
        sid_arg = (data.get("session_id") or "").strip()
        d = (data.get("dir") or "").strip().strip('"')
        backend = common.normalize_backend(data.get("backend"))
        if not sid_arg:
            self._json({"error": "missing session_id"}, 400)
            return
        evs = []
        title = data.get("title") or "Resume"
        if common.is_codex_backend(backend):
            try:
                snap = CodexSession.history_snapshot(sid_arg)
                evs = snap.get("events") or []
                if snap.get("cwd") and not os.path.isdir(d):
                    d = snap.get("cwd")
                if snap.get("title") and not data.get("title"):
                    title = snap.get("title")
            except Exception as e:
                evs = [{"type": "codex_notice", "message": "Codex history read failed: %s" % e}]
        if not d or not os.path.isdir(d):
            d = d or os.path.expanduser("~")
        if not common.is_codex_backend(backend):
            evs = common.load_claude_transcript_events(sid_arg)
        auto_approve = common.AUTO_APPROVE if data.get("yolo") is None else bool(data.get("yolo"))
        try:
            sid = launch_native(d, title=title,
                                auto_approve=auto_approve, mode="resume",
                                session_id=sid_arg, events=evs, backend=backend)
        except Exception as e:
            self._json({"error": str(e)}, 500)
            return
        self._json({"ok": True, "sid": sid, "dir": d, "backend": backend,
                    "yolo": auto_approve, "session_path": "/t/%s/" % sid})

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
        if pr.path == "/api/launch":
            d = (data.get("dir") or "").strip().strip('"')
            if not d or not os.path.isdir(d):
                self._json({"error": "invalid directory: %r" % d}, 400)
                return
            auto_approve = common.AUTO_APPROVE if data.get("yolo") is None else bool(data.get("yolo"))
            backend = common.normalize_backend(data.get("backend"))
            try:
                sid = launch_native(d, title=data.get("title") or "", auto_approve=auto_approve, backend=backend)
            except Exception as e:
                self._json({"error": str(e)}, 500)
                return
            self._json({"ok": True, "sid": sid, "dir": d, "backend": backend,
                        "yolo": auto_approve, "session_path": "/t/%s/" % sid})
        elif pr.path in ("/api/resume", "/api/nresume"):
            self._resume_native(data)
        elif pr.path == "/api/stop":
            self._json({"ok": kill_session((data.get("sid") or "").strip())})
        elif pr.path == "/api/ninterrupt":
            # 打断当前轮但保留会话(区别于 /api/stop 杀整个会话)。ns.interrupt 仅 kill 子进程。
            sid = (data.get("sid") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"error": "native session not found"}, 404)
                return
            self._json({"ok": ns.interrupt()})
        elif pr.path == "/api/nsend":
            sid = (data.get("sid") or "").strip()
            prompt = (data.get("prompt") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"error": "native session not found"}, 404)
                return
            if not prompt:
                self._json({"error": "missing prompt"}, 400)
                return
            # 每轮发送都带上当前计划/任务模式(后端重启后会丢,以此重同步),保证 argv 用对 permission-mode
            if "plan" in data:
                ns.plan_mode = bool(data["plan"])
            if "task" in data:
                ns.task_mode = bool(data["task"])
            ns.send(prompt)
            self._json({"ok": True})
        elif pr.path == "/api/nmode":
            sid = (data.get("sid") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"error": "native session not found"}, 404)
                return
            ns.set_modes(data.get("plan"), data.get("task"))
            self._json({"ok": True, "plan": ns.plan_mode, "task": ns.task_mode})
        elif pr.path == "/api/napprove":
            sid = (data.get("sid") or "").strip()
            tuid = (data.get("tool_use_id") or "").strip()
            allow = bool(data.get("allow"))
            always = bool(data.get("always"))
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"error": "native session not found"}, 404)
                return
            self._json({"ok": ns.approve(tuid, allow, data.get("message"), always)})
        elif pr.path == "/api/nanswer":
            sid = (data.get("sid") or "").strip()
            tuid = (data.get("tool_use_id") or "").strip()
            ans = data.get("answers") if "answers" in data else (data.get("answer") or "")
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"error": "native session not found"}, 404)
                return
            self._json({"ok": ns.answer(tuid, ans)})
        elif pr.path == "/api/_perm_gate":
            sid = (data.get("sid") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"behavior": "deny", "message": "session not found"}, 404)
                return
            allow, msg = ns.await_permission(data.get("tool_use_id") or "",
                                             data.get("tool_name") or "",
                                             data.get("input") or {})
            if allow:
                self._json({"behavior": "allow", "updatedInput": data.get("input") or {}})
            else:
                self._json({"behavior": "deny", "message": msg or "user denied"})
        elif pr.path == "/api/_ask_gate":
            sid = (data.get("sid") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if s else None
            if not ns:
                self._json({"answer": "(session not found)"}, 404)
                return
            ans = ns.await_answer(data.get("tool_use_id") or "", data.get("question") or "", data.get("questions"))
            self._json({"answer": ans})
        elif pr.path == "/api/stop_all":
            kill_all()
            self._json({"ok": True})
        elif pr.path == "/api/_exit":
            def _die():
                time.sleep(0.25)
                kill_all()
                os._exit(0)
            threading.Thread(target=_die, daemon=True).start()
            self._json({"ok": True, "restarting": True})
        elif pr.path == "/api/_soft_exit":
            def _soft_die():
                time.sleep(0.25)
                try:
                    with _lock:
                        snap = {sid: dict(s) for sid, s in sessions.items()}
                    entries = {sid: common._registry_safe_entry(sid, s) for sid, s in snap.items()}
                    common.registry_save(entries)
                except Exception:
                    pass
                os._exit(0)
            threading.Thread(target=_soft_die, daemon=True).start()
            self._json({"ok": True, "restarting": True, "soft": True})
        elif pr.path == "/api/history_delete":
            sid = (data.get("sid") or "").strip()
            try:
                r = common.delete_history(sid, data.get("backend"))
            except Exception as e:
                self._json({"error": str(e)}, 500)
                return
            self._json({"ok": r["deleted"], "deleted": r["deleted"]})
        else:
            self._json({"error": "not found"}, 404)


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
    atexit.register(kill_all)
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
