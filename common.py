# -*- coding: utf-8 -*-
"""
Agents Cockpit — shared infrastructure (used by both web and manager processes).

Constants/paths, env, binary discovery, auth, websocket frame helpers, history
loaders, CC-Switch read-only integration, folder browse, the session registry +
scrollback readers (Phase B), port/PID helpers, and the manager-spawn helpers.

This module must NOT import web.py / manager.py / hub.py (keeps the dependency
graph acyclic: app -> {web, manager} -> common; manager -> hub -> common).
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
import time
import socket
import configparser
import http.client
import hashlib
import re
import shlex
import sqlite3
from datetime import datetime

# ---- config: read everything from config.ini (no env vars) ----
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.ini")

_CONFIG_DEFAULTS = """
[server]
host = 0.0.0.0
port = 7682
port_base = 0
bind = 127.0.0.1
[manager]
port = 0
heartbeat = 2
heartbeat_grace = 3
[approval]
auto_approve = 1
codex_no_alt_screen = 1
[binaries]
codex =
claude =
ttyd =
[paths]
auth_file = auth.txt
codex_home =
claude_home =
[ccswitch]
db =
usage_ttl = 15
balance_ttl = 300
[limits]
buf_cap = 262144
claude_scan_cap = 6000
"""


def _load_config():
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_string(_CONFIG_DEFAULTS)
    if os.path.isfile(CONFIG_FILE):
        try:
            cp.read(CONFIG_FILE, encoding="utf-8")
        except configparser.Error as e:
            print("WARNING: config.ini 解析失败,改用默认值: %s" % e)
    return cp


_CFG = _load_config()


def _cfg_get(section, key, fallback=""):
    try:
        return _CFG.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


HOST = (_CFG.get("server", "host") or "0.0.0.0").strip()
PICKER_PORT = _CFG.getint("server", "port") or 7682
_pb = _CFG.getint("server", "port_base")
PORT_BASE = _pb if _pb > 0 else PICKER_PORT + 1
PORT_SKIP = {PICKER_PORT}
INDEX = os.path.join(HERE, "index.html")
BIND_IFACE = (_CFG.get("server", "bind") or "127.0.0.1").strip()  # ttyd loopback iface (Windows: 127.0.0.1)
CREATE_NO_WINDOW = 0x08000000
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BUF_CAP = _CFG.getint("limits", "buf_cap") or 262144  # max replay buffer per session (~256KB)
AUTO_APPROVE = _CFG.getboolean("approval", "auto_approve")        # codex --yolo / claude --dangerously-skip-permissions
CODEX_NO_ALT_SCREEN = _CFG.getboolean("approval", "codex_no_alt_screen")
RUN_MODE = "manager" if "--manager" in sys.argv else "web"
MANAGER_HOST = "127.0.0.1"
_mp = _CFG.getint("manager", "port")
MANAGER_PORT = _mp if _mp > 0 else PICKER_PORT + 1000

# ---- persisted-state dirs (registry + scrollback for soft-restart reattach) ----
STATE_DIR = os.path.join(HERE, ".agent-cockpit")
REGISTRY_PATH = os.path.join(STATE_DIR, "sessions.json")
SCROLLBACK_DIR = os.path.join(STATE_DIR, "scrollback")
REG_LOCK = threading.Lock()                       # only guards disk writes; never nest under manager._lock
MANAGER_HEARTBEAT_INTERVAL = _CFG.getfloat("manager", "heartbeat") or 2.0
MANAGER_HEARTBEAT_GRACE = _CFG.getint("manager", "heartbeat_grace") or 3

# ---- CC Switch integration (optional, read-only) ----
CCSWITCH_DB = (_cfg_get("ccswitch", "db") or os.path.join(os.path.expanduser("~"), ".cc-switch", "cc-switch.db")).strip()
CCSWITCH_USAGE_TTL = _CFG.getint("ccswitch", "usage_ttl") or 15        # db read cache (s)
CCSWITCH_BALANCE_TTL = _CFG.getint("ccswitch", "balance_ttl") or 300   # quota cache (s)

AUTH_FILE = (_cfg_get("paths", "auth_file") or os.path.join(HERE, "auth.txt")).strip()
if not os.path.isabs(AUTH_FILE):
    AUTH_FILE = os.path.join(HERE, AUTH_FILE)

CODEX_HOME = (_cfg_get("paths", "codex_home") or os.path.join(os.path.expanduser("~"), ".codex")).strip()
SESSIONS_DIR = os.path.join(CODEX_HOME, "sessions")
HISTORY_JSONL = os.path.join(CODEX_HOME, "history.jsonl")
CLAUDE_HOME = (_cfg_get("paths", "claude_home") or os.path.join(os.path.expanduser("~"), ".claude")).strip()
CLAUDE_PROJECTS_DIR = os.path.join(CLAUDE_HOME, "projects")
# 扫描单个 claude 会话文件的最大行数(标题/ai-title 通常在前若干行;超大转录用此封顶)
CLAUDE_SCAN_CAP = _CFG.getint("limits", "claude_scan_cap") or 6000



# ---------- binary discovery ----------
def _find_codex_under(root):
    want = "codex.exe" if os.name == "nt" else "codex"
    if not os.path.isdir(root):
        return None
    for dp, _d, fs in os.walk(root):
        if dp.endswith(os.sep + "bin") and want in fs:
            return os.path.join(dp, want)
    return None


def resolve_codex_bin(override=None):
    if override and os.path.isfile(override):
        return override
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
    try:
        out = subprocess.check_output("npm root -g", shell=True, stderr=subprocess.DEVNULL, timeout=10).decode(errors="replace").strip()
        if out:
            found = _find_codex_under(os.path.join(out, "@openai"))
            if found:
                return found
    except Exception:
        pass
    return None


def resolve_ttyd(override=None):
    if override and os.path.isfile(override):
        return override
    for c in (os.path.join(HERE, "ttyd.exe"), os.path.join(HERE, "ttyd")):
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ttyd")


def resolve_claude_bin(override=None):
    if override and os.path.isfile(override):
        return override
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


CODEX_BIN = resolve_codex_bin(_cfg_get("binaries", "codex").strip() or None)
CLAUDE_BIN = resolve_claude_bin(_cfg_get("binaries", "claude").strip() or None)
TTYD = resolve_ttyd(_cfg_get("binaries", "ttyd").strip() or None)

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


# ---------- net helpers ----------
def _is_local_client(addr):
    host = addr[0] if addr else ""
    return host in ("127.0.0.1", "::1", "localhost")


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


def _port_alive(port, timeout=0.5):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout)
        s.close()
        return True
    except OSError:
        return False


def _kill_pid(pid):
    """Kill a process by PID (used for re-attached sessions with no Popen handle).
    Windows: taskkill /F /T also reaps the ttyd's codex/claude child. POSIX: SIGTERM->SIGKILL."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           creationflags=CREATE_NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            import signal as _sig
            try:
                os.kill(pid, _sig.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
                time.sleep(0.15)
            try:
                os.kill(pid, _sig.SIGKILL)
            except OSError:
                pass
    except Exception:
        pass


# ---------- manager spawn / liveness (used by web) ----------
def _manager_path():
    return sys.argv[0] if sys.argv and sys.argv[0] else __file__


def _manager_argv():
    # config is file-based, so the manager subprocess just needs the mode flag;
    # both processes read the same config.ini from disk.
    return [sys.executable, os.path.abspath(_manager_path()), "--manager"]


def manager_available():
    try:
        conn = http.client.HTTPConnection(MANAGER_HOST, MANAGER_PORT, timeout=0.8)
        conn.request("GET", "/api/backends")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return 200 <= resp.status < 500
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


# ---------- persisted session registry (Phase B) ----------
def registry_load():
    """Return the raw registry object ({version, manager_pid, sessions:{sid->entry}}) or {}."""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj or {}
    except (OSError, ValueError):
        return {}


def _registry_write(obj):
    """Atomic write under REG_LOCK. Never raises."""
    with REG_LOCK:
        tmp = REGISTRY_PATH + ".tmp"
        try:
            os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f)
            os.replace(tmp, REGISTRY_PATH)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _registry_read_locked():
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        obj = {"version": 1, "sessions": {}}
    if not isinstance(obj, dict):
        obj = {"version": 1, "sessions": {}}
    if not isinstance(obj.get("sessions"), dict):
        obj["sessions"] = {}
    return obj


def registry_save(entries):
    """Overwrite the whole sessions map (used by soft-exit snapshot). entries: {sid -> entry}."""
    _registry_write({"version": 1, "manager_pid": os.getpid(), "sessions": entries})


def registry_upsert(sid, entry):
    """Read-modify-write a single sid (safe under concurrent launch calls)."""
    with REG_LOCK:
        obj = _registry_read_locked()
        obj["sessions"][sid] = entry
        obj["manager_pid"] = os.getpid()
        _registry_write_unlocked(obj)


def _registry_write_unlocked(obj):
    tmp = REGISTRY_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, REGISTRY_PATH)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def registry_drop(sid):
    """Remove one sid from registry + best-effort delete its scrollback log."""
    with REG_LOCK:
        obj = _registry_read_locked()
        if sid not in obj["sessions"]:
            changed = False
        else:
            obj["sessions"].pop(sid, None)
            changed = True
        if changed:
            _registry_write_unlocked(obj)
    try:
        os.unlink(os.path.join(SCROLLBACK_DIR, "%s.log" % sid))
    except OSError:
        pass


def registry_clear():
    _registry_write({"version": 1, "manager_pid": os.getpid(), "sessions": {}})


def _registry_safe_entry(sid, s):
    """Project a live session dict onto the JSON-serializable registry shape."""
    proc = s.get("proc")
    pid = proc.pid if proc is not None else s.get("pid")
    hub = s.get("hub")
    return {
        "port": s.get("port"),
        "pid": pid,
        "dir": s.get("dir", ""),
        "backend": s.get("backend", "codex"),
        "title": s.get("title", ""),
        "started": s.get("started", time.time()),
        "mode": s.get("mode", "new"),
        "session_id": s.get("session_id"),
        "cols": getattr(hub, "cols", 0) if hub else 0,
        "rows": getattr(hub, "rows", 0) if hub else 0,
    }


def read_scrollback(sid, cap=BUF_CAP):
    """Parse a length-prefixed scrollback log; return up to the last `cap` bytes of frames.
    Resyncs past a truncated leading frame (we may have seeked mid-frame)."""
    path = os.path.join(SCROLLBACK_DIR, "%s.log" % sid)
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    try:
        with open(path, "rb") as f:
            if size > cap:
                f.seek(size - cap)
            data = f.read()
    except OSError:
        return []
    frames = []
    i, n = 0, len(data)
    resync = size > cap   # only the leading frame can be partial
    while i + 4 <= n:
        ln = int.from_bytes(data[i:i + 4], "big")
        if resync:
            if 0 < ln <= 1048576 and i + 4 + ln <= n:
                resync = False
                frames.append(data[i + 4:i + 4 + ln])
                i += 4 + ln
            else:
                i += 1
            continue
        if i + 4 + ln > n:
            break  # truncated tail
        frames.append(data[i + 4:i + 4 + ln])
        i += 4 + ln
    return frames


# ---------- history ----------
def iso_to_epoch(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def _claude_user_text(o):
    """Pull the human-typed text out of a claude 'user' record (str or content blocks)."""
    msg = o.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text") or "")
        return " ".join(p for p in parts if p).strip()
    return ""


def load_claude_history():
    """Scan ~/.claude/projects/*/<uuid>.jsonl into the same shape as codex history."""
    out = []
    if not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return out
    for dp, _dirs, fs in os.walk(CLAUDE_PROJECTS_DIR):
        for fn in fs:
            if not fn.endswith(".jsonl"):
                continue
            # 跳过子代理(sidechain)转写:它们躺在 <session-uuid>/subagents/ 下,
            # 文件名以 agent- 开头,不是可独立 --resume 的会话。
            if os.path.basename(dp) == "subagents" or fn.startswith("agent-"):
                continue
            sid = fn[:-6]  # strip .jsonl → 即 sessionId(== 文件名)
            cwd = ts_str = first_user = ai_title = ""
            try:
                with open(os.path.join(dp, fn), "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i >= CLAUDE_SCAN_CAP:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except ValueError:
                            continue
                        if not cwd and o.get("cwd"):
                            cwd = o["cwd"]
                        if not ts_str and o.get("timestamp"):
                            ts_str = o["timestamp"]
                        t = o.get("type")
                        if t == "ai-title" and not ai_title:
                            ai_title = (o.get("aiTitle") or "").strip()
                        elif t == "summary" and not ai_title:
                            ai_title = (o.get("summary") or "").strip()
                        elif t == "user" and not first_user:
                            txt = _claude_user_text(o)
                            if txt:
                                first_user = txt
                        if cwd and ts_str and ai_title:
                            break
            except OSError:
                continue
            if not cwd:
                continue
            title = (ai_title or first_user or "(无标题)").strip()
            out.append({
                "session_id": sid, "cwd": cwd,
                "ts": iso_to_epoch(ts_str),
                "title": title, "originator": "", "backend": "claude",
            })
    return out


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
    if os.path.isdir(SESSIONS_DIR):
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
                    "backend": "codex",
                })
    out.extend(load_claude_history())
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


# ---------- CC Switch integration (optional, read-only) ----------
def _toml_first(text, key):
    m = re.search(r'(?m)^[ \t]*%s[ \t]*=[ \t]*"([^"]+)"' % re.escape(key), text or "")
    return m.group(1) if m else None


def _ccswitch_provider_meta(sc_json, app_type):
    """Parse one provider's settings_config into model/base_url/host/api_key."""
    try:
        sc = json.loads(sc_json) if sc_json else {}
    except ValueError:
        sc = {}
    if not isinstance(sc, dict):
        sc = {}
    env = sc.get("env") if isinstance(sc.get("env"), dict) else {}
    api_key = ""
    if app_type == "claude":
        model = env.get("ANTHROPIC_MODEL") or env.get("ANTHROPIC_DEFAULT_SONNET_MODEL_NAME") or ""
        base_url = env.get("ANTHROPIC_BASE_URL") or ""
        api_key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY") or ""
    else:  # codex etc: config is a TOML string; auth may hold the key
        cfg = sc.get("config") or ""
        model = _toml_first(cfg, "model") or ""
        base_url = _toml_first(cfg, "base_url") or ""
        auth = sc.get("auth") if isinstance(sc.get("auth"), dict) else {}
        api_key = auth.get("OPENAI_API_KEY") or ""
    host = urllib.parse.urlparse(base_url).hostname if base_url else ""
    return {"model": model, "base_url": base_url, "host": host or "", "api_key": api_key}


def _ccswitch_open():
    uri = "file:%s?mode=ro" % CCSWITCH_DB.replace("\\", "/").replace("?", "")
    con = sqlite3.connect(uri, uri=True, timeout=2.0)
    con.row_factory = sqlite3.Row
    return con


def _day_start_epoch(now):
    lt = time.localtime(now)
    return time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))


def _month_start_epoch(now):
    lt = time.localtime(now)
    return time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1)))


def _usage_window(cur, since):
    row = cur.execute(
        "SELECT COUNT(*) n, TOTAL(CAST(total_cost_usd AS REAL)) cost, "
        "TOTAL(input_tokens) it, TOTAL(output_tokens) ot, "
        "TOTAL(COALESCE(cache_read_tokens,0)+COALESCE(cache_creation_tokens,0)) ct "
        "FROM proxy_request_logs WHERE created_at>=? AND status_code<500", (since,)).fetchone()
    return {"requests": int(row["n"] or 0), "cost": round(float(row["cost"] or 0.0), 4),
            "input_tokens": int(row["it"] or 0), "output_tokens": int(row["ot"] or 0),
            "cache_tokens": int(row["ct"] or 0)}


def _usage_by_model(cur, since, limit=8):
    rows = cur.execute(
        "SELECT model, COUNT(*) n, TOTAL(CAST(total_cost_usd AS REAL)) cost, "
        "TOTAL(input_tokens+output_tokens+COALESCE(cache_read_tokens,0)+COALESCE(cache_creation_tokens,0)) tok "
        "FROM proxy_request_logs WHERE created_at>=? AND status_code<500 "
        "GROUP BY model ORDER BY cost DESC LIMIT ?", (since, limit)).fetchall()
    return [{"model": r["model"] or "(unknown)", "requests": int(r["n"] or 0),
             "cost": round(float(r["cost"] or 0.0), 4), "tokens": int(r["tok"] or 0)} for r in rows]


_ccswitch_usage_cache = {"ts": 0.0, "data": None}


def ccswitch_overview():
    if not os.path.isfile(CCSWITCH_DB):
        return {"enabled": False}
    now = time.time()
    cached = _ccswitch_usage_cache["data"]
    if cached and now - _ccswitch_usage_cache["ts"] < CCSWITCH_USAGE_TTL:
        out = dict(cached); out["cached"] = True; return out
    try:
        con = _ccswitch_open()
    except Exception as e:
        return {"enabled": True, "error": "open db: %s" % e, "providers": [], "usage": {}}
    try:
        cur = con.cursor()
        providers = []
        for r in cur.execute("SELECT app_type,name,is_current,settings_config FROM providers "
                             "ORDER BY is_current DESC, app_type"):
            m = _ccswitch_provider_meta(r["settings_config"], r["app_type"])
            providers.append({"app_type": r["app_type"], "name": r["name"],
                              "is_current": bool(r["is_current"]),
                              "model": m["model"], "host": m["host"]})
        usage = {"today": _usage_window(cur, _day_start_epoch(now)),
                 "month": _usage_window(cur, _month_start_epoch(now)),
                 "by_model": _usage_by_model(cur, _day_start_epoch(now)),
                 "last_ts": int(cur.execute("SELECT MAX(created_at) m FROM proxy_request_logs").fetchone()["m"] or 0)}
        out = {"enabled": True, "providers": providers, "usage": usage, "cached": False}
        _ccswitch_usage_cache["data"] = out
        _ccswitch_usage_cache["ts"] = now
        return dict(out)
    except Exception as e:
        return {"enabled": True, "error": str(e), "providers": [], "usage": {}}
    finally:
        try:
            con.close()
        except Exception:
            pass


def _zhipu_api_base(host):
    h = (host or "").lower()
    if "bigmodel.cn" in h:
        return "https://open.bigmodel.cn"
    if "z.ai" in h:
        return "https://api.z.ai"
    return None


def _ccswitch_current_zhipu():
    """Return (api_key, host) for the current claude provider if Zhipu/Z.ai, else None."""
    try:
        con = _ccswitch_open()
    except Exception:
        return None
    try:
        row = con.execute("SELECT settings_config FROM providers WHERE app_type='claude' AND is_current=1 LIMIT 1").fetchone()
        if not row:
            return None
        m = _ccswitch_provider_meta(row["settings_config"], "claude")
        if not m["api_key"] or not m["host"]:
            return None
        return (m["api_key"], m["host"])
    finally:
        try:
            con.close()
        except Exception:
            pass


_ccswitch_balance_cache = {"key": None, "host": None, "ts": 0.0, "data": None}
_ccswitch_balance_lock = threading.Lock()
_ccswitch_balance_refreshing = [False]


def _ccswitch_balance_refresh(target_key, target_host):
    out = None
    try:
        api_base = _zhipu_api_base(target_host)
        if not api_base or not target_key:
            out = {"supported": False}
        else:
            host = api_base.split("://", 1)[1]
            conn = http.client.HTTPSConnection(host, timeout=6.0)
            conn.request("GET", "/api/monitor/usage/quota/limit", headers={
                "Authorization": target_key, "Accept-Language": "en-US,en",
                "Content-Type": "application/json"})
            resp = conn.getresponse(); body = resp.read(); conn.close()
            if resp.status != 200:
                raise RuntimeError("HTTP %d" % resp.status)
            obj = json.loads(body.decode("utf-8", "replace"))
            data = obj.get("data") or {}
            limits = data.get("limits") or []
            tok = next((x for x in limits if x.get("type") == "TOKENS_LIMIT"), None)
            if tok is None:
                raise RuntimeError("TOKENS_LIMIT not found in response")
            pct = float(tok.get("percentage") or 0)
            out = {"supported": True, "plan": str(data.get("level") or "ZHIPU").upper(),
                   "used_pct": round(pct, 1), "remaining_pct": round(max(0.0, 100.0 - pct), 1),
                   "reset_ms": tok.get("nextResetTime"), "fetched_at": time.time()}
    except Exception as e:
        out = {"supported": True, "error": str(e), "fetched_at": time.time()}
    with _ccswitch_balance_lock:
        _ccswitch_balance_cache.update(key=target_key, host=target_host, data=out, ts=time.time())
        _ccswitch_balance_refreshing[0] = False


def ccswitch_balance():
    """Non-blocking: returns cached quota (maybe null), spawns a background refresh when stale."""
    if not os.path.isfile(CCSWITCH_DB):
        return {"supported": False}
    info = _ccswitch_current_zhipu()
    if not info:
        return {"supported": False}
    key, host = info
    if not _zhipu_api_base(host) or not key:
        return {"supported": False}
    now = time.time()
    with _ccswitch_balance_lock:
        c = _ccswitch_balance_cache
        same = (c["key"] == key and c["host"] == host)
        if c["data"] is not None and same and now - c["ts"] < CCSWITCH_BALANCE_TTL:
            return dict(c["data"])
        served = dict(c["data"]) if (c["data"] is not None and same) else None
        if not _ccswitch_balance_refreshing[0]:
            _ccswitch_balance_refreshing[0] = True
            threading.Thread(target=_ccswitch_balance_refresh, args=(key, host), daemon=True).start()
        return served if served is not None else {"supported": True, "pending": True}


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


# ---------- shared HTTP handler base ----------
class BaseHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "agent-cockpit/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

    def _serve_index(self):
        try:
            data = open(INDEX, "rb").read()
        except OSError as e:
            self._json({"error": str(e)}, 500); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False
