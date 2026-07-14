# -*- coding: utf-8 -*-
"""
Agents Cockpit — shared infrastructure (used by both web and manager processes).

Constants/paths, env, binary discovery, auth, websocket frame helpers, history
loaders, CC-Switch read-only integration, folder browse, the session registry,
port/PID helpers, and the manager-spawn helpers.

This module must NOT import web.py / manager.py (keeps the dependency graph
acyclic: app -> {web, manager} -> common).
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
import hmac
import re
import secrets
import sqlite3
from datetime import datetime

# ---- config: read everything from config.ini (no env vars) ----
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.ini")

_CONFIG_DEFAULTS = """
[server]
host = 0.0.0.0
port = 7682
use_https = 0
cert_file =
key_file =
cert_cn = agents-cockpit
http_port = 0
[manager]
port = 0
heartbeat = 2
heartbeat_grace = 3
[approval]
auto_approve = 1
[binaries]
claude =
codex =
[paths]
auth_file = auth.txt
claude_home =
[ccswitch]
db =
usage_ttl = 15
balance_ttl = 300
[limits]
buf_cap = 262144
claude_scan_cap = 6000
[detect]
idle_debounce = 8
plan_threshold = 3
[notify]
enabled = 0
telegram_token =
telegram_chat_id =
bark_key =
webhook_url =
webhook_secret =
events = confirm,done
min_interval = 30
desktop_toast = 0
[security]
session_ttl = 86400
max_fail = 5
lockout_secs = 300
cookie_secure = 0
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
INDEX = os.path.join(HERE, "index.html")
CREATE_NO_WINDOW = 0x08000000
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BUF_CAP = _CFG.getint("limits", "buf_cap") or 262144
AUTO_APPROVE = _CFG.getboolean("approval", "auto_approve")  # Claude --dangerously-skip-permissions
RUN_MODE = "manager" if "--manager" in sys.argv else "web"
# --stop / --help must work even with a broken/empty config (no bins, no auth.txt),
# so we skip the startup sanity checks (which sys.exit) in those modes.
_STOP_OR_HELP = ("--stop" in sys.argv) or ("--help" in sys.argv) or ("-h" in sys.argv) or ("--is-running" in sys.argv)
MANAGER_HOST = "127.0.0.1"
_mp = _CFG.getint("manager", "port")
MANAGER_PORT = _mp if _mp > 0 else PICKER_PORT + 1000

# ---- persisted-state dirs (native session registry + replay state) ----
STATE_DIR = os.path.join(HERE, ".agent-cockpit")
REGISTRY_PATH = os.path.join(STATE_DIR, "sessions.json")
SCROLLBACK_DIR = os.path.join(STATE_DIR, "scrollback")  # legacy cleanup only
STOP_SENTINEL = "stop.sentinel"   # written by app.py --stop when the web layer is unreachable
REG_LOCK = threading.Lock()                       # only guards disk writes; never nest under manager._lock
STOPPING = False   # set True by web /api/_stop to freeze the watchdog + ensure_manager respawn
MANAGER_HEARTBEAT_INTERVAL = _CFG.getfloat("manager", "heartbeat") or 2.0
MANAGER_HEARTBEAT_GRACE = _CFG.getint("manager", "heartbeat_grace") or 3

# ---- CC Switch integration (optional, read-only) ----
CCSWITCH_DB = (_cfg_get("ccswitch", "db") or os.path.join(os.path.expanduser("~"), ".cc-switch", "cc-switch.db")).strip()
CCSWITCH_USAGE_TTL = _CFG.getint("ccswitch", "usage_ttl") or 15        # db read cache (s)
CCSWITCH_BALANCE_TTL = _CFG.getint("ccswitch", "balance_ttl") or 300   # quota cache (s)

AUTH_FILE = (_cfg_get("paths", "auth_file") or os.path.join(HERE, "auth.txt")).strip()
if not os.path.isabs(AUTH_FILE):
    AUTH_FILE = os.path.join(HERE, AUTH_FILE)

# ---- optional HTTPS for the browser-facing web server ----
USE_HTTPS = _CFG.getboolean("server", "use_https")
_cf = (_cfg_get("server", "cert_file")).strip()
_kf = (_cfg_get("server", "key_file")).strip()
CERT_FILE = (os.path.join(HERE, _cf) if (_cf and not os.path.isabs(_cf))
             else (_cf or os.path.join(STATE_DIR, "web_cert.pem")))
KEY_FILE = (os.path.join(HERE, _kf) if (_kf and not os.path.isabs(_kf))
            else (_kf or os.path.join(STATE_DIR, "web_key.pem")))
CERT_CN = (_cfg_get("server", "cert_cn") or "agents-cockpit").strip() or "agents-cockpit"
LAN_HTTP_PORT = _CFG.getint("server", "http_port")
CLAUDE_HOME = (_cfg_get("paths", "claude_home") or os.path.join(os.path.expanduser("~"), ".claude")).strip()
CLAUDE_PROJECTS_DIR = os.path.join(CLAUDE_HOME, "projects")
CLAUDE_SCAN_CAP = _CFG.getint("limits", "claude_scan_cap") or 6000

# ---- native session state detection / notifications ----
IDLE_DEBOUNCE = _CFG.getfloat("detect", "idle_debounce") or 8.0
PLAN_THRESHOLD = _CFG.getint("detect", "plan_threshold") or 3
# ---- external push notify ----
NOTIFY_ENABLED = _CFG.getboolean("notify", "enabled")
NOTIFY_TG_TOKEN = (_cfg_get("notify", "telegram_token")).strip()
NOTIFY_TG_CHAT = (_cfg_get("notify", "telegram_chat_id")).strip()
NOTIFY_BARK_KEY = (_cfg_get("notify", "bark_key")).strip()
NOTIFY_WEBHOOK_URL = (_cfg_get("notify", "webhook_url")).strip()
NOTIFY_WEBHOOK_SECRET = (_cfg_get("notify", "webhook_secret")).strip()
_ev = (_cfg_get("notify", "events")).strip() or "confirm,done"
NOTIFY_EVENTS = {e.strip() for e in _ev.replace(";", ",").split(",") if e.strip()}
NOTIFY_MIN_INTERVAL = _CFG.getfloat("notify", "min_interval") or 30.0
NOTIFY_TIMEOUT = 6.0
# 本机 Windows 桌面 toast(通知中心)。与 Telegram/Bark/webhook 并列的独立推送通道;
# 仅 Windows 生效,其它平台静默。受同一 NOTIFY_ENABLED + NOTIFY_EVENTS 门槛与 _push 去抖控制。
NOTIFY_DESKTOP_TOAST = _CFG.getboolean("notify", "desktop_toast")

# ---- auth / session (会话化登录) ----
SESSION_TTL = _CFG.getint("security", "session_ttl") or 86400   # 登录会话有效期(秒)
MAX_FAIL = _CFG.getint("security", "max_fail")                  # 连续失败 N 次锁定;0 = 关闭限速(走隧道建议)
LOCKOUT_SECS = _CFG.getint("security", "lockout_secs") or 300   # 锁定时长(秒)
COOKIE_SECURE = _CFG.getboolean("security", "cookie_secure")    # 1=带 Secure(需走 HTTPS 入口)



# ---------- binary discovery ----------
def _prefer_windows_cmd(path):
    if os.name != "nt" or not path:
        return path
    root, ext = os.path.splitext(path)
    if ext.lower() in (".cmd", ".bat", ".exe"):
        return path
    for suffix in (".cmd", ".exe", ".bat", ".ps1"):
        cand = path + suffix
        if os.path.isfile(cand):
            return cand
    return path


def resolve_cli_bin(name, override=None):
    if override and os.path.isfile(override):
        return _prefer_windows_cmd(override)
    try:
        cmd = ("where %s" % name) if os.name == "nt" else ("command -v %s" % name)
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=10).decode(errors="replace")
        for line in out.splitlines():
            shim = _prefer_windows_cmd(line.strip())
            if shim and os.path.isfile(shim):
                return shim
    except Exception:
        pass
    return None


def resolve_claude_bin(override=None):
    return resolve_cli_bin("claude", override)


def resolve_codex_bin(override=None):
    return resolve_cli_bin("codex", override)


def _script_argv(path, *args):
    if not path:
        return []
    ext = os.path.splitext(path)[1].lower()
    if os.name == "nt" and ext == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path] + list(args)
    return [path] + list(args)


def codex_argv(*args):
    if CODEX_BIN:
        base = os.path.dirname(CODEX_BIN)
        js = os.path.join(base, "node_modules", "@openai", "codex", "bin", "codex.js")
        if os.path.isfile(js):
            node = os.path.join(base, "node.exe") if os.name == "nt" else os.path.join(base, "node")
            if not os.path.isfile(node):
                node = "node"
            return [node, js] + list(args)
    return _script_argv(CODEX_BIN, *args)


def is_codex_backend(backend):
    return backend in ("codex", "codex_native")


def is_claude_backend(backend):
    return backend in ("claude", "native", "claude_native")


def normalize_backend(backend):
    if is_codex_backend(backend):
        return "codex_native"
    if is_claude_backend(backend):
        return "claude_native"
    if CODEX_BIN:
        return "codex_native"
    return "claude_native"


if _STOP_OR_HELP:
    # stop/help must not require a working install (bins are irrelevant there)
    CLAUDE_BIN = None
    CODEX_BIN = None
    BACKENDS = {}
else:
    CLAUDE_BIN = resolve_claude_bin(_cfg_get("binaries", "claude").strip() or None)
    CODEX_BIN = resolve_codex_bin(_cfg_get("binaries", "codex").strip() or None)
    BACKENDS = {}
    if CLAUDE_BIN and os.path.isfile(CLAUDE_BIN):
        BACKENDS["claude_native"] = {"bin": CLAUDE_BIN, "label": "Claude"}
    if CODEX_BIN and os.path.isfile(CODEX_BIN):
        BACKENDS["codex_native"] = {"bin": CODEX_BIN, "label": "Codex"}
    if not BACKENDS:
        print("ERROR: Neither Claude CLI nor Codex CLI was found. Install one or set [binaries] in config.ini.")
        sys.exit(1)

# ---------- auth: users, password hashing, session tokens ----------
# auth.txt 每行一个用户 "用户名:凭证"。凭证可以是:
#   * 明文(兼容旧版,如 claude:password123)
#   * 哈希 "$pbkdf2$<iters>$<salt_b64>$<hash_b64>"(推荐;用 hash_password() 生成)
# 行首 # 视为注释,空行忽略;多行 = 多用户。
USERS = {}
_legacy_user = None
try:
    with open(AUTH_FILE, "r", encoding="utf-8") as _f:
        for _raw in _f:
            ln = _raw.strip()
            if not ln or ln.startswith("#") or ":" not in ln:
                continue
            _u, _p = ln.split(":", 1)
            USERS[_u.strip()] = _p
            if _legacy_user is None:
                _legacy_user = _u.strip()
except OSError:
    pass
if not USERS and not _STOP_OR_HELP:
    print("ERROR: %s 没有有效的 用户名:凭证 行" % AUTH_FILE); sys.exit(1)
# 仅用于内部 web->manager 调用(manager 信任本机)与启动日志;对外登录走 USERS。
CRED = ("%s:%s" % (_legacy_user, USERS.get(_legacy_user, ""))) if _legacy_user else ":"
EXPECTED_AUTH = "Basic " + base64.b64encode(CRED.encode()).decode()


def hash_password(password, iters=120000):
    """生成 "$pbkdf2$iters$salt_b64$hash_b64" 哈希,写入 auth.txt 即可。命令行:
       python -c "import common; print(common.hash_password('你的密码'))" """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return "$pbkdf2$%d$%s$%s" % (iters, base64.b64encode(salt).decode(),
                                 base64.b64encode(dk).decode())


def verify_password(password, stored):
    """校验密码;支持 $pbkdf2$ 哈希与明文(旧版)。常量时间比较。"""
    if not stored or not password:
        return False
    if stored.startswith("$pbkdf2$"):
        parts = stored.split("$")
        if len(parts) != 5:
            return False
        try:
            iters = int(parts[2])
            salt = base64.b64decode(parts[3])
            want = base64.b64decode(parts[4])
        except Exception:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, want)
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))


def _load_or_create_session_secret():
    """会话签名密钥,持久化到 STATE_DIR,使已签发的 token 在 web 重启后仍有效。"""
    path = os.path.join(STATE_DIR, "session_secret")
    try:
        with open(path, "r", encoding="utf-8") as f:
            sec = f.read().strip()
        if sec:
            return sec
    except OSError:
        pass
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        sec = secrets.token_hex(32)
        with open(path, "w", encoding="utf-8") as f:
            f.write(sec)
        return sec
    except OSError:
        return ""   # 回退:用一次性临时密钥(token 不跨重启)


_SESSION_SECRET = (_load_or_create_session_secret() or secrets.token_hex(32)).encode("utf-8")


def make_session_token(user):
    """签发无状态 HMAC token: base64(payload).sig,payload 含 user 与过期时间。"""
    payload = {"u": user, "exp": int(time.time()) + SESSION_TTL}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    pb = base64.urlsafe_b64encode(body).decode("ascii")
    sig = hmac.new(_SESSION_SECRET, pb.encode("ascii"), hashlib.sha256).hexdigest()
    return pb + "." + sig


def verify_session_token(token):
    """token 有效且未过期则返回用户名,否则 None。"""
    if not token or "." not in token:
        return None
    pb, _, sig = token.partition(".")
    expect = hmac.new(_SESSION_SECRET, pb.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(pb.encode("ascii")).decode("utf-8"))
        exp = int(payload.get("exp", 0))
    except Exception:
        return None
    if exp < time.time():
        return None
    u = payload.get("u")
    return u if (isinstance(u, str) and u in USERS) else None


def session_cookie_header(name, value, max_age=SESSION_TTL, secure=COOKIE_SECURE):
    """构造 Set-Cookie 值: HttpOnly + SameSite=Lax(+可选 Secure)。
    secure 默认取 COOKIE_SECURE;明文 HTTP(局域网)监听器应传 False,否则浏览器不回传 Cookie。"""
    parts = ["%s=%s" % (name, value), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % max_age]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


# ---------- 登录失败限速(按 访客标识/IP,内存) ----------
# key 由调用方决定:内网穿透下优先用 ac_visitor cookie(每访问者唯一),
# 缺失时回退来源 IP。这样穿透后不同访问者各有各的失败计数,不会互相连坐锁定。
_fail_lock = threading.Lock()
_fail_state = {}   # key -> {"fails": n, "locked_until": ts}


def check_lockout(key):
    """返回 (是否允许尝试, 还需等待秒数)。max_fail<=0 时关闭限速(走隧道时建议如此)。"""
    if MAX_FAIL <= 0:
        return True, 0
    with _fail_lock:
        st = _fail_state.get(key)
        if st:
            remain = st.get("locked_until", 0) - time.time()
            if remain > 0:
                return False, int(remain) + 1
    return True, 0


def register_login_fail(key):
    """记录一次失败;达到 MAX_FAIL 则锁定 LOCKOUT_SECS 秒。返回是否触发了锁定。max_fail<=0 时为空操作。"""
    if MAX_FAIL <= 0:
        return False
    with _fail_lock:
        st = _fail_state.setdefault(key, {"fails": 0, "locked_until": 0})
        st["fails"] += 1
        if st["fails"] >= MAX_FAIL:
            st["locked_until"] = time.time() + LOCKOUT_SECS
            st["fails"] = 0
            return True
    return False


def register_login_success(key):
    with _fail_lock:
        _fail_state.pop(key, None)


# ---------- 应用层 HTTPS(自签证书;配合 tcp 隧道做端到端加密) ----------
def ensure_self_signed_cert(cert_path, key_path, cn=None):
    """确保自签证书存在;不存在则用 cryptography 生成(CN/SAN=cn,有效期 10 年)。
    依赖可选库 cryptography(pip install cryptography);也可自己在 config.ini 用
    [server] cert_file / key_file 指定已有证书(如 Let's Encrypt)。已存在则跳过。"""
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime as _dt
    except ImportError:
        raise RuntimeError("生成自签证书需要 cryptography 库: pip install cryptography"
                           "(或在 config.ini 的 [server] cert_file/key_file 指定已有证书)")
    cn = (cn or CERT_CN or "agents-cockpit").strip() or "agents-cockpit"
    try:
        os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    except OSError:
        pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = _dt.datetime.utcnow()
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(days=1))
            .not_valid_after(now + _dt.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(cn)]), critical=False)
            .sign(key, hashes.SHA256()))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print("已生成自签 HTTPS 证书(CN=%s): %s" % (cn, cert_path))


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
    Windows: taskkill /F /T reaps a whole process tree. POSIX: SIGTERM->SIGKILL."""
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


def _pid_alive(pid):
    """True if a process with this pid currently exists."""
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.OpenProcess.restype = ctypes.c_void_p
            k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            k.CloseHandle.argtypes = [ctypes.c_void_p]
            h = k.OpenProcess(0x1000, 0, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            k.CloseHandle(h)
            return True
        except Exception:
            return True   # unsure -> assume alive (a kill attempt is still safe)
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


# ---------- Win32 Job Object: kill the whole tree when this process dies ----------
# The web process binds itself into a Job Object flagged KILL_ON_JOB_CLOSE. Every
# child it then spawns (web -> manager -> claude) inherits job membership,
# so if the web process dies for ANY reason (crash, window close, TerminateProcess)
# the kernel terminates the entire job and nothing is orphaned. Without this those
# children are detached (CREATE_NO_WINDOW, no console) and survive a web death.
_JOB_HANDLE = [None]   # keep the handle alive for our whole lifetime; never close it


def bind_to_kill_on_close_job():
    """Windows only. Returns True on success. Best-effort: on any failure (e.g.
    already inside a non-nestable job on an old host) it prints a line and returns
    False, leaving the sentinel / `app.py --stop` path as the cleanup fallback.
    POSIX: no-op (the start.sh trap + SIGTERM handlers cover it)."""
    if os.name != "nt":
        return False
    _JOB_HANDLE[0] = _create_kill_on_close_job()
    return _JOB_HANDLE[0] is not None


def _create_kill_on_close_job():
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]
        k32.GetCurrentProcess.restype = wintypes.HANDLE

        h = k32.CreateJobObjectW(None, None)
        if not h:
            print("[job] CreateJobObject 失败(err=%d),仅依赖 stop 命令清理" % ctypes.get_last_error())
            return None

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]

        class _BASIC_LIMITS(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_void_p),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _EXT_LIMITS(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _BASIC_LIMITS),
                        ("IoInfo", _IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = _EXT_LIMITS()
        info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        JobObjectExtendedLimitInformation = 9
        if not k32.SetInformationJobObject(h, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            print("[job] SetInformationJobObject 失败(err=%d),仅依赖 stop 命令清理" % ctypes.get_last_error())
            return None
        if not k32.AssignProcessToJobObject(h, k32.GetCurrentProcess()):
            print("[job] AssignProcessToJobObject 失败(err=%d) — 可能已在旧式 job 内;仅依赖 stop 命令清理"
                  % ctypes.get_last_error())
            return None
        return h
    except Exception as e:
        print("[job] Job Object 建立失败(%s),仅依赖 stop 命令清理" % e)
        return None


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
    if STOPPING:
        return False
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


# ---------- full-stop helpers (used by `app.py --stop`) ----------
def _http_post(port, path, auth=""):
    """POST {} to 127.0.0.1:port/path with the given Basic auth. Returns True on
    any HTTP response, False on connection refused (server down). Best-effort."""
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        c.request("POST", path, body=b"{}",
                  headers={"Authorization": auth, "Content-Type": "application/json"})
        c.getresponse().read(); c.close()
        return True
    except OSError:
        return False


def _write_stop_sentinel():
    """Drop STATE_DIR/stop.sentinel. The supervisor loop (start.cmd/start.sh)
    consumes it on the next iteration and stops relaunching. Only written when
    the web layer is already unreachable (so exit code 42 can't carry the stop)."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, STOP_SENTINEL), "w") as f:
            f.write("stop\n")
    except OSError:
        pass


def perform_shutdown():
    """Full teardown, run by `app.py --stop` in a separate process. Compensating
    steps — each covers for the ones above it failing:
      1. POST web /api/_stop  -> web freezes its watchdog, asks manager to _exit,
                                 exits code 42 (supervisor stops relaunching).
         (web unreachable)     -> write stop.sentinel so the supervisor still stops.
      2. POST manager /api/_exit -> kill_all() + manager exit (manager trusts localhost).
      3. kill_registry_sessions  -> taskkill any recorded legacy session pid still alive
                                    (soft-exit orphans / manager already dead).
    Returns a port-free report."""
    web_ok = _http_post(PICKER_PORT, "/api/_stop", EXPECTED_AUTH)
    if not web_ok:
        _write_stop_sentinel()
    _http_post(MANAGER_PORT, "/api/_exit", EXPECTED_AUTH)
    kill_registry_sessions()
    # web exits with code 42 asynchronously AFTER its own manager-roundtrip, so
    # poll for both ports to actually free (up to ~6s) rather than a fixed sleep
    # that can report a misleading "still busy" while shutdown is mid-flight.
    deadline = time.time() + 6.0
    while time.time() < deadline:
        if not _port_alive(PICKER_PORT) and not _port_alive(MANAGER_PORT):
            break
        time.sleep(0.25)
    # last-resort: kill a detached background supervisor so stop.cmd leaves
    # nothing behind. The supervisor normally exits on its own via exit-42 /
    # stop.sentinel, but if it is stuck this guarantees teardown.
    sup_pid_path = os.path.join(STATE_DIR, "supervisor.pid")
    try:
        with open(sup_pid_path, "r") as f:
            sup_pid = int((f.read() or "0").strip())
        if sup_pid:
            _kill_pid(sup_pid)
    except (OSError, ValueError):
        pass
    try:
        os.unlink(sup_pid_path)
    except OSError:
        pass
    return {"web_port_free": not _port_alive(PICKER_PORT),
            "manager_port_free": not _port_alive(MANAGER_PORT)}


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
    """Project a live native session dict onto the JSON-serializable registry shape."""
    ns = s.get("native")
    backend = s.get("backend") or normalize_backend("")
    provider = s.get("provider") or ("codex" if is_codex_backend(backend) else "claude")
    return {
        "port": None,
        "pid": None,
        "dir": s.get("dir", ""),
        "backend": backend,
        "provider": provider,
        "title": s.get("title", ""),
        "started": s.get("started", time.time()),
        "mode": s.get("mode", "new"),
        "yolo": bool(getattr(ns, "yolo", False) if ns else s.get("yolo")),
        "session_id": getattr(ns, "claude_sid", None) or getattr(ns, "thread_id", None) or s.get("session_id"),
        "thread_id": getattr(ns, "thread_id", None) or s.get("thread_id"),
        "cols": 0,
        "rows": 0,
    }


def kill_registry_sessions():
    """Best-effort sweep: tree-kill every legacy pid recorded in the registry.
    Used by `app.py --stop` to reap sessions the manager can no longer reach (it
    already died) or that a soft-exit deliberately orphaned. Safe on already-dead
    pids (taskkill/kill just no-op). Returns the list of pids it attempted."""
    reg = registry_load()
    sess = reg.get("sessions") if isinstance(reg, dict) else None
    if not isinstance(sess, dict) or not sess:
        return []
    tried = []
    for sid, e in sess.items():
        pid = e.get("pid") if isinstance(e, dict) else None
        if pid:
            _kill_pid(pid)
            tried.append((sid, pid))
    return tried


# ---------- history ----------
def iso_to_epoch(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def _claude_user_text(o):
    """Pull the human-typed text out of a Claude 'user' record."""
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


def load_claude_transcript_events(claude_sid, cap=100):
    """Reconstruct native replay events from ~/.claude/projects/*/<session>.jsonl."""
    out = []
    target = (claude_sid or "").strip() + ".jsonl"
    if not target or not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return out
    path = None
    for dp, _dirs, fs in os.walk(CLAUDE_PROJECTS_DIR):
        if target in fs:
            path = os.path.join(dp, target)
            break
    if not path:
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        t = o.get("type")
        if t not in ("user", "assistant"):
            continue
        if t == "user" and _transcript_is_human_turn(o) and out:
            out.append({"type": "result"})
        out.append(o)
    if out:
        out.append({"type": "result"})
    return out[-cap:] if cap else out


def _transcript_is_human_turn(o):
    """True if a Claude transcript 'user' record is a human message, not tool_result."""
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    if isinstance(c, list):
        has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in c)
        has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
        return has_text and not has_result
    return False


def load_claude_history():
    """Scan Claude transcripts and mark every restorable item as a native web session."""
    out = []
    if not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return out
    for dp, _dirs, fs in os.walk(CLAUDE_PROJECTS_DIR):
        for fn in fs:
            if not fn.endswith(".jsonl"):
                continue
            if os.path.basename(dp) == "subagents" or fn.startswith("agent-"):
                continue
            sid = fn[:-6]
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
            title = (ai_title or first_user or "(Untitled)").strip()
            out.append({
                "session_id": sid,
                "cwd": cwd,
                "ts": iso_to_epoch(ts_str),
                "title": title,
                "originator": "",
                "backend": "claude_native",
            })
    return out


def load_history(limit=60):
    out = load_claude_history()
    if CODEX_BIN:
        try:
            from codex_native import list_thread_history
            out.extend(list_thread_history(limit=limit, archived=False))
        except Exception as e:
            print("WARN: failed to load Codex history: %s" % e)
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out[:limit]


def delete_history(sid, backend=None):
    """Delete one Claude transcript by session id. Running sessions are not touched."""
    sid = (sid or "").strip()
    res = {"deleted": False, "session_file": None}
    if is_codex_backend(backend):
        if not sid:
            return res
        try:
            from codex_native import delete_thread
            res["deleted"] = bool(delete_thread(sid))
            res["session_file"] = sid
        except Exception:
            pass
        return res
    if not sid or not os.path.isdir(CLAUDE_PROJECTS_DIR):
        return res
    target = sid + ".jsonl"
    for dp, _dirs, fs in os.walk(CLAUDE_PROJECTS_DIR):
        if target in fs:
            p = os.path.join(dp, target)
            try:
                os.unlink(p)
                res["deleted"] = True
                res["session_file"] = p
            except OSError:
                pass
            break
    return res


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
    else:  # Other providers may store config as TOML and auth separately.
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
    ns = s.get("native")
    backend = s.get("backend") or normalize_backend("")
    provider = s.get("provider") or ("codex" if is_codex_backend(backend) else "claude")
    session_id = getattr(ns, "claude_sid", None) or getattr(ns, "thread_id", None) or s.get("session_id")
    return {"sid": sid, "dir": s["dir"], "title": getattr(ns, "convo_title", None) or s["title"], "mode": s["mode"],
            "session_id": session_id, "thread_id": getattr(ns, "thread_id", None) or s.get("thread_id"),
            "started": s["started"], "session_path": "/t/%s/" % sid,
            "backend": backend, "provider": provider, "native": True,
            "state": ns.state() if ns else "idle",
            "yolo": bool(getattr(ns, "yolo", False) if ns else s.get("yolo")),
            "last_input_ts": getattr(ns, "last_activity", 0) if ns else 0,
            "last_output_ts": getattr(ns, "last_activity", 0) if ns else 0,
            "cols": 0, "rows": 0}


# ---------- external push notifications (Telegram / Bark / webhook) ----------
def _notify_enabled_for(event):
    return NOTIFY_ENABLED and event in NOTIFY_EVENTS


def notify_result_text(events, limit=3500):
    """Return the latest assistant text message, excluding thinking/tool process."""
    for ev in reversed(events or []):
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        parts = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
        text = "\n".join(p for p in parts if p).strip()
        if text:
            if limit and len(text) > limit:
                suffix = "\n\n...(result text truncated)"
                text = text[:max(0, limit - len(suffix))].rstrip() + suffix
            return text
    return ""


def _ps_quote(s):
    """转义字符串以安全嵌入 PowerShell 单引号字面量(' → ''),并压平换行(toast 文本一行)。"""
    return str(s).replace("\r", " ").replace("\n", " ").replace("'", "''")


# Windows toast:GetTemplateContent(ToastText02) 取系统模板 → 新 XmlDocument 载入 → .Item(n).InnerText
# 填两行文本(InnerText 自动做 XML 转义,故标题/正文无需额外 Escape,只需 _ps_quote 转义 PS 单引号)。
# AUMID 用系统已注册的 Microsoft.Windows.Explorer(自定义 AUMID 需配开始菜单快捷方式,门槛高),
# 失败再试 RunDialog,最后退到无参 CreateToastNotifier()。
_DESKTOP_TOAST_PS = r"""[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$t='<T>'; $b='<B>'
$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($tpl.GetXml())
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).InnerText = $t
$nodes.Item(1).InnerText = $b
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$ok=$false
foreach($a in @('Microsoft.Windows.Explorer','Microsoft.Windows.Shell.RunDialog')){
  try { [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($a).Show($toast); $ok=$true; break }
  catch {}
}
if(-not $ok){ try { [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier().Show($toast) } catch { exit 3 } }"""


def desktop_notify(title, body=""):
    """Windows 原生 toast(进通知中心,带横幅+声音)。经 PowerShell 调 WinRT;非 Windows / 未启用 /
    任何失败均静默返回 False。在 push_notify 内被调用,故复用上层 _push 的 per-event 去抖与
    _notify_enabled_for 门槛。用 -EncodedCommand(base64/UTF-16LE)传输整段脚本,彻底规避
    Python↔PowerShell 引号/反斜杠转义;标题与正文仅做单引号转义后注入占位符。"""
    if os.name != "nt" or not NOTIFY_DESKTOP_TOAST:
        return False
    title = (str(title).strip() or "notice")[:200]
    body = str(body).strip()[:400]
    try:
        script = _DESKTOP_TOAST_PS.replace("<T>", _ps_quote(title)).replace("<B>", _ps_quote(body))
        enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=8, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception as e:
        print("notify desktop toast failed: %s" % e)
        return False


def push_notify(title, body, event, webhook_body=None):
    """Fire-and-forget external push over every configured channel. Blocking HTTP — the
    caller (manager._notify_sender worker) is expected to run this off the main loop.
    Returns True if at least one channel returned 2xx. Silent on error (prints a line)."""
    if not _notify_enabled_for(event):
        return False
    # 本机 Windows 桌面 toast:与下面的 Telegram/Bark/webhook 并列的独立通道。
    # desktop_notify 内部自检平台+开关,非 Windows / 未启用时静默 no-op,不影响网络推送。
    try:
        desktop_notify(title, body)
    except Exception:
        pass
    ok = False
    full = (str(title) + "\n" + str(body)).strip()
    # --- Telegram Bot ---
    if NOTIFY_TG_TOKEN and NOTIFY_TG_CHAT:
        try:
            data = urllib.parse.urlencode({"chat_id": NOTIFY_TG_CHAT, "text": full}).encode()
            conn = http.client.HTTPSConnection("api.telegram.org", timeout=NOTIFY_TIMEOUT)
            try:
                conn.request("POST", "/bot%s/sendMessage" % NOTIFY_TG_TOKEN, body=data,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
                r = conn.getresponse(); r.read()
                ok = ok or 200 <= r.status < 300
            finally:
                conn.close()
        except Exception as e:
            print("notify telegram failed: %s" % e)
    # --- Bark (iOS): bare key -> api.day.app, or a full https URL ---
    if NOTIFY_BARK_KEY:
        try:
            if NOTIFY_BARK_KEY.lower().startswith("http"):
                pr = urllib.parse.urlsplit(NOTIFY_BARK_KEY)
                scheme, host, basepath = pr.scheme or "https", pr.netloc, pr.path.rstrip("/")
            else:
                scheme, host, basepath = "https", "api.day.app", "/" + NOTIFY_BARK_KEY.strip("/")
            path = "%s/%s/%s" % (basepath,
                                 urllib.parse.quote(str(title).strip() or "notice", safe=""),
                                 urllib.parse.quote(str(body).strip(), safe=""))
            cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            conn = cls(host, timeout=NOTIFY_TIMEOUT)
            try:
                conn.request("GET", path); r = conn.getresponse(); r.read()
                ok = ok or 200 <= r.status < 300
            finally:
                conn.close()
        except Exception as e:
            print("notify bark failed: %s" % e)
    # --- webhook (auto-detects Feishu/Lark schema vs generic JSON) ---
    if NOTIFY_WEBHOOK_URL:
        try:
            if _webhook_send(NOTIFY_WEBHOOK_URL, NOTIFY_WEBHOOK_SECRET,
                             title, body, event, webhook_body=webhook_body):
                ok = True
        except Exception as e:
            print("notify webhook failed: %s" % e)
    return ok


def _webhook_is_feishu(url):
    u = url.lower()
    return "feishu.cn" in u or "larksuite" in u or "open-apis/bot" in u


def _webhook_send(url, secret, title, body, event, webhook_body=None):
    """POST a notification to a webhook. Auto-detects Feishu/Lark custom-bot schema
    ({msg_type, content}) vs a generic {title, body, event} JSON. For Feishu, `secret`
    is used as the signing key (enable "自定义签名" on the bot); for generic webhooks it
    rides in the X-Notify-Secret header. Returns True only if the endpoint accepted the
    message (HTTP 2xx AND, for Feishu, body code == 0)."""
    pr = urllib.parse.urlsplit(url)
    path_q = (pr.path or "/") + (("?" + pr.query) if pr.query else "")
    cls = http.client.HTTPSConnection if pr.scheme == "https" else http.client.HTTPConnection
    webhook_text = body if webhook_body is None else webhook_body
    if _webhook_is_feishu(url):
        text = (str(title) + "\n" + str(webhook_text)).strip()
        data = {"msg_type": "text", "content": {"text": text}}
        if secret:   # Feishu signature: HMAC-SHA256 over "{ts}\n{secret}"
            ts = str(int(time.time()))
            sign = base64.b64encode(
                hmac.new(("%s\n%s" % (ts, secret)).encode("utf-8"),
                         digestmod=hashlib.sha256).digest()).decode("utf-8")
            data["timestamp"] = ts
            data["sign"] = sign
        payload = json.dumps(data).encode()
    else:
        payload = json.dumps({"title": str(title), "body": str(webhook_text), "event": event}).encode()
    conn = cls(pr.netloc, timeout=NOTIFY_TIMEOUT)
    try:
        conn.request("POST", path_q, body=payload, headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        raw = r.read()
        success = 200 <= r.status < 300
        if success and _webhook_is_feishu(url):
            # Feishu answers HTTP 200 with a body code on business errors (keyword /
            # signature / ip mismatch) — surface those so they're debuggable.
            try:
                j = json.loads(raw.decode("utf-8", "replace"))
                code = j.get("code", j.get("StatusCode", 0))
                if code not in (0, None):
                    success = False
                    print("notify feishu rejected: %s" % (j.get("msg") or j.get("StatusMessage") or raw[:200]))
            except Exception:
                pass
        return success
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
        # index.html 在开发期经常改动,且每次请求都重新读盘;禁用浏览器缓存,
        # 避免用户看到旧页面(如顶部栏样式不生效)。文件很小,no-store 无副作用。
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False
