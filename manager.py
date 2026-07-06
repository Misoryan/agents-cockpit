# -*- coding: utf-8 -*-
"""
Agent Cockpit — manager process (the "codex/claude 端" supervisor).

Owns every ttyd+codex/claude child process and the in-memory session table.
This is the layer that survives a web-only restart, and (Phase B) can now be
SOFT-restarted itself without killing the CLI children: it persists the session
registry to disk, leaves the ttyd children orphaned-but-alive on os._exit, and
re-attaches to them on the next startup.
"""
import os
import sys
import json
import time
import atexit
import shlex
import socket
import subprocess
import threading
import urllib.parse

import common
from common import BaseHandler, ThreadingServer
from hub import Hub

# ---- manager-only state ----
sessions = {}        # sid -> {port, proc|None, pid, dir, title, started, mode, session_id, backend, hub}
_lock = threading.Lock()
_sid = [0]
_server = [None]
_reattached = False


# ---------- session lifecycle ----------
def alloc_port():
    with _lock:
        used = {s["port"] for s in sessions.values()}
    for off in range(0, 300):
        port = common.PORT_BASE + off
        if port in common.PORT_SKIP or port in used:
            continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port)); s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("no free port")


def prune_dead():
    """Drop sessions whose ttyd/CLI died. Fresh sessions: proc.poll(). Re-attached
    sessions (proc=None): detect via the hub's upstream reader having exited."""
    dead = []
    with _lock:
        for sid, s in sessions.items():
            proc = s.get("proc")
            hub = s.get("hub")
            if proc is not None:
                if proc.poll() is not None:
                    dead.append(sid)
            elif hub is not None and not hub.alive:
                dead.append(sid)
        for sid in dead:
            s = sessions.pop(sid, None)
            if s and s.get("hub"):
                try:
                    s["hub"].close()
                except OSError:
                    pass
    for sid in dead:
        common.registry_drop(sid)


def kill_session(sid):
    """Stop one session. Works for fresh (have Popen) and re-attached (pid only)."""
    with _lock:
        s = sessions.pop(sid, None)
    if not s:
        return False
    if s.get("hub"):
        try:
            s["hub"].close()
        except OSError:
            pass
    proc = s.get("proc")
    if proc is not None:
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
    else:
        common._kill_pid(s.get("pid"))
    common.registry_drop(sid)
    return True


def kill_all():
    with _lock:
        sids = list(sessions.keys())
    for sid in sids:
        kill_session(sid)


def launch(cwd, backend="codex", cli_args=None, title="", mode="new", session_id=None,
           auto_approve=None, extra_args=None):
    prune_dead()
    bconf = common.BACKENDS.get(backend) or common.BACKENDS["codex"]
    bin_path = bconf["bin"]
    if not bin_path or not os.path.isfile(bin_path):
        raise RuntimeError("%s 未找到(请用 npm 装 @openai/codex 或安装 claude,或设 CODEX_BIN/CLAUDE_BIN)" % bconf["label"])
    if auto_approve is None:
        auto_approve = common.AUTO_APPROVE
    yolo = list(bconf["yolo"]) if auto_approve else []
    display_args = ["--no-alt-screen"] if backend == "codex" and common.CODEX_NO_ALT_SCREEN else []
    extra = shlex.split(extra_args) if extra_args else []
    port = alloc_port()
    # ttyd: localhost-only, writable. Persistent (hub keeps the CLI alive).
    cmd = [common.TTYD, "-p", str(port), "-W", "-w", cwd, "-i", common.BIND_IFACE, bin_path] + yolo + display_args + extra + (cli_args or [])
    proc = subprocess.Popen(cmd, creationflags=common.CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    common.wait_port(port)
    hub = Hub(port)
    with _lock:
        _sid[0] += 1
        sid = "s%d" % _sid[0]
        sessions[sid] = {
            "port": port, "proc": proc, "pid": proc.pid, "dir": cwd, "backend": backend,
            "title": title or os.path.basename(cwd.rstrip("\\/")) or cwd,
            "started": time.time(), "mode": mode, "session_id": session_id, "hub": hub,
        }
        snap = dict(sessions[sid])
    hub.open_scrollback(sid)
    common.registry_upsert(sid, common._registry_safe_entry(sid, snap))
    return sid, port


# ---------- re-attach on startup (Phase B) ----------
def reattach_sessions():
    """Before serve_forever: load the registry, probe each session's ttyd port,
    reconnect an upstream Hub to surviving ttys, replay scrollback, and re-seed
    the sid counter / used-ports. Idempotent (guarded by _reattached)."""
    global _reattached
    if _reattached:
        return
    _reattached = True
    try:
        os.makedirs(common.STATE_DIR, exist_ok=True)
        os.makedirs(common.SCROLLBACK_DIR, exist_ok=True)
    except OSError:
        pass
    reg = common.registry_load()
    sess = reg.get("sessions") if isinstance(reg, dict) else None
    if not isinstance(sess, dict) or not sess:
        return
    live_sids = set()
    for sid, e in sess.items():
        port = e.get("port")
        pid = e.get("pid")
        if not port or not common._port_alive(port):
            common.registry_drop(sid)
            continue
        try:
            hub = Hub(port)   # reconnect upstream WS to the surviving ttyd
        except OSError:
            common.registry_drop(sid)
            continue
        hub.open_scrollback(sid)
        for fr in common.read_scrollback(sid):   # restore scrollback for late-joining browsers
            hub.replay_frame(fr)
        hub.cols = e.get("cols") or 0
        hub.rows = e.get("rows") or 0
        try:
            num = int(sid[1:]) if sid.startswith("s") and sid[1:].isdigit() else 0
            if num > _sid[0]:
                _sid[0] = num
        except Exception:
            pass
        with _lock:
            sessions[sid] = {
                "port": port, "proc": None, "pid": pid, "dir": e.get("dir", ""),
                "backend": e.get("backend", "codex"), "title": e.get("title", ""),
                "started": e.get("started", time.time()), "mode": e.get("mode", "new"),
                "session_id": e.get("session_id"), "hub": hub,
            }
        live_sids.add(sid)
    # drop orphan scrollback files for sids no longer live
    try:
        for fn in os.listdir(common.SCROLLBACK_DIR):
            if fn.endswith(".log") and fn[:-4] not in live_sids:
                try:
                    os.unlink(os.path.join(common.SCROLLBACK_DIR, fn))
                except OSError:
                    pass
    except OSError:
        pass


# ---------- HTTP handler (manager mode) ----------
class ManagerHandler(BaseHandler):
    def _auth(self):
        if common._is_local_client(self.client_address):
            return True
        if self.headers.get("Authorization", "") == common.EXPECTED_AUTH:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="agent-cockpit"')
        self.send_header("Content-Length", "12"); self.end_headers()
        self.wfile.write(b"auth required")
        return False

    def _serve_terminal(self, sid, rest):
        with _lock:
            s = sessions.get(sid)
            hub = s["hub"] if s else None
            port = s["port"] if s else None
        if not s:
            body = ("<h3>该会话不存在或已停止。</h3><p>回到 <a href='/'>控制台</a>。</p>").encode("utf-8")
            self.send_response(404); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if rest == "ws":
            self._ws_handshake(hub)
        else:
            try:
                html = common.fetch_ttyd_html(port)
            except OSError:
                self.send_response(502); self.send_header("Content-Length", "0"); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html))); self.end_headers(); self.wfile.write(html)

    def _ws_handshake(self, hub):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_response(400); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.close_connection = True
        self.send_response(101)
        self.send_header("Upgrade", "websocket"); self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", common.ws_accept_key(key))
        if "tty" in (self.headers.get("Sec-WebSocket-Protocol") or ""):
            self.send_header("Sec-WebSocket-Protocol", "tty")
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:
            pass
        hub.add_client(self.connection)

    def do_GET(self):
        if not self._auth():
            return
        pr = urllib.parse.urlparse(self.path)
        path = pr.path
        if path.startswith("/t/"):
            parts = path.split("/")
            if len(parts) >= 3 and parts[1] == "t":
                sid = parts[2]
                rest = "/".join(parts[3:])
                return self._serve_terminal(sid, rest)
            self._json({"error": "bad terminal path"}, 404); return
        if path in ("/", "/index.html"):
            self._serve_index(); return
        if path == "/api/browse":
            q = urllib.parse.parse_qs(pr.query); self._json(common.browse(q.get("path", [""])[0]))
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
            self._json({"backends": [k for k, v in common.BACKENDS.items() if v["bin"] and os.path.isfile(v["bin"])],
                        "labels": {k: v["label"] for k, v in common.BACKENDS.items()}})
        elif path == "/api/cc_usage":
            out = common.ccswitch_overview()
            if out.get("enabled"):
                out["balance"] = common.ccswitch_balance()
            self._json(out)
        else:
            self._json({"error": "not found"}, 404)

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
                self._json({"error": "invalid directory: %r" % d}, 400); return
            backend = (data.get("backend") or "codex").strip()
            if backend not in common.BACKENDS:
                backend = "codex"
            yo = data.get("yolo")
            auto_approve = common.AUTO_APPROVE if yo is None else bool(yo)
            extra = (data.get("args") or "").strip()
            try:
                sid, _ = launch(d, backend=backend, title=data.get("title") or "",
                                auto_approve=auto_approve, extra_args=extra)
            except Exception as e:
                self._json({"error": str(e)}, 500); return
            self._json({"ok": True, "sid": sid, "dir": d, "backend": backend, "term_path": "/t/%s/" % sid})
        elif pr.path == "/api/resume":
            sid_arg = (data.get("session_id") or "").strip()
            d = (data.get("dir") or "").strip().strip('"')
            if not sid_arg:
                self._json({"error": "missing session_id"}, 400); return
            if not d or not os.path.isdir(d):
                d = d or os.path.expanduser("~")
            backend = (data.get("backend") or "codex").strip()
            if backend not in common.BACKENDS:
                backend = "codex"
            # codex: 'codex resume <id>'  ;  claude: 'claude --resume <id>'
            cli_args = ["--resume", sid_arg] if backend == "claude" else ["resume", sid_arg]
            try:
                sid, _ = launch(d, backend=backend, cli_args=cli_args,
                                title=data.get("title") or "恢复会话", mode="resume", session_id=sid_arg)
            except Exception as e:
                self._json({"error": str(e)}, 500); return
            self._json({"ok": True, "sid": sid, "dir": d, "backend": backend, "term_path": "/t/%s/" % sid})
        elif pr.path == "/api/stop":
            self._json({"ok": kill_session((data.get("sid") or "").strip())})
        elif pr.path == "/api/stop_all":
            kill_all(); self._json({"ok": True})
        elif pr.path == "/api/_exit":
            # 完全重启:杀掉全部会话后退出 manager;web 层的 ensure_manager 会用新代码重新拉起。
            def _die():
                time.sleep(0.25)   # 让响应先发回
                kill_all()
                os._exit(0)
            threading.Thread(target=_die, daemon=True).start()
            self._json({"ok": True, "restarting": True})
        elif pr.path == "/api/_soft_exit":
            # 软重启:把会话注册表写盘后退出,但【不】杀子进程。ttyd+codex 成孤儿但存活,
            # 下个 manager 启动时 reattach_sessions() 会按注册表重连。
            def _soft_die():
                time.sleep(0.25)
                try:
                    with _lock:
                        snap = {sid: dict(s) for sid, s in sessions.items()}
                    entries = {sid: common._registry_safe_entry(sid, s) for sid, s in snap.items()}
                    common.registry_save(entries)
                except Exception:
                    pass
                os._exit(0)   # DO NOT kill_all — children must survive
            threading.Thread(target=_soft_die, daemon=True).start()
            self._json({"ok": True, "restarting": True, "soft": True})
        else:
            self._json({"error": "not found"}, 404)


def run():
    print("Agent Cockpit manager: http://%s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT))
    reattach_sessions()
    atexit.register(kill_all)
    try:
        try:
            _server[0] = ThreadingServer((common.MANAGER_HOST, common.MANAGER_PORT), ManagerHandler)
        except OSError as e:
            print("ERROR: manager 端口 %d 已被占用：%s" % (common.MANAGER_PORT, e))
            sys.exit(1)
        _server[0].serve_forever()
    except KeyboardInterrupt:
        kill_all(); print("manager bye")
