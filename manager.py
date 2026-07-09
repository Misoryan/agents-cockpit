# -*- coding: utf-8 -*-
"""
Agents Cockpit — manager process (the "codex/claude 端" supervisor).

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
import queue

import common
from common import BaseHandler, ThreadingServer
from hub import Hub
from native import NativeSession

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
            if s.get("backend") == "native":
                ns = s.get("native")
                if not ns or not ns.alive:
                    dead.append(sid)
                continue
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
    """Stop one session. Works for fresh (have Popen) and re-attached (pid only).
    Always tree-kills by pid: on Windows proc.terminate() only kills ttyd and
    leaves the codex/claude grandchildren orphaned, so we taskkill /F /T the pid
    regardless of branch and just use the Popen handle to reap the exit code."""
    with _lock:
        s = sessions.pop(sid, None)
    if not s:
        return False
    if s.get("backend") == "native":
        ns = s.get("native")
        if ns:
            try: ns.close()
            except Exception: pass
        common.registry_drop(sid)
        return True
    if s.get("hub"):
        try:
            s["hub"].close()
        except OSError:
            pass
    proc = s.get("proc")
    pid = s.get("pid") or (proc.pid if proc is not None else None)
    common._kill_pid(pid)   # taskkill /F /T (Win) / SIGTERM->SIGKILL tree (POSIX)
    if proc is not None:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
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
    hub = Hub(port, backend)
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


def launch_native(cwd, title="", auto_approve=False):
    """启动一个原生 agent 会话(不打 ttyd/PTY,直接打 Anthropic 兼容端点)。
    和终端会话并列,backend='native'。auto_approve=True 时 bash 跳过审批(等同 yolo)。v1 不支持 reattach。"""
    prune_dead()
    with _lock:
        _sid[0] += 1
        sid = "s%d" % _sid[0]
        ns = NativeSession(sid, cwd, yolo=bool(auto_approve))
        sessions[sid] = {
            "port": None, "proc": None, "pid": None, "dir": cwd, "backend": "native",
            "title": title or os.path.basename(cwd.rstrip(os.sep)) or cwd,
            "started": time.time(), "mode": "new", "session_id": None,
            "hub": None, "native": ns,
        }
        snap = dict(sessions[sid])
    common.registry_upsert(sid, common._registry_safe_entry(sid, snap))
    return sid


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
        if e.get("backend") == "native":
            ns = NativeSession.recover(sid, e.get("dir", ""))
            if ns:
                with _lock:
                    sessions[sid] = {"port": None, "proc": None, "pid": None,
                                     "dir": e.get("dir", ""), "backend": "native",
                                     "title": e.get("title", ""), "started": e.get("started", time.time()),
                                     "mode": e.get("mode", "new"), "session_id": None, "hub": None, "native": ns}
                live_sids.add(sid)
                try:
                    num = int(sid[1:]) if sid.startswith("s") and sid[1:].isdigit() else 0
                    if num > _sid[0]:
                        _sid[0] = num
                except Exception:
                    pass
            else:
                common.registry_drop(sid)
            continue
        if not port or not common._port_alive(port):
            common.registry_drop(sid)
            continue
        try:
            hub = Hub(port, e.get("backend", "codex"))   # reconnect upstream WS to the surviving ttyd
        except OSError:
            common.registry_drop(sid)
            continue
        hub.open_scrollback(sid)
        hub.ever_input = True   # a re-attachable session was already interacted with
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


# ---------- external push watcher (fires on state transitions) ----------
# Single watcher polls each hub's state every few seconds; a single sender drains the
# push queue so slow HTTP/DNS in one channel never stalls the next notification.
_notify_state = {}         # sid -> last observed state
_notify_pushed = {}        # sid -> {event: last_pushed_ts}
_notify_idle_since = {}    # sid -> ts it first became idle (None once a "done" fired)
_notify_q = queue.Queue()
_NOTIFY_INTERVAL = 4.0


def _notify_enqueue(title, body, event):
    _notify_q.put((title, body, event))


def _notify_sender():
    while True:
        try:
            title, body, event = _notify_q.get(timeout=60)
        except queue.Empty:
            continue
        try:
            common.push_notify(title, body, event)
        except Exception:
            pass
        finally:
            try:
                _notify_q.task_done()
            except ValueError:
                pass


def _session_label(s):
    be = common.BACKENDS.get(s.get("backend", "codex"), {}).get("label", "")
    return "%s · %s" % (be, s.get("title") or os.path.basename((s.get("dir") or "").rstrip("\\/")) or s.get("dir") or "")


def _notify_watcher():
    while True:
        time.sleep(_NOTIFY_INTERVAL)
        try:
            with _lock:
                snap = {sid: s for sid, s in sessions.items() if s.get("hub")}
            now = time.time()
            # drop state for sessions that disappeared
            for sid in [k for k in _notify_state if k not in snap]:
                _notify_state.pop(sid, None)
                _notify_pushed.pop(sid, None)
                _notify_idle_since.pop(sid, None)
            for sid, s in snap.items():
                try:
                    cur = s["hub"].state(now)
                except Exception:
                    continue
                prev = _notify_state.get(sid)
                idle_since = _notify_idle_since.get(sid)
                if prev is None:
                    # first observation after restart / new session: record silently
                    _notify_state[sid] = cur
                    _notify_idle_since[sid] = now if cur == "idle" else None
                    continue
                if cur == prev:
                    # unchanged; an idle that persists long enough matures into a "done"
                    if cur == "idle" and idle_since is not None and "done" in common.NOTIFY_EVENTS \
                            and (now - idle_since) >= common.IDLE_DEBOUNCE:
                        _notify_enqueue(_session_label(s) + " · 已完成",
                                        (s.get("dir") or "") + " — 等待下一条指令", "done")
                        _notify_idle_since[sid] = None   # fire once per idle stretch
                    continue
                # state transitioned
                if cur in ("confirm", "plan"):
                    ev = cur
                    if ev in common.NOTIFY_EVENTS and \
                            (now - _notify_pushed.get(sid, {}).get(ev, 0)) >= common.NOTIFY_MIN_INTERVAL:
                        head = "Plan 待确认" if cur == "plan" else "需要确认"
                        _notify_enqueue(_session_label(s) + " · " + head,
                                        (s.get("dir") or "") + " — 点击处理", ev)
                        _notify_pushed.setdefault(sid, {})[ev] = now
                    _notify_idle_since[sid] = None
                elif cur == "idle":
                    # just went idle: arm the debounce timer (push only if it persists)
                    _notify_idle_since[sid] = now
                else:
                    # running / new: cancel any pending idle completion
                    _notify_idle_since[sid] = None
                _notify_state[sid] = cur
        except Exception:
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
        if s.get("backend") == "native":
            ns = s.get("native")
            if rest == "ws":
                self._native_ws_handshake(ns)
            else:
                self._serve_native_page(sid, s)
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

    def _native_ws_handshake(self, ns):
        # 复用 ttyd 的 101 握手形状,但握手后把 socket 交给 NativeSession.add_client
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_response(400); self.send_header("Content-Length", "0"); self.end_headers(); return
        if not ns:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.close_connection = True
        self.send_response(101)
        self.send_header("Upgrade", "websocket"); self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", common.ws_accept_key(key))
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:
            pass
        ns.add_client(self.connection)

    def _serve_native_page(self, sid, s):
        body = ("<h3>原生会话: %s</h3><p>请在 <a href='/'>控制台</a> 中打开此会话。</p>"
                % s.get("title", sid)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

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
            yo = data.get("yolo")
            if backend in ("native", "claude"):
                try:
                    sid = launch_native(d, title=data.get("title") or "", auto_approve=bool(yo))
                except Exception as e:
                    self._json({"error": str(e)}, 500); return
                self._json({"ok": True, "sid": sid, "dir": d, "backend": "native", "term_path": "/t/%s/" % sid})
                return
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
        elif pr.path == "/api/nsend":
            sid = (data.get("sid") or "").strip()
            prompt = (data.get("prompt") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if (s and s.get("backend") == "native") else None
            if not ns:
                self._json({"error": "native session not found"}, 404); return
            if not prompt:
                self._json({"error": "missing prompt"}, 400); return
            ns.send(prompt)
            self._json({"ok": True})
        elif pr.path == "/api/napprove":
            sid = (data.get("sid") or "").strip()
            tuid = (data.get("tool_use_id") or "").strip()
            allow = bool(data.get("allow"))
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if (s and s.get("backend") == "native") else None
            if not ns:
                self._json({"error": "native session not found"}, 404); return
            ok = ns.approve(tuid, allow, data.get("message"))
            self._json({"ok": ok})
        elif pr.path == "/api/nanswer":
            sid = (data.get("sid") or "").strip()
            tuid = (data.get("tool_use_id") or "").strip()
            ans = data.get("answer") or ""
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if (s and s.get("backend") == "native") else None
            if not ns:
                self._json({"error": "native session not found"}, 404); return
            ok = ns.answer(tuid, ans)
            self._json({"ok": ok})
        elif pr.path == "/api/_perm_gate":
            # 网关(gate_mcp.py)调用:阻塞等网页审批。本地子进程 → _auth 自动放行,无需 token。
            sid = (data.get("sid") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if (s and s.get("backend") == "native") else None
            if not ns:
                self._json({"behavior": "deny", "message": "会话不存在"}, 404); return
            allow, msg = ns.await_permission(data.get("tool_use_id") or "",
                                             data.get("tool_name") or "",
                                             data.get("input") or {})
            if allow:
                self._json({"behavior": "allow", "updatedInput": data.get("input") or {}})
            else:
                self._json({"behavior": "deny", "message": msg or "用户拒绝"})
        elif pr.path == "/api/_ask_gate":
            sid = (data.get("sid") or "").strip()
            with _lock:
                s = sessions.get(sid)
            ns = s.get("native") if (s and s.get("backend") == "native") else None
            if not ns:
                self._json({"answer": "(会话不存在)"}, 404); return
            ans = ns.await_answer(data.get("tool_use_id") or "", data.get("question") or "")
            self._json({"answer": ans})
        elif pr.path == "/api/stop_all":
            kill_all(); self._json({"ok": True})
        elif pr.path == "/api/adapt":
            # 把 PTY 尺寸显式切到请求端(终端页"适配本屏"按钮)。不再随客户端进出/缩放自动变。
            sid = (data.get("sid") or "").strip()
            try:
                cols = int(data.get("cols") or 0); rows = int(data.get("rows") or 0)
            except (TypeError, ValueError):
                cols = rows = 0
            with _lock:
                s = sessions.get(sid); hub = s["hub"] if s else None
            if not s:
                self._json({"error": "session not found"}, 404); return
            ok = hub.adapt(cols, rows) if hub else False
            self._json({"ok": ok, "cols": hub.cols if hub else 0, "rows": hub.rows if hub else 0})
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


def _sigterm_die(*_a):
    """POSIX SIGTERM (e.g. start.sh's `kill 0` on the process group): reap every
    session tree then exit. Windows ignores this (the Job Object covers it)."""
    try:
        kill_all()
    except Exception:
        pass
    os._exit(0)


def run():
    print("Agents Cockpit manager: http://%s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT))
    reattach_sessions()
    atexit.register(kill_all)
    if os.name == "posix":
        import signal as _sig
        _sig.signal(_sig.SIGTERM, _sigterm_die)
    # 通知功能已停用:native 有 WS 实时 + 前端反馈,terminal 用户直接看终端输出
    # if common.NOTIFY_ENABLED:
    #     threading.Thread(target=_notify_sender, daemon=True).start()
    #     threading.Thread(target=_notify_watcher, daemon=True).start()
    try:
        try:
            _server[0] = ThreadingServer((common.MANAGER_HOST, common.MANAGER_PORT), ManagerHandler)
        except OSError as e:
            print("ERROR: manager 端口 %d 已被占用：%s" % (common.MANAGER_PORT, e))
            sys.exit(1)
        _server[0].serve_forever()
    except KeyboardInterrupt:
        kill_all(); print("manager bye")
