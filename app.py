# -*- coding: utf-8 -*-
"""
Codex-Web: phone-friendly launcher for codex with SHARED, multi-device terminals.

  console + embedded terminals : http://<lan-ip>:7682   (basic-auth)

Shared-session model:
  - Each session = ONE persistent ttyd+codex (localhost, --yolo).
  - app.py keeps ONE upstream websocket to that ttyd (keeps codex alive) and
    multiplexes many browsers (PC + phone) onto it: broadcasts codex output to
    all clients, forwards any client's input to codex, and replays buffered
    output to clients joining mid-task. So PC and phone see the SAME codex live
    and both can type — and can switch between multiple such sessions smoothly.

Stdlib only. Reuses E:\\tools\\ttyd\\ttyd.exe and the cr_-configured codex.exe.
"""
import http.server
import socketserver
import json
import os
import subprocess
import threading
import urllib.parse
import base64
import sys
import atexit
import time
import socket
import select
import http.client
import hashlib
import re
import shlex
import signal
from datetime import datetime

# ---- config (all overridable via env) ----
HOST = "0.0.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
PICKER_PORT = int(os.environ.get("CODEX_WEB_PORT", "7682"))
PORT_BASE = int(os.environ.get("CODEX_PORT_BASE", str(PICKER_PORT + 1)))
PORT_SKIP = {PICKER_PORT}
INDEX = os.path.join(HERE, "index.html")
SW_FILE = os.path.join(HERE, "sw.js")
AUTH_FILE = os.environ.get("AUTH_FILE") or os.path.join(HERE, "auth.txt")
BIND_IFACE = os.environ.get("CODEX_BIND", "127.0.0.1")  # ttyd loopback iface (Windows: 127.0.0.1)
CREATE_NO_WINDOW = 0x08000000
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BUF_CAP = 262144  # max replay buffer per session (~256KB)
# auto-approve: codex --yolo / claude --dangerously-skip-permissions. CODEX_YOLO=0 to disable.
AUTO_APPROVE = os.environ.get("CODEX_YOLO", "1") not in ("0", "", "false", "no")
CODEX_NO_ALT_SCREEN = os.environ.get("CODEX_NO_ALT_SCREEN", "1") not in ("0", "", "false", "no")
LOG_TEXT_CAP = int(os.environ.get("CODEX_LOG_TEXT_CAP", str(BUF_CAP)))
RUN_MODE = "manager" if "--manager" in sys.argv else "web"
MANAGER_HOST = "127.0.0.1"
MANAGER_PORT = int(os.environ.get("CODEX_MANAGER_PORT", str(PICKER_PORT + 1000)))

CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
SESSIONS_DIR = os.path.join(CODEX_HOME, "sessions")
HISTORY_JSONL = os.path.join(CODEX_HOME, "history.jsonl")


def _find_codex_under(root):
    want = "codex.exe" if os.name == "nt" else "codex"
    if not os.path.isdir(root):
        return None
    for dp, _d, fs in os.walk(root):
        if dp.endswith(os.sep + "bin") and want in fs:
            return os.path.join(dp, want)
    return None


def resolve_codex_bin():
    p = os.environ.get("CODEX_BIN")
    if p and os.path.isfile(p):
        return p
    # locate the codex launcher on PATH, derive the npm global prefix from it
    try:
        cmd = "where codex" if os.name == "nt" else "command -v codex"
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=10).decode(errors="replace")
        for line in out.splitlines():
            shim = line.strip()
            if not shim:
                continue
            prefix = os.path.dirname(os.path.abspath(shim))
            for nm in (os.path.join(prefix, "node_modules"), os.path.join(os.path.dirname(prefix), "node_modules")):
                found = _find_codex_under(os.path.join(nm, "@openai"))
                if found:
                    return found
    except Exception:
        pass
    # fallback: npm global root
    try:
        out = subprocess.check_output("npm root -g", shell=True, stderr=subprocess.DEVNULL, timeout=10).decode(errors="replace").strip()
        if out:
            found = _find_codex_under(os.path.join(out, "@openai"))
            if found:
                return found
    except Exception:
        pass
    return None


def resolve_ttyd():
    p = os.environ.get("TTYD")
    if p and os.path.isfile(p):
        return p
    for c in (os.path.join(HERE, "ttyd.exe"), os.path.join(HERE, "ttyd")):
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ttyd")


def resolve_claude_bin():
    p = os.environ.get("CLAUDE_BIN")
    if p and os.path.isfile(p):
        return p
    try:
        cmd = "where claude" if os.name == "nt" else "command -v claude"
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=10).decode(errors="replace")
        for line in out.splitlines():
            shim = line.strip()
            if shim and os.path.isfile(shim):
                return shim
    except Exception:
        pass
    return None


CODEX_BIN = resolve_codex_bin()
CLAUDE_BIN = resolve_claude_bin()
TTYD = resolve_ttyd()

BACKENDS = {
    "codex": {"bin": CODEX_BIN, "yolo": ["--yolo"], "label": "Codex"},
    "claude": {"bin": CLAUDE_BIN, "yolo": ["--dangerously-skip-permissions"], "label": "Claude Code"},
}

if not (CODEX_BIN or CLAUDE_BIN):
    print("ERROR: 未找到 codex 或 claude。请至少安装一个 CLI。")
    sys.exit(1)
if not TTYD or not os.path.isfile(TTYD):
    print("ERROR: 未找到 ttyd。请把 ttyd(.exe) 放在本目录,或设置 TTYD 环境变量。")
    sys.exit(1)

with open(AUTH_FILE, "r", encoding="utf-8") as f:
    CRED = f.read().strip()
if ":" not in CRED:
    print("ERROR: bad .auth (need user:pass)"); sys.exit(1)
EXPECTED_AUTH = "Basic " + base64.b64encode(CRED.encode()).decode()

sessions = {}      # sid -> {port, proc, dir, title, started, mode, session_id, hub}
_lock = threading.Lock()
_sid = [0]
_server = [None]


def _is_local_client(addr):
    host = addr[0] if addr else ""
    return host in ("127.0.0.1", "::1", "localhost")


def _manager_path():
    return sys.argv[0] if sys.argv and sys.argv[0] else __file__


def _manager_argv():
    args = [a for a in sys.argv[1:] if a != "--manager"]
    return [sys.executable, os.path.abspath(_manager_path()), "--manager"] + args


def manager_available():
    try:
        conn = http.client.HTTPConnection(MANAGER_HOST, MANAGER_PORT, timeout=0.8)
        conn.request("GET", "/api/backends")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        if not (200 <= resp.status < 500):
            return False
        # Old managers may answer /api/backends but not support the log API.
        conn = http.client.HTTPConnection(MANAGER_HOST, MANAGER_PORT, timeout=0.8)
        conn.request("GET", "/api/log?sid=__healthcheck__")
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", "replace")
        conn.close()
        return resp.status == 404 and "session not found" in data
    except OSError:
        return False


def ensure_manager():
    if RUN_MODE == "manager" or manager_available():
        return True
    subprocess.Popen(_manager_argv(), cwd=HERE, creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 8
    while time.time() < deadline:
        if manager_available():
            return True
        time.sleep(0.2)
    return False


def restart_web_soon():
    def _restart():
        time.sleep(0.35)
        srv = _server[0]
        if srv:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_restart, daemon=True).start()


# ---------- websocket frame helpers (RFC 6455, minimal) ----------
def _recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        c = sock.recv(n - len(data))
        if not c:
            raise OSError("socket closed")
        data += c
    return bytes(data)


def ws_recv(sock):
    """Read one ws message; transparently answers ping. Returns (opcode, payload) or (None,None)."""
    while True:
        hdr = _recv_exact(sock, 2)
        b1, b2 = hdr[0], hdr[1]
        op = b1 & 0x0f
        masked = b2 & 0x80
        ln = b2 & 0x7f
        if ln == 126:
            ln = int.from_bytes(_recv_exact(sock, 2), "big")
        elif ln == 127:
            ln = int.from_bytes(_recv_exact(sock, 8), "big")
        mask = _recv_exact(sock, 4) if masked else b""
        payload = _recv_exact(sock, ln) if ln else b""
        if masked:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
        if op == 0x9:  # ping -> pong
            ws_send(sock, payload, 0xA); continue
        if op == 0xA:  # pong
            continue
        return op, payload


def ws_send(sock, payload, opcode=0x2, mask=False):
    out = bytearray([0x80 | opcode])
    ln = len(payload)
    mflag = 0x80 if mask else 0x00
    if ln < 126:
        out.append(mflag | ln)
    elif ln < 65536:
        out.append(mflag | 126); out += ln.to_bytes(2, "big")
    else:
        out.append(mflag | 127); out += ln.to_bytes(8, "big")
    if mask:
        m = os.urandom(4); out += m
        payload = bytes(payload[i] ^ m[i % 4] for i in range(len(payload)))
    out += payload
    sock.sendall(bytes(out))


def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


# ---------- hub: one persistent codex, many browser clients ----------
_CONFIRM_RE = re.compile(rb"(?i)(\bapprove\b|\ballow\b|\bconfirm\b|\[y/?n\]|\(yes/no\)|\(y/n\)|\byes/no\b)")
_ANSI_RE = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_backspaces(text):
    out = []
    for ch in text:
        if ch == "\b":
            if out:
                out.pop()
        else:
            out.append(ch)
    return "".join(out)


def _payload_to_plain_text(payload):
    if not payload:
        return ""
    # ttyd prefixes stdout frames with "0"; other prefixes are control/input frames.
    if payload[:1] == b"0":
        data = payload[1:]
    elif payload[:1] in (b"1", b"2", b"3", b"4", b"5"):
        return ""
    else:
        data = payload
    text = data.decode("utf-8", "replace")
    text = _ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_backspaces(text)
    return _CTRL_RE.sub("", text)


class Hub:
    def __init__(self, ttyd_port):
        self.ttyd_port = ttyd_port
        self.clients = set()       # browser raw sockets
        self.frames = []           # buffered output payloads (ttyd "0"+data), for replay
        self.frames_size = 0
        self.frames_dropped = False
        self.upstream = None       # raw socket to ttyd
        self.clock = threading.Lock()
        self.started = time.time()
        self.last_output_ts = time.time()
        self.last_input_ts = time.time()
        self.awaiting_confirm = False
        self.confirm_ts = 0.0
        self.cols = 0
        self.rows = 0
        self.client_sizes = {}   # client_id -> (cols, rows)
        self._connect_upstream()

    def apply_resize(self, client_id, cols, rows):
        # shrink-to-min: codex takes the SMALLEST size among connected clients,
        # so every device's xterm grid is >= codex size -> no garble anywhere
        # (bigger screens just show the smaller terminal with side margins).
        try:
            cols = int(cols); rows = int(rows)
        except (TypeError, ValueError):
            return
        if cols <= 0 or rows <= 0:
            return
        with self.clock:
            self.client_sizes[client_id] = (cols, rows)
            self._recompute_size_locked()

    def drop_client_size(self, client_id):
        with self.clock:
            self.client_sizes.pop(client_id, None)
            self._recompute_size_locked()

    def _recompute_size_locked(self):
        sizes = [s for s in self.client_sizes.values() if s[0] and s[1]]
        if not sizes:
            return
        cols = min(s[0] for s in sizes); rows = min(s[1] for s in sizes)
        if cols and rows and (cols, rows) != (self.cols, self.rows):
            self.cols, self.rows = cols, rows
            self.send_upstream(("1" + json.dumps({"columns": cols, "rows": rows})).encode(), 0x1)

    def state(self, now):
        if self.awaiting_confirm and (now - self.confirm_ts) < 600:
            return "confirm"
        if (now - self.last_output_ts) < 4:
            return "running"
        return "idle"

    def _connect_upstream(self):
        s = socket.create_connection(("127.0.0.1", self.ttyd_port), 10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
               "Sec-WebSocket-Protocol: tty\r\n\r\n" % (self.ttyd_port, key))
        s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = s.recv(4096)
            if not c:
                raise OSError("ttyd no 101")
            buf += c
        self.upstream = s
        # init frame ttyd expects: {AuthToken, columns, rows}
        init = json.dumps({"AuthToken": "", "columns": 100, "rows": 30}).encode()
        ws_send(s, init, 0x1, mask=True)
        threading.Thread(target=self._reader, daemon=True).start()

    def _store(self, payload):
        self.frames.append(payload)
        self.frames_size += len(payload)
        while self.frames_size > BUF_CAP and len(self.frames) > 1:
            old = self.frames.pop(0)
            self.frames_size -= len(old)
            self.frames_dropped = True

    def plain_log(self):
        with self.clock:
            snapshot = list(self.frames)
            truncated = self.frames_dropped
            size = self.frames_size
        text = "".join(_payload_to_plain_text(fr) for fr in snapshot)
        if len(text) > LOG_TEXT_CAP:
            text = text[-LOG_TEXT_CAP:]
            truncated = True
        return text, truncated, size

    def _broadcast(self, payload, opcode):
        dead = []
        for c in self.clients:
            try:
                ws_send(c, payload, opcode)
            except OSError:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)

    def _reader(self):
        s = self.upstream
        while True:
            try:
                op, payload = ws_recv(s)
            except OSError:
                break
            if op is None or op == 0x8:
                break
            if op in (0x1, 0x2):
                self.last_output_ts = time.time()
                if _CONFIRM_RE.search(payload):
                    self.awaiting_confirm = True
                    self.confirm_ts = time.time()
                with self.clock:
                    self._store(payload)
                    self._broadcast(payload, op)
        # upstream gone
        try:
            for c in list(self.clients):
                c.close()
        except OSError:
            pass
        self.clients.clear()

    def send_upstream(self, payload, opcode):
        if self.upstream:
            try:
                ws_send(self.upstream, payload, opcode, mask=True)
            except OSError:
                pass

    def add_client(self, sock):
        # replay buffered frames so late joiners see history
        with self.clock:
            snapshot = list(self.frames)
        for fr in snapshot:
            try:
                ws_send(sock, fr, 0x2)
            except OSError:
                return
        with self.clock:
            self.clients.add(sock)
        cid = id(sock)
        try:
            first = True
            while True:
                op, payload = ws_recv(sock)
                if op is None or op == 0x8:
                    break
                if op not in (0x1, 0x2):
                    continue
                p0 = payload[:1]
                if first:
                    first = False
                    if p0 == b"{":  # ttyd client init {AuthToken, columns, rows}
                        try:
                            o = json.loads(payload.decode("utf-8", "replace"))
                            self.apply_resize(cid, o.get("columns"), o.get("rows"))
                        except Exception:
                            pass
                        continue
                if p0 == b"1":  # resize -> shrink-to-min
                    try:
                        o = json.loads(payload[1:].decode("utf-8", "replace"))
                        self.apply_resize(cid, o.get("columns"), o.get("rows"))
                    except Exception:
                        pass
                    continue
                # input + others: forward and mark activity
                self.last_input_ts = time.time()
                self.awaiting_confirm = False
                self.send_upstream(payload, op)
        except OSError:
            pass
        finally:
            with self.clock:
                self.clients.discard(sock)
            self.drop_client_size(cid)
            try:
                sock.close()
            except OSError:
                pass

    def close(self):
        try:
            if self.upstream:
                self.upstream.close()
        except OSError:
            pass
        for c in list(self.clients):
            try:
                c.close()
            except OSError:
                pass
        self.clients.clear()


# ---------- session lifecycle ----------
def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def wait_port(port, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = socket.create_connection(("127.0.0.1", port), 0.5); s.close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


def alloc_port():
    with _lock:
        used = {s["port"] for s in sessions.values()}
    for off in range(0, 300):
        port = PORT_BASE + off
        if port in PORT_SKIP or port in used:
            continue
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port)); s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("no free port")


def prune_dead():
    with _lock:
        dead = [sid for sid, s in sessions.items() if s["proc"].poll() is not None]
        for sid in dead:
            s = sessions.pop(sid, None)
            if s and s.get("hub"):
                try: s["hub"].close()
                except OSError: pass


def kill_session(sid):
    with _lock:
        s = sessions.pop(sid, None)
    if not s:
        return False
    if s.get("hub"):
        try: s["hub"].close()
        except OSError: pass
    try: s["proc"].terminate()
    except OSError: pass
    try: s["proc"].wait(timeout=3)
    except subprocess.TimeoutExpired:
        try: s["proc"].kill()
        except OSError: pass
    return True


def kill_all():
    with _lock:
        sids = list(sessions.keys())
    for sid in sids:
        kill_session(sid)


def launch(cwd, backend="codex", cli_args=None, title="", mode="new", session_id=None, auto_approve=None, extra_args=None):
    prune_dead()
    bconf = BACKENDS.get(backend) or BACKENDS["codex"]
    bin_path = bconf["bin"]
    if not bin_path or not os.path.isfile(bin_path):
        raise RuntimeError("%s 未找到(请用 npm 装 @openai/codex 或安装 claude,或设 CODEX_BIN/CLAUDE_BIN)" % bconf["label"])
    if auto_approve is None:
        auto_approve = AUTO_APPROVE
    yolo = list(bconf["yolo"]) if auto_approve else []
    display_args = ["--no-alt-screen"] if backend == "codex" and CODEX_NO_ALT_SCREEN else []
    extra = shlex.split(extra_args) if extra_args else []
    port = alloc_port()
    # ttyd: localhost-only, writable. Persistent (hub keeps the CLI alive).
    cmd = [TTYD, "-p", str(port), "-W", "-w", cwd, "-i", BIND_IFACE, bin_path] + yolo + display_args + extra + (cli_args or [])
    proc = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_port(port)
    hub = Hub(port)
    with _lock:
        _sid[0] += 1
        sid = "s%d" % _sid[0]
        sessions[sid] = {
            "port": port, "proc": proc, "dir": cwd, "backend": backend,
            "title": title or os.path.basename(cwd.rstrip("\\/")) or cwd,
            "started": time.time(), "mode": mode, "session_id": session_id, "hub": hub,
        }
    return sid, port


atexit.register(kill_all)


# ---------- history ----------
def iso_to_epoch(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def load_history(limit=60):
    titles = {}
    try:
        with open(HISTORY_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                sid = o.get("session_id")
                if sid:
                    titles[sid] = {"ts": o.get("ts"), "title": (o.get("text") or "").strip()}
    except OSError:
        pass
    out = []
    if not os.path.isdir(SESSIONS_DIR):
        return out
    for dp, _dirs, fs in os.walk(SESSIONS_DIR):
        for fn in fs:
            if not fn.endswith(".jsonl"):
                continue
            try:
                with open(os.path.join(dp, fn), "r", encoding="utf-8") as f:
                    meta = json.loads(f.readline())
            except (OSError, ValueError):
                continue
            if meta.get("type") != "session_meta":
                continue
            p = meta.get("payload", {})
            sid = p.get("session_id")
            if not sid:
                continue
            t = titles.get(sid, {})
            out.append({
                "session_id": sid, "cwd": p.get("cwd", ""),
                "ts": t.get("ts") or iso_to_epoch(p.get("timestamp", "")),
                "title": t.get("title") or "(无标题)", "originator": p.get("originator", ""),
            })
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out[:limit]


def recent_dirs(limit=30):
    by = {}
    for h in load_history(500):
        c = h.get("cwd") or "(未知目录)"
        e = by.get(c)
        if e is None:
            e = {"cwd": c, "count": 0, "last_ts": 0}; by[c] = e
        e["count"] += 1
        if (h.get("ts") or 0) > e["last_ts"]:
            e["last_ts"] = h.get("ts") or 0
    return sorted(by.values(), key=lambda x: x["last_ts"], reverse=True)[:limit]


# ---------- folder browse ----------
def parent_of(path):
    if not path:
        return ""
    par = os.path.dirname(path)
    return "" if par == path else par


def browse(path):
    if not path:
        drives = []
        for i in range(26):
            letter = chr(ord("A") + i)
            d = letter + ":\\"
            if os.path.isdir(d):
                drives.append({"name": letter + ":", "path": d})
        return {"path": "", "parent": "", "entries": drives}
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return {"error": "not a directory", "path": path}
    entries = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir():
                        entries.append({"name": e.name, "path": e.path})
                except OSError:
                    pass
    except OSError as ex:
        return {"error": str(ex), "path": path}
    entries.sort(key=lambda x: x["name"].lower())
    return {"path": path, "parent": parent_of(path), "entries": entries}


def session_obj(sid, s, host):
    hub = s["hub"]; now = time.time()
    return {"sid": sid, "dir": s["dir"], "title": s["title"], "mode": s["mode"],
            "session_id": s["session_id"], "started": s["started"], "term_path": "/t/%s/" % sid,
            "backend": s.get("backend", "codex"),
            "state": hub.state(now), "last_input_ts": hub.last_input_ts,
            "last_output_ts": hub.last_output_ts, "cols": hub.cols, "rows": hub.rows}


def fetch_ttyd_html(port):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request("GET", "/")
        resp = conn.getresponse()
        return resp.read()
    finally:
        conn.close()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "codex-web/4.0"

    def log_message(self, *a):
        pass

    def _auth(self):
        if RUN_MODE == "manager" and _is_local_client(self.client_address):
            return True
        if self.headers.get("Authorization", "") == EXPECTED_AUTH:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="codex-web"')
        self.send_header("Content-Length", "12"); self.end_headers()
        self.wfile.write(b"auth required")
        return False

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

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
                html = fetch_ttyd_html(port)
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
        self.send_header("Sec-WebSocket-Accept", ws_accept_key(key))
        if "tty" in (self.headers.get("Sec-WebSocket-Protocol") or ""):
            self.send_header("Sec-WebSocket-Protocol", "tty")
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:
            pass
        hub.add_client(self.connection)

    def _serve_index(self):
        try:
            data = open(INDEX, "rb").read()
        except OSError as e:
            self._json({"error": str(e)}, 500); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def _serve_sw(self):
        try:
            data = open(SW_FILE, "rb").read()
        except OSError:
            self._json({"error": "service worker not found"}, 404); return
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Service-Worker-Allowed", "/")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def _proxy_manager_http(self, method, body=None):
        if not ensure_manager():
            self._json({"error": "manager not available"}, 503); return
        headers = {}
        ctype = self.headers.get("Content-Type")
        if ctype:
            headers["Content-Type"] = ctype
        try:
            conn = http.client.HTTPConnection(MANAGER_HOST, MANAGER_PORT, timeout=60)
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk in ("connection", "transfer-encoding", "keep-alive", "proxy-authenticate",
                          "proxy-authorization", "te", "trailers", "upgrade", "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            self._json({"error": "manager proxy failed: %s" % e}, 502)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _proxy_manager_ws(self):
        if not ensure_manager():
            self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers(); return
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_response(400); self.send_header("Content-Length", "0"); self.end_headers(); return
        try:
            upstream = socket.create_connection((MANAGER_HOST, MANAGER_PORT), 10)
            req = [
                "GET %s HTTP/1.1" % self.path,
                "Host: %s:%d" % (MANAGER_HOST, MANAGER_PORT),
                "Upgrade: websocket",
                "Connection: Upgrade",
                "Sec-WebSocket-Key: %s" % key,
                "Sec-WebSocket-Version: %s" % (self.headers.get("Sec-WebSocket-Version") or "13"),
            ]
            proto = self.headers.get("Sec-WebSocket-Protocol")
            if proto:
                req.append("Sec-WebSocket-Protocol: %s" % proto)
            upstream.sendall(("\r\n".join(req) + "\r\n\r\n").encode())
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = upstream.recv(4096)
                if not chunk:
                    raise OSError("manager websocket handshake failed")
                resp += chunk
            if b" 101 " not in resp.split(b"\r\n", 1)[0]:
                self.connection.sendall(resp)
                upstream.close()
                return
            self.close_connection = True
            self.connection.sendall(resp)

            def pipe(src, dst):
                try:
                    while True:
                        data = src.recv(65536)
                        if not data:
                            break
                        dst.sendall(data)
                except OSError:
                    pass
                finally:
                    try: dst.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    try: dst.close()
                    except OSError: pass

            t = threading.Thread(target=pipe, args=(upstream, self.connection), daemon=True)
            t.start()
            pipe(self.connection, upstream)
        except OSError:
            try:
                self.send_response(502); self.send_header("Content-Length", "0"); self.end_headers()
            except OSError:
                pass

    def _web_get(self, path):
        if path in ("/", "/index.html"):
            self._serve_index(); return
        if path == "/sw.js":
            self._serve_sw(); return
        if path.startswith("/t/") and path.endswith("/ws"):
            self._proxy_manager_ws(); return
        if path.startswith("/t/") or path.startswith("/api/"):
            self._proxy_manager_http("GET"); return
        self._json({"error": "not found"}, 404)

    def _web_post(self, path, raw):
        if path == "/api/restart_web":
            self._json({"ok": True, "message": "web restarting"})
            restart_web_soon()
            return
        if path.startswith("/api/"):
            self._proxy_manager_http("POST", raw); return
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        if not self._auth():
            return
        pr = urllib.parse.urlparse(self.path)
        path = pr.path
        if RUN_MODE != "manager":
            self._web_get(path); return
        if path.startswith("/t/"):
            parts = path.split("/")
            if len(parts) >= 3 and parts[1] == "t":
                sid = parts[2]
                rest = "/".join(parts[3:])
                return self._serve_terminal(sid, rest)
            self._json({"error": "bad terminal path"}, 404); return
        if path in ("/", "/index.html"):
            try:
                data = open(INDEX, "rb").read()
            except OSError as e:
                self._json({"error": str(e)}, 500); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path == "/sw.js":
            try:
                data = open(SW_FILE, "rb").read()
            except OSError:
                self._json({"error": "service worker not found"}, 404); return
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Service-Worker-Allowed", "/")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path == "/api/browse":
            q = urllib.parse.parse_qs(pr.query); self._json(browse(q.get("path", [""])[0]))
        elif path == "/api/sessions":
            prune_dead()
            with _lock:
                items = [session_obj(sid, s, self.headers.get("Host", "")) for sid, s in sessions.items()]
            items.sort(key=lambda x: x["started"], reverse=True)
            self._json({"sessions": items})
        elif path == "/api/log":
            q = urllib.parse.parse_qs(pr.query)
            sid = (q.get("sid", [""])[0] or "").strip()
            with _lock:
                s = sessions.get(sid)
            if not s:
                self._json({"error": "session not found"}, 404); return
            text, truncated, size = s["hub"].plain_log()
            self._json({"sid": sid, "text": text, "truncated": truncated, "bytes": size,
                        "updated": time.time()})
        elif path == "/api/history":
            q = urllib.parse.parse_qs(pr.query)
            self._json({"history": load_history(int(q.get("limit", ["60"])[0] or 60))})
        elif path == "/api/recent_dirs":
            q = urllib.parse.parse_qs(pr.query)
            self._json({"dirs": recent_dirs(int(q.get("limit", ["30"])[0] or 30))})
        elif path == "/api/backends":
            self._json({"backends": [k for k, v in BACKENDS.items() if v["bin"] and os.path.isfile(v["bin"])],
                        "labels": {k: v["label"] for k, v in BACKENDS.items()}})
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
        if RUN_MODE != "manager":
            self._web_post(pr.path, raw); return
        if pr.path == "/api/launch":
            d = (data.get("dir") or "").strip().strip('"')
            if not d or not os.path.isdir(d):
                self._json({"error": "invalid directory: %r" % d}, 400); return
            backend = (data.get("backend") or "codex").strip()
            if backend not in BACKENDS:
                backend = "codex"
            yo = data.get("yolo")
            auto_approve = AUTO_APPROVE if yo is None else bool(yo)
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
            try:
                sid, _ = launch(d, backend="codex", cli_args=["resume", sid_arg],
                                title=data.get("title") or "恢复会话", mode="resume", session_id=sid_arg)
            except Exception as e:
                self._json({"error": str(e)}, 500); return
            self._json({"ok": True, "sid": sid, "dir": d, "term_path": "/t/%s/" % sid})
        elif pr.path == "/api/stop":
            self._json({"ok": kill_session((data.get("sid") or "").strip())})
        elif pr.path == "/api/stop_all":
            kill_all(); self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


if __name__ == "__main__":
    ip = lan_ip()
    if RUN_MODE == "manager":
        print("Codex-Web manager: http://%s:%d" % (MANAGER_HOST, MANAGER_PORT))
        try:
            try:
                _server[0] = ThreadingServer((MANAGER_HOST, MANAGER_PORT), Handler)
            except OSError as e:
                print("ERROR: manager 端口 %d 已被占用：%s" % (MANAGER_PORT, e))
                sys.exit(1)
            _server[0].serve_forever()
        except KeyboardInterrupt:
            kill_all(); print("manager bye")
    else:
        ensure_manager()
        print("=" * 56)
        print(" Codex-Web  (Web/Manager split: 可单独重启网页)")
        print(" 控制台(手机/电脑打开): http://%s:%d" % (ip, PICKER_PORT))
        print(" Manager(本机): http://%s:%d" % (MANAGER_HOST, MANAGER_PORT))
        print(" 账号: %s  密码: ***" % CRED.split(":", 1)[0])
        print(" codex : %s" % (CODEX_BIN or "(未找到)"))
        print(" claude: %s" % (CLAUDE_BIN or "(未找到)"))
        print(" Ctrl+C 只退出 Web；运行中的 Codex 由 manager 保持")
        print("=" * 56)
        try:
            try:
                _server[0] = ThreadingServer((HOST, PICKER_PORT), Handler)
            except OSError as e:
                print("ERROR: 控制台端口 %d 已被旧 Web 占用：%s" % (PICKER_PORT, e))
                print("请关闭旧的 start.cmd/Python 窗口后再启动，或结束占用该端口的旧 Web 进程。")
                sys.exit(1)
            _server[0].serve_forever()
        except KeyboardInterrupt:
            print("web bye")
