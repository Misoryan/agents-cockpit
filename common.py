# -*- coding: utf-8 -*-
"""
Agents Cockpit — shared infrastructure (used by both web and manager processes).

Constants/paths, env, binary discovery, auth, websocket frame helpers, history
loaders, CC-Switch read-only integration, folder browse, the session registry,
port/PID helpers, and the manager-spawn helpers.

This module must NOT import web.py / manager.py (keeps the dependency graph
acyclic: app -> {web, manager} -> common).
"""
import os
import threading
import sys
import time
import configparser
import secrets

import common_auth
import common_binaries
import common_browse
import common_ccswitch
import common_history
import common_http
import common_notify
import common_process
import common_registry
import common_users
from common_ws import WS_GUID, ws_accept_key, ws_recv, ws_send

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
[users]
data_dir = .agent-cockpit/users
default_workspace_root = .agent-cockpit/users/{uid}/workspace
allow_unconfigured_paths = 1
primary_user_uses_default_homes = 1
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
[codex_dynamic_tools]
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
csrf_origin_check = 1
csrf_allow_missing_origin = 1
allowed_origins =
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
ASSETS_DIR = os.path.join(HERE, "assets")
CREATE_NO_WINDOW = 0x08000000
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
_ud = (_cfg_get("users", "data_dir") or os.path.join(STATE_DIR, "users")).strip()
USER_DATA_DIR = os.path.join(HERE, _ud) if not os.path.isabs(_ud) else _ud
DEFAULT_WORKSPACE_ROOT = (_cfg_get("users", "default_workspace_root") or "").strip()
ALLOW_UNCONFIGURED_PATHS = _CFG.getboolean("users", "allow_unconfigured_paths")
PRIMARY_USER_USES_DEFAULT_HOMES = _CFG.getboolean("users", "primary_user_uses_default_homes")
STOP_SENTINEL = "stop.sentinel"   # written by app.py --stop when the web layer is unreachable
REG_LOCK = common_registry.REG_LOCK               # only guards disk writes; never nest under manager._lock
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
CSRF_ORIGIN_CHECK = _CFG.getboolean("security", "csrf_origin_check")
CSRF_ALLOW_MISSING_ORIGIN = _CFG.getboolean("security", "csrf_allow_missing_origin")
CSRF_ALLOWED_ORIGINS = common_auth.split_allowed_origins(_cfg_get("security", "allowed_origins"))



# ---------- binary discovery ----------
def _prefer_windows_cmd(path):
    return common_binaries.prefer_windows_cmd(path)


def resolve_cli_bin(name, override=None):
    return common_binaries.resolve_cli_bin(name, override)


def resolve_claude_bin(override=None):
    return common_binaries.resolve_claude_bin(override)


def resolve_codex_bin(override=None):
    return common_binaries.resolve_codex_bin(override)


def _script_argv(path, *args):
    return common_binaries.script_argv(path, *args)


def codex_argv(*args):
    return common_binaries.codex_argv(CODEX_BIN, *args)


def is_codex_backend(backend):
    return common_binaries.is_codex_backend(backend)


def is_claude_backend(backend):
    return common_binaries.is_claude_backend(backend)


def normalize_backend(backend):
    return common_binaries.normalize_backend(backend, CODEX_BIN)


CLAUDE_BIN, CODEX_BIN, BACKENDS = common_binaries.discover_backends(
    _cfg_get("binaries", "claude").strip() or None,
    _cfg_get("binaries", "codex").strip() or None,
    stop_or_help=_STOP_OR_HELP,
)
if not _STOP_OR_HELP and not BACKENDS:
    print("ERROR: Neither Claude CLI nor Codex CLI was found. Install one or set [binaries] in config.ini.")
    sys.exit(1)

# ---------- auth: users, password hashing, session tokens ----------
# auth.txt format stays compatible: "user:credential", where credential may be
# plaintext or "$pbkdf2$<iters>$<salt_b64>$<hash_b64>" from hash_password().
USERS, _legacy_user = common_auth.load_users(AUTH_FILE)
if not USERS and not _STOP_OR_HELP:
    print("ERROR: %s has no valid user:credential lines" % AUTH_FILE); sys.exit(1)
# Used only for local web->manager/control calls; browser login uses USERS.
CRED = ("%s:%s" % (_legacy_user, USERS.get(_legacy_user, ""))) if _legacy_user else ":"
EXPECTED_AUTH = common_auth.expected_basic_auth(_legacy_user, USERS)

hash_password = common_auth.hash_password
verify_password = common_auth.verify_password


def _load_or_create_session_secret():
    """Load or create the HMAC secret persisted under STATE_DIR."""
    return common_auth.load_or_create_session_secret(STATE_DIR)


_SESSION_SECRET = (_load_or_create_session_secret() or secrets.token_hex(32)).encode("utf-8")
INTERNAL_AUTH = common_auth.internal_auth(_SESSION_SECRET)


def verify_internal_auth(header):
    """Validate the private web/manager/gate bearer token."""
    return common_auth.verify_internal_auth(header, INTERNAL_AUTH)


def make_session_token(user):
    """Sign a stateless HMAC token containing user and expiry."""
    return common_auth.make_session_token(user, _SESSION_SECRET, SESSION_TTL)


def verify_session_token(token):
    """Return the user name for a valid, unexpired token; otherwise None."""
    return common_auth.verify_session_token(token, _SESSION_SECRET, USERS)


def session_cookie_header(name, value, max_age=SESSION_TTL, secure=COOKIE_SECURE):
    """Build Set-Cookie with HttpOnly + SameSite=Lax and optional Secure."""
    return common_auth.session_cookie_header(name, value, max_age, secure=secure)


def request_origin_allowed(headers):
    return common_auth.request_origin_allowed(
        headers,
        allowed_origins=CSRF_ALLOWED_ORIGINS,
        allow_missing=CSRF_ALLOW_MISSING_ORIGIN,
    )


# ---------- per-user local state / workspace roots ----------
def _user_settings():
    return common_users.UserSettings(
        base_dir=HERE,
        user_data_dir=USER_DATA_DIR,
        default_workspace_root=DEFAULT_WORKSPACE_ROOT,
        allow_unconfigured_paths=ALLOW_UNCONFIGURED_PATHS,
        primary_user_uses_default_homes=PRIMARY_USER_USES_DEFAULT_HOMES,
        claude_home=CLAUDE_HOME,
        users=USERS,
    )


safe_user_id = common_users.safe_user_id


def _format_user_path(template, user, uid):
    return common_users.format_user_path(template, user, uid, _user_settings())


def user_state_dir(user):
    return common_users.user_state_dir(user, _user_settings())


def primary_user():
    return common_users.primary_user(_user_settings())


def user_uses_default_homes(user):
    return common_users.user_uses_default_homes(user, _user_settings())


def user_claude_home(user, state_dir=None):
    return common_users.user_claude_home(user, _user_settings(), state_dir=state_dir)


def user_codex_home(user, state_dir=None):
    return common_users.user_codex_home(user, _user_settings(), state_dir=state_dir)


def user_profile_path(user):
    return common_users.user_profile_path(user, _user_settings())


def load_user_profile(user):
    return common_users.load_user_profile(user, _user_settings())


def user_workspace_roots(user):
    return common_users.user_workspace_roots(user, _user_settings())


def ensure_user_dirs(user):
    return common_users.ensure_user_dirs(user, _user_settings())


def user_context(user):
    return common_users.user_context(user, _user_settings())


def request_user(handler):
    return common_users.request_user(handler, _user_settings(), verify_session_token)


def path_allowed_for_user(user, path):
    return common_users.path_allowed_for_user(user, path, _user_settings())


def workspace_overview(user):
    return common_users.workspace_overview(user, _user_settings())


def codex_dynamic_tool_mappings():
    """Return explicit dynamic-tool passthrough mappings from config.ini."""
    try:
        items = _CFG.items("codex_dynamic_tools")
    except (configparser.NoSectionError, configparser.NoOptionError):
        return {}
    out = {}
    for key, value in items:
        key = str(key or "").strip()
        value = str(value or "").strip()
        if key and value:
            out[key] = value
    return out


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


# ---------- net / process / manager helpers ----------
def _process_settings():
    return common_process.ProcessSettings(
        picker_port=PICKER_PORT,
        manager_host=MANAGER_HOST,
        manager_port=MANAGER_PORT,
        run_mode=RUN_MODE,
        base_dir=HERE,
        create_no_window=CREATE_NO_WINDOW,
        state_dir=STATE_DIR,
        stop_sentinel=STOP_SENTINEL,
        expected_auth=EXPECTED_AUTH,
        manager_path=_manager_path(),
    )


def _is_local_client(addr):
    return common_process.is_local_client(addr)


def lan_ip():
    return common_process.lan_ip()


def wait_port(port, timeout=5.0):
    return common_process.wait_port(port, timeout=timeout)


def _port_alive(port, timeout=0.5):
    return common_process.port_alive(port, timeout=timeout)


def _kill_pid(pid):
    return common_process.kill_pid(pid, CREATE_NO_WINDOW)


def _pid_alive(pid):
    return common_process.pid_alive(pid)


# ---------- Win32 Job Object: kill the whole tree when this process dies ----------
def bind_to_kill_on_close_job():
    return common_process.bind_to_kill_on_close_job()


def _create_kill_on_close_job():
    return common_process.create_kill_on_close_job()


# ---------- manager spawn / liveness (used by web) ----------
def _manager_path():
    return sys.argv[0] if sys.argv and sys.argv[0] else __file__


def _manager_argv():
    return common_process.manager_argv(_process_settings())


def manager_available():
    return common_process.manager_available(_process_settings())


def ensure_manager():
    return common_process.ensure_manager(_process_settings(), is_stopping=lambda: STOPPING)


# ---------- full-stop helpers (used by `app.py --stop`) ----------
def _http_post(port, path, auth=""):
    return common_process.http_post(port, path, auth=auth)


def _write_stop_sentinel():
    return common_process.write_stop_sentinel(_process_settings())


def perform_shutdown():
    return common_process.perform_shutdown(_process_settings(), kill_registry_sessions)


# ---------- websocket frame helpers (RFC 6455, minimal) ----------
# Re-exported from common_ws for compatibility with existing imports.


# ---------- persisted session registry (Phase B) ----------
def _registry_settings():
    return common_registry.RegistrySettings(
        registry_path=REGISTRY_PATH,
        scrollback_dir=SCROLLBACK_DIR,
        user_state_dir=user_state_dir,
    )


def _registry_path(user=None, state_dir=None):
    return common_registry.registry_path(user, state_dir, _registry_settings())


def registry_load(user=None, state_dir=None):
    """Return the raw registry object ({version, manager_pid, sessions:{sid->entry}}) or {}."""
    return common_registry.registry_load(user, state_dir, _registry_settings())


def _registry_write(obj, user=None, state_dir=None):
    """Atomic write under REG_LOCK. Never raises."""
    return common_registry.registry_write(obj, user, state_dir, _registry_settings())


def _registry_read_locked(user=None, state_dir=None):
    return common_registry.registry_read(user, state_dir, _registry_settings())


def registry_save(entries, user=None, state_dir=None):
    """Overwrite the whole sessions map (used by soft-exit snapshot). entries: {sid -> entry}."""
    return common_registry.registry_save(entries, os.getpid(), user, state_dir, _registry_settings())


def registry_upsert(sid, entry, user=None, state_dir=None):
    """Read-modify-write a single sid (safe under concurrent launch calls)."""
    return common_registry.registry_upsert(sid, entry, os.getpid(), user, state_dir, _registry_settings())


def _registry_write_unlocked(obj, user=None, state_dir=None):
    return common_registry.registry_write_unlocked(obj, user, state_dir, _registry_settings())


def registry_drop(sid, user=None, state_dir=None):
    """Remove one sid from registry + best-effort delete its scrollback log."""
    return common_registry.registry_drop(sid, user, state_dir, _registry_settings())


def registry_clear(user=None, state_dir=None):
    return common_registry.registry_clear(os.getpid(), user, state_dir, _registry_settings())


def _registry_safe_entry(sid, s):
    """Project a live native session dict onto the JSON-serializable registry shape."""
    ns = s.get("native")
    backend = s.get("backend") or normalize_backend("")
    provider = s.get("provider") or ("codex" if is_codex_backend(backend) else "claude")
    try:
        native_state = ns.state() if ns else s.get("state", "idle")
    except Exception:
        native_state = s.get("state", "idle")
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
        "state": native_state,
        "busy": bool(getattr(ns, "_busy", False)) if ns else bool(s.get("busy")),
        "current_turn_started_at": getattr(ns, "current_turn_started_at", None) if ns else s.get("current_turn_started_at"),
        "last_completed_at": getattr(ns, "last_completed_at", None) if ns else s.get("last_completed_at"),
        "last_activity": getattr(ns, "last_activity", None) if ns else s.get("last_activity"),
        "awaiting_plan_decision": bool(getattr(ns, "_awaiting_plan_decision", False)) if ns else bool(s.get("awaiting_plan_decision")),
        "session_id": getattr(ns, "claude_sid", None) or getattr(ns, "thread_id", None) or s.get("session_id"),
        "thread_id": getattr(ns, "thread_id", None) or s.get("thread_id"),
        "user": s.get("user") or getattr(ns, "user", ""),
        "uid": s.get("uid") or getattr(ns, "uid", ""),
        "state_dir": s.get("state_dir") or getattr(ns, "state_dir", ""),
        "claude_home": s.get("claude_home") or getattr(ns, "claude_home", None),
        "codex_home": s.get("codex_home") or getattr(ns, "codex_home", None),
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
def _history_settings():
    return common_history.HistorySettings(
        claude_home=CLAUDE_HOME,
        claude_scan_cap=CLAUDE_SCAN_CAP,
        codex_enabled=bool(CODEX_BIN),
    )


def iso_to_epoch(s):
    return common_history.iso_to_epoch(s)


def _claude_user_text(o):
    return common_history.claude_user_text(o)


def _claude_projects_dir(ctx=None):
    return common_history.claude_projects_dir(_history_settings(), ctx=ctx)


def load_claude_transcript_events(claude_sid, cap=100, ctx=None):
    return common_history.load_claude_transcript_events(claude_sid, _history_settings(), cap=cap, ctx=ctx)


def _transcript_is_human_turn(o):
    return common_history.transcript_is_human_turn(o)


def load_claude_history(ctx=None):
    return common_history.load_claude_history(_history_settings(), ctx=ctx)


def load_history(limit=60, ctx=None, live_codex=False, archived=False):
    return common_history.load_history(
        _history_settings(), limit=limit, ctx=ctx,
        live_codex=live_codex, archived=archived)


def delete_history(sid, backend=None, ctx=None):
    return common_history.delete_history(sid, _history_settings(), backend=backend, ctx=ctx,
                                         is_codex_backend_fn=is_codex_backend)


def recent_dirs(limit=30, ctx=None):
    return common_history.recent_dirs(_history_settings(), limit=limit, ctx=ctx)


# ---------- CC Switch integration (optional, read-only) ----------
def _ccswitch_settings():
    return common_ccswitch.CCSwitchSettings(
        db=CCSWITCH_DB,
        usage_ttl=CCSWITCH_USAGE_TTL,
        balance_ttl=CCSWITCH_BALANCE_TTL,
    )


def _toml_first(text, key):
    return common_ccswitch.toml_first(text, key)


def _ccswitch_provider_meta(sc_json, app_type):
    return common_ccswitch.provider_meta(sc_json, app_type)


def _ccswitch_open():
    return common_ccswitch.open_db(_ccswitch_settings())


def _day_start_epoch(now):
    return common_ccswitch.day_start_epoch(now)


def _month_start_epoch(now):
    return common_ccswitch.month_start_epoch(now)


def _usage_window(cur, since):
    return common_ccswitch.usage_window(cur, since)


def _usage_by_model(cur, since, limit=8):
    return common_ccswitch.usage_by_model(cur, since, limit=limit)


def ccswitch_overview():
    return common_ccswitch.overview(_ccswitch_settings())


def _zhipu_api_base(host):
    return common_ccswitch.zhipu_api_base(host)


def _ccswitch_current_zhipu():
    return common_ccswitch.current_zhipu(_ccswitch_settings())


def _ccswitch_balance_refresh(target_key, target_host):
    return common_ccswitch.balance_refresh(target_key, target_host, _ccswitch_settings())


def ccswitch_balance():
    return common_ccswitch.balance(_ccswitch_settings())


# ---------- folder browse ----------
def parent_of(path):
    return common_browse.parent_of(path)


def browse(path, user=None):
    return common_browse.browse(
        path,
        user=user,
        workspace_overview_fn=workspace_overview,
        path_allowed_fn=path_allowed_for_user,
    )


def session_obj(sid, s, host):
    return common_browse.session_obj(
        sid,
        s,
        host,
        normalize_backend_fn=normalize_backend,
        is_codex_backend_fn=is_codex_backend,
    )


# ---------- external push notifications (Telegram / Bark / webhook) ----------
def _notify_settings():
    return common_notify.NotifySettings(
        enabled=NOTIFY_ENABLED,
        events=NOTIFY_EVENTS,
        telegram_token=NOTIFY_TG_TOKEN,
        telegram_chat=NOTIFY_TG_CHAT,
        bark_key=NOTIFY_BARK_KEY,
        webhook_url=NOTIFY_WEBHOOK_URL,
        webhook_secret=NOTIFY_WEBHOOK_SECRET,
        timeout=NOTIFY_TIMEOUT,
        desktop_toast=NOTIFY_DESKTOP_TOAST,
        create_no_window=CREATE_NO_WINDOW,
    )


def _notify_enabled_for(event):
    return common_notify.notify_enabled_for(event, _notify_settings())


def notify_result_text(events, limit=3500):
    return common_notify.notify_result_text(events, limit=limit)


def notify_copy(kind, cwd, actor="Agent", detail="", danger=False):
    return common_notify.notify_copy(kind, cwd, actor=actor, detail=detail, danger=danger)


_ps_quote = common_notify.ps_quote
_DESKTOP_TOAST_PS = common_notify.DESKTOP_TOAST_PS


def desktop_notify(title, body=""):
    return common_notify.desktop_notify(title, body, settings=_notify_settings())


def push_notify(title, body, event, webhook_body=None):
    return common_notify.push_notify(title, body, event, _notify_settings(), webhook_body=webhook_body)


def _webhook_is_feishu(url):
    return common_notify.webhook_is_feishu(url)


def _webhook_send(url, secret, title, body, event, webhook_body=None):
    return common_notify.webhook_send(url, secret, title, body, event,
                                      timeout=NOTIFY_TIMEOUT, webhook_body=webhook_body)


# ---------- shared HTTP handler base ----------
class BaseHandler(common_http.BaseHandler):
    index_path = INDEX
    static_root = ASSETS_DIR


ThreadingServer = common_http.ThreadingServer
